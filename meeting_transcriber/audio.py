"""Audio capture and voice-activity segmentation.

We open a PortAudio input stream per source (microphone, system audio), downmix
to mono, resample to 16 kHz (Whisper's native rate) and chop the stream into
utterance-sized segments using a simple RMS/silence voice-activity detector.

Each finished segment is pushed onto a shared queue as a ``Segment`` and picked
up by the transcription worker.
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from dataclasses import dataclass

import numpy as np

try:  # high quality resampler; falls back to linear interpolation if missing
    import soxr

    _HAVE_SOXR = True
except Exception:  # pragma: no cover
    _HAVE_SOXR = False

import sounddevice as sd

TARGET_RATE = 16_000


@dataclass
class Segment:
    """A finished utterance ready for transcription."""

    label: str          # "You" / "Meeting"
    audio: np.ndarray   # float32, mono, 16 kHz, range [-1, 1]


@dataclass
class InputDevice:
    index: int
    name: str
    default_samplerate: int
    max_input_channels: int

    def __str__(self) -> str:  # shown in the UI dropdowns
        return f"[{self.index}] {self.name}"


def list_input_devices() -> list[InputDevice]:
    """Return every device that exposes at least one input channel."""
    devices = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            devices.append(
                InputDevice(
                    index=idx,
                    name=dev["name"],
                    default_samplerate=int(dev["default_samplerate"] or TARGET_RATE),
                    max_input_channels=int(dev["max_input_channels"]),
                )
            )
    return devices


# Names of common loopback / virtual-cable devices that carry system audio,
# across macOS, Windows and Linux (PulseAudio/PipeWire).
_SYSTEM_AUDIO_HINTS = (
    "blackhole",      # macOS (BlackHole)
    "loopback",       # macOS (Rogue Amoeba Loopback), Windows WASAPI loopback
    "soundflower",    # macOS (legacy)
    "stereo mix",     # Windows (Realtek)
    "what u hear",    # Windows (Creative)
    "vb-audio",       # Windows/macOS (VB-Cable)
    "cable output",   # Windows (VB-Cable)
    "voicemeeter",    # Windows (VoiceMeeter)
    ".monitor",       # Linux PulseAudio/PipeWire monitor source
    "monitor of",     # Linux PulseAudio monitor (descriptive name)
)


def find_system_audio_device(devices: list[InputDevice]) -> InputDevice | None:
    """Best guess at the device carrying meeting/system audio on any platform."""
    for dev in devices:
        name = dev.name.lower()
        if any(hint in name for hint in _SYSTEM_AUDIO_HINTS):
            return dev
    return None


def _resample_to_16k(audio: np.ndarray, in_rate: int) -> np.ndarray:
    if in_rate == TARGET_RATE:
        return audio.astype(np.float32, copy=False)
    if _HAVE_SOXR:
        return soxr.resample(audio, in_rate, TARGET_RATE).astype(np.float32)
    # Linear-interpolation fallback (good enough for speech).
    n_out = int(round(len(audio) * TARGET_RATE / in_rate))
    if n_out <= 1:
        return np.zeros(0, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


class Segmenter:
    """Energy/silence based utterance segmenter operating on 16 kHz mono float32."""

    def __init__(
        self,
        sample_rate: int = TARGET_RATE,
        threshold: float = 0.010,
        hangover_sec: float = 0.6,
        max_sec: float = 8.0,
        min_speech_sec: float = 0.4,
        preroll_sec: float = 0.25,
        frame_sec: float = 0.03,
    ):
        self.threshold = threshold
        self.frame = max(1, int(sample_rate * frame_sec))
        self.hangover = int(sample_rate * hangover_sec)
        self.max_samples = int(sample_rate * max_sec)
        self.min_speech = int(sample_rate * min_speech_sec)
        preroll_frames = max(1, int(preroll_sec / frame_sec))

        self._leftover = np.zeros(0, dtype=np.float32)
        self._preroll: deque[np.ndarray] = deque(maxlen=preroll_frames)
        self._buf: list[np.ndarray] = []
        self._in_speech = False
        self._silence_run = 0
        self._speech_samples = 0
        self._seg_samples = 0

    def set_threshold(self, value: float) -> None:
        self.threshold = max(0.0, float(value))

    def add(self, audio: np.ndarray) -> list[np.ndarray]:
        """Feed new audio; return any utterance segments that just completed."""
        finished: list[np.ndarray] = []
        data = np.concatenate([self._leftover, audio]) if self._leftover.size else audio
        n_frames = len(data) // self.frame
        self._leftover = data[n_frames * self.frame:].copy()

        for i in range(n_frames):
            frame = data[i * self.frame:(i + 1) * self.frame]
            rms = float(np.sqrt(np.mean(frame * frame))) if frame.size else 0.0
            is_speech = rms >= self.threshold

            if not self._in_speech:
                self._preroll.append(frame)
                if is_speech:
                    self._in_speech = True
                    self._buf = list(self._preroll)
                    self._seg_samples = sum(len(f) for f in self._buf)
                    self._speech_samples = self.frame
                    self._silence_run = 0
            else:
                self._buf.append(frame)
                self._seg_samples += self.frame
                if is_speech:
                    self._silence_run = 0
                    self._speech_samples += self.frame
                else:
                    self._silence_run += self.frame

                if self._silence_run >= self.hangover or self._seg_samples >= self.max_samples:
                    seg = self._finish()
                    if seg is not None:
                        finished.append(seg)
        return finished

    def flush(self) -> list[np.ndarray]:
        seg = self._finish()
        return [seg] if seg is not None else []

    def _finish(self) -> np.ndarray | None:
        emit = None
        if self._buf and self._speech_samples >= self.min_speech:
            emit = np.concatenate(self._buf).astype(np.float32)
        self._buf = []
        self._preroll.clear()
        self._in_speech = False
        self._silence_run = 0
        self._speech_samples = 0
        self._seg_samples = 0
        return emit


class CaptureWorker(threading.Thread):
    """Captures one input device and emits utterance ``Segment``s onto a queue."""

    def __init__(
        self,
        device: InputDevice,
        label: str,
        out_queue: "queue.Queue[Segment]",
        threshold: float = 0.012,
    ):
        super().__init__(daemon=True, name=f"capture-{label}")
        self.device = device
        self.label = label
        self.out_queue = out_queue
        # NOTE: do not name this ``_stop`` - that shadows threading.Thread._stop()
        # and breaks join().
        self._stop_event = threading.Event()
        self._raw: "queue.Queue[np.ndarray]" = queue.Queue()
        self._channels = min(2, max(1, device.max_input_channels))
        self.segmenter = Segmenter(threshold=threshold)
        self.error: str | None = None

    def stop(self) -> None:
        self._stop_event.set()

    def _callback(self, indata, frames, time_info, status):  # noqa: ANN001
        # Runs on the PortAudio thread - keep it light.
        self._raw.put(indata.copy())

    def run(self) -> None:
        in_rate = self.device.default_samplerate
        try:
            with sd.InputStream(
                device=self.device.index,
                channels=self._channels,
                samplerate=in_rate,
                dtype="float32",
                callback=self._callback,
            ):
                while not self._stop_event.is_set():
                    try:
                        block = self._raw.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    mono = block.mean(axis=1) if block.ndim > 1 else block
                    audio16 = _resample_to_16k(mono, in_rate)
                    for seg in self.segmenter.add(audio16):
                        self.out_queue.put(Segment(self.label, seg))
        except Exception as exc:  # surface device/stream errors to the UI
            self.error = f"{self.label}: {exc}"
            return

        for seg in self.segmenter.flush():
            self.out_queue.put(Segment(self.label, seg))
