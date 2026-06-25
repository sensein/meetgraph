"""Transcription engines.

Two interchangeable backends behind a common ``Transcriber`` interface:

* :class:`LocalWhisperTranscriber` — faster-whisper, runs fully on-device.
* :class:`OpenAITranscriber`        — OpenAI's hosted transcription API.

Both take a 16 kHz mono float32 numpy array and return plain text.
"""

from __future__ import annotations

import io
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


class LocalWhisperTranscriber(Transcriber):
    """On-device transcription via faster-whisper (CTranslate2)."""

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "auto",
        language: str | None = None,
    ):
        from faster_whisper import WhisperModel  # lazy: heavy import

        # CTranslate2 has no CUDA on macOS; "auto" -> CPU with int8 here.
        if compute_type == "auto":
            compute_type = "int8"
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
        return LocalWhisperTranscriber(
            model_size=config.get("model_size", "base"),
            language=language,
        )
    if engine == "openai":
        return OpenAITranscriber(
            api_key=config.get("api_key", ""),
            model=config.get("openai_model", "whisper-1"),
            language=language,
        )
    raise ValueError(f"Unknown engine: {engine!r}")
