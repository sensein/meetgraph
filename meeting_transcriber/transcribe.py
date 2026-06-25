"""Transcription engines.

Two interchangeable backends behind a common ``Transcriber`` interface:

* :class:`LocalWhisperTranscriber` — faster-whisper, runs fully on-device.
* :class:`OpenAITranscriber`        — OpenAI's hosted transcription API.

Both take a 16 kHz mono float32 numpy array and return plain text.
"""

from __future__ import annotations

import io
import sys
import wave
from abc import ABC, abstractmethod

import numpy as np


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe 16 kHz mono float32 audio and return text."""

    def close(self) -> None:  # optional cleanup hook
        pass


def _float_to_wav_bytes(audio: np.ndarray, rate: int = 16_000) -> bytes:
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


import importlib.util
import platform


def _has_cuda() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() in ("arm64", "aarch64")


def hardware_caps() -> dict:
    """What acceleration is available on this machine."""
    apple = _is_apple_silicon()
    return {
        "cuda": _has_cuda(),                                   # NVIDIA (faster-whisper/CT2)
        "apple": apple,                                        # Apple Silicon
        "mlx": apple and importlib.util.find_spec("mlx_whisper") is not None,  # Apple GPU via MLX
    }


def resolve_device(choice: str = "auto") -> str:
    """Resolve 'auto' to the best available backend: cuda > mlx (Apple) > cpu."""
    if choice and choice != "auto":
        return choice
    caps = hardware_caps()
    if caps["cuda"]:
        return "cuda"
    if caps["mlx"]:
        return "mlx"
    return "cpu"


def compute_label(choice: str = "auto") -> str:
    dev = resolve_device(choice)
    return {"cuda": "GPU · CUDA", "mlx": "GPU · Apple Silicon (MLX)", "cpu": "CPU"}.get(dev, "CPU")


def detect_compute() -> tuple[str, str, str]:
    """CTranslate2 device/precision for the faster-whisper path (CUDA or CPU only)."""
    if _has_cuda():
        return "cuda", "float16", "GPU · CUDA"
    return "cpu", "int8", "CPU"


class MLXWhisperTranscriber(Transcriber):
    """Apple-Silicon GPU transcription via MLX (mlx-whisper)."""

    _PRESET = {
        "tiny": "mlx-community/whisper-tiny-mlx",
        "base": "mlx-community/whisper-base-mlx",
        "small": "mlx-community/whisper-small-mlx",
        "medium": "mlx-community/whisper-medium-mlx",
        "large-v3": "mlx-community/whisper-large-v3-mlx",
        "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    }

    def __init__(self, model_size: str = "base", language: str | None = None):
        import mlx_whisper  # lazy: Apple-only

        self._mlx = mlx_whisper
        self.repo = model_size if "/" in model_size else self._PRESET.get(model_size, self._PRESET["base"])
        self.language = language or None

    def transcribe(self, audio: np.ndarray) -> str:
        result = self._mlx.transcribe(
            audio.astype(np.float32), path_or_hf_repo=self.repo, language=self.language
        )
        return (result.get("text") or "").strip()


class LocalWhisperTranscriber(Transcriber):
    """On-device transcription via faster-whisper (CTranslate2).

    ``model_size`` may be a preset (tiny/base/small/medium/large-v3) **or** any
    HuggingFace CTranslate2 Whisper repo id / local path (e.g.
    ``deepdml/faster-whisper-large-v3-turbo-ct2``).
    """

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "auto",
        language: str | None = None,
    ):
        from faster_whisper import WhisperModel  # lazy: heavy import

        if device == "auto" or compute_type == "auto":
            d, c, _ = detect_compute()
            device = d if device == "auto" else device
            compute_type = c if compute_type == "auto" else compute_type
        self.device = device
        self.compute_type = compute_type
        self.language = language or None
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio: np.ndarray) -> str:
        segments, _ = self.model.transcribe(
            audio.astype(np.float32),
            language=self.language,
            beam_size=1,
            vad_filter=False,  # we already segmented upstream
        )
        return " ".join(s.text.strip() for s in segments).strip()


class OpenAITranscriber(Transcriber):
    """Hosted transcription via the OpenAI audio API."""

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-1",
        language: str | None = None,
    ):
        from openai import OpenAI  # lazy import

        if not api_key:
            raise ValueError("An OpenAI API key is required for the cloud engine.")
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.language = language or None

    def transcribe(self, audio: np.ndarray) -> str:
        wav = _float_to_wav_bytes(audio)
        kwargs = {"model": self.model, "file": ("audio.wav", wav, "audio/wav")}
        if self.language:
            kwargs["language"] = self.language
        resp = self.client.audio.transcriptions.create(**kwargs)
        return (resp.text or "").strip()


def make_transcriber(config: dict) -> Transcriber:
    """Factory used by the UI. ``config['engine']`` is 'local' or 'openai'."""
    engine = config.get("engine", "local")
    language = config.get("language") or None
    if engine == "local":
        device = resolve_device(config.get("device", "auto"))
        if device == "mlx":
            return MLXWhisperTranscriber(
                model_size=config.get("model_size", "base"), language=language
            )
        compute_type = config.get("compute_type") or "auto"
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"
        return LocalWhisperTranscriber(
            model_size=config.get("model_size", "base"),
            device=device,
            compute_type=compute_type,
            language=language,
        )
    if engine == "openai":
        return OpenAITranscriber(
            api_key=config.get("api_key", ""),
            model=config.get("openai_model", "whisper-1"),
            language=language,
        )
    raise ValueError(f"Unknown engine: {engine!r}")
