"""Glue between audio capture, transcription engine and the Qt UI.

Capture workers push utterance ``Segment``s onto a queue; a single transcription
worker drains the queue (keeping ordering and serializing access to the model)
and emits results to the UI via Qt signals.
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal

from .audio import CaptureWorker, InputDevice, Segment
from .transcribe import make_transcriber


class TranscriptionController(QObject):
    # speaker, timestamp, text
    new_text = pyqtSignal(str, datetime, str)
    status = pyqtSignal(str)
    started = pyqtSignal()   # fired on start and on resume
    paused = pyqtSignal()
    stopped = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._seg_queue: "queue.Queue[Segment | None]" = queue.Queue()
        self._captures: list[CaptureWorker] = []
        self._worker: threading.Thread | None = None
        self._running = False
        self._paused = False
        self._sources: list[tuple[InputDevice, str]] = []
        self._threshold = 0.012
        self._diarizer = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    def start(self, config: dict, sources: list[tuple[InputDevice, str]]) -> None:
        """``config`` -> engine settings; ``sources`` -> list of (device, label)."""
        if self._running:
            return
        self._sources = sources
        self._threshold = float(config.get("threshold", 0.012))
        threading.Thread(target=self._start_impl, args=(config,), daemon=True).start()

    def _start_captures(self) -> None:
        self._captures = []
        for device, label in self._sources:
            cw = CaptureWorker(device, label, self._seg_queue, threshold=self._threshold)
            self._captures.append(cw)
        for cw in self._captures:
            cw.start()

    def _stop_captures(self) -> None:
        for cw in self._captures:
            try:
                cw.stop()
            except Exception:
                pass
        for cw in self._captures:
            try:
                cw.join(timeout=3.0)  # lets the final-flush segments enqueue
            except Exception:
                pass
        self._captures = []

    def _start_impl(self, config: dict) -> None:
        try:
            self.status.emit("Loading transcription engine…")
            transcriber = make_transcriber(config)
        except Exception as exc:
            self.error.emit(f"Could not start engine: {exc}")
            return

        # Optional local speaker diarization (consistent Speaker N labels).
        self._diarizer = None
        if config.get("diarization") == "local":
            try:
                from .diarize import SpeakerLabeler

                self.status.emit("Loading speaker diarization model…")
                labeler = SpeakerLabeler(hf_token=config.get("hf_token") or None)
                if labeler.available:
                    self._diarizer = labeler
                else:
                    self.status.emit("Speaker labels off — install pyannote.audio + set a HuggingFace "
                                     "token to enable. Labelling by audio source.")
            except Exception:
                self.status.emit("Speaker labels off (diarization unavailable). Labelling by source.")

        self._seg_queue = queue.Queue()
        self._running = True
        self._paused = False
        self._worker = threading.Thread(
            target=self._transcribe_loop, args=(transcriber,), daemon=True, name="transcribe"
        )
        self._worker.start()
        self._start_captures()

        self.started.emit()
        self.status.emit("Listening… speak or play meeting audio.")

    def pause(self) -> None:
        """Stop capturing but keep the session (transcript + engine) so you can resume."""
        if not self._running or self._paused:
            return
        self._paused = True
        self._stop_captures()  # transcription worker + engine stay alive
        self.paused.emit()
        self.status.emit("Paused — click Resume to continue.")

    def resume(self) -> None:
        if not self._running or not self._paused:
            return
        self._paused = False
        self._start_captures()
        self.started.emit()
        self.status.emit("Listening… speak or play meeting audio.")

    def _transcribe_loop(self, transcriber) -> None:  # noqa: ANN001
        try:
            while True:
                seg = self._seg_queue.get()
                if seg is None:  # sentinel
                    break
                # Surface any capture-thread failures.
                for cw in self._captures:
                    if cw.error:
                        self.error.emit(cw.error)
                        cw.error = None
                try:
                    text = transcriber.transcribe(seg.audio)
                except Exception as exc:
                    self.error.emit(f"Transcription failed: {exc}")
                    continue
                if text:
                    label = seg.label
                    if self._diarizer is not None:
                        spk = self._diarizer.label(seg.audio)
                        if spk:  # anonymous, consistent speaker id across the meeting
                            label = spk
                    self.new_text.emit(label, datetime.now(), text)
        finally:
            try:
                transcriber.close()
            except Exception:
                pass

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._paused = False
        self.status.emit("Stopping…")
        self._stop_captures()
        self._seg_queue.put(None)  # release transcription worker (after final flush)
        if self._worker:
            try:
                self._worker.join(timeout=15.0)
            except Exception:
                pass
        self._worker = None
        self.stopped.emit()
        self.status.emit("Stopped.")
