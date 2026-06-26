"""Lightweight online speaker diarization.

We transcribe per voice-activity segment, so diarization here means: give each
utterance a consistent speaker label (``Speaker 1``, ``Speaker 2``, ...) by
embedding the audio and clustering online (nearest-centroid with a similarity
threshold). The embedding uses ``pyannote.audio`` (optional dependency, needs a
HuggingFace token to download the model); if it isn't available, diarization is
a no-op and we fall back to the audio-source label.

This runs on the local machine - cloud transcription APIs (e.g. OpenAI) do not
return speaker labels, so local diarization is how speakers get separated.
"""

from __future__ import annotations

import numpy as np


class OnlineDiarizer:
    """Assign a stable ``Speaker N`` label to successive embeddings (online)."""

    def __init__(self, threshold: float = 0.70):
        self.threshold = threshold
        self._centroids: list[np.ndarray] = []
        self._counts: list[int] = []
        self._labels: list[str] = []

    @staticmethod
    def _cos(a: np.ndarray, b: np.ndarray) -> float:
        denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
        return float(np.dot(a, b) / denom)

    def assign(self, emb: np.ndarray) -> str:
        emb = np.asarray(emb, dtype="float64").reshape(-1)
        best_sim, best_i = -1.0, -1
        for i, c in enumerate(self._centroids):
            s = self._cos(emb, c)
            if s > best_sim:
                best_sim, best_i = s, i
        if best_i >= 0 and best_sim >= self.threshold:
            n = self._counts[best_i]
            self._centroids[best_i] = (self._centroids[best_i] * n + emb) / (n + 1)
            self._counts[best_i] += 1
            return self._labels[best_i]
        label = f"Speaker {len(self._centroids) + 1}"
        self._centroids.append(emb)
        self._counts.append(1)
        self._labels.append(label)
        return label


class SpeakerLabeler:
    """Embeds an utterance and returns a consistent speaker label, or None.

    Prefers **Resemblyzer** (bundled model, no token, no download) and falls back
    to **pyannote.audio** (needs a HuggingFace token) if Resemblyzer isn't present.
    """

    def __init__(self, hf_token: str | None = None, threshold: float = 0.72):
        self._diar = OnlineDiarizer(threshold)
        self._embed = None
        self.backend = None

        # 1) Resemblyzer - token-free, model ships with the package.
        try:
            from resemblyzer import VoiceEncoder

            enc = VoiceEncoder(verbose=False)
            self._embed = lambda audio, rate: enc.embed_utterance(
                np.ascontiguousarray(audio, dtype="float32"))
            self.backend = "resemblyzer"
        except Exception:
            self._embed = None

        # 2) pyannote fallback (gated model -> needs a HF token).
        if self._embed is None:
            try:
                import torch
                from pyannote.audio import Inference, Model

                model = Model.from_pretrained("pyannote/embedding", use_auth_token=hf_token or True)
                inf = Inference(model, window="whole")

                def _emb(audio, rate):
                    wav = torch.from_numpy(np.ascontiguousarray(audio, dtype="float32")).unsqueeze(0)
                    return np.asarray(inf({"waveform": wav, "sample_rate": rate})).reshape(-1)

                self._embed = _emb
                self.backend = "pyannote"
            except Exception:
                self._embed = None

    @property
    def available(self) -> bool:
        return self._embed is not None

    def label(self, audio: np.ndarray, rate: int = 16_000) -> str | None:
        if self._embed is None or audio is None or len(audio) < int(0.4 * rate):
            return None  # too short to embed reliably -> fall back to source label
        try:
            emb = np.asarray(self._embed(audio, rate)).reshape(-1)
            return self._diar.assign(emb)
        except Exception:
            return None
