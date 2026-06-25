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
    started = pyqtSignal()
    stopped = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._seg_queue: "queue.Queue[Segment | None]" = queue.Queue()
        self._captures: list[CaptureWorker] = []
        self._worker: threading.Thread | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self, config: dict, sources: list[tuple[InputDevice, str]]) -> None:
        """``config`` -> engine settings; ``sources`` -> list of (device, label)."""
        if self._running:
            return
        threading.Thread(target=self._start_impl, args=(config, sources), daemon=True).start()

    def _start_impl(self, config: dict, sources: list[tuple[InputDevice, str]]) -> None:
        try:
            self.status.emit("Loading transcription engine…")
            transcriber = make_transcriber(config)
        except Exception as exc:
            self.error.emit(f"Could not start engine: {exc}")
            return

        self._seg_queue = queue.Queue()
        self._captures = []
        threshold = float(config.get("threshold", 0.012))
        for device, label in sources:
            cw = CaptureWorker(device, label, self._seg_queue, threshold=threshold)
            self._captures.append(cw)

        self._running = True
        self._worker = threading.Thread(
            target=self._transcribe_loop, args=(transcriber,), daemon=True, name="transcribe"
        )
        self._worker.start()
        for cw in self._captures:
            cw.start()

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
                    self.new_text.emit(seg.label, datetime.now(), text)
        finally:
            try:
                transcriber.close()
            except Exception:
                pass

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self.status.emit("Stopping…")
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
        self._seg_queue.put(None)  # release transcription worker (after final flush)
        if self._worker:
            try:
                self._worker.join(timeout=15.0)
            except Exception:
                pass
        self._captures = []
        self._worker = None
        self.stopped.emit()
        self.status.emit("Stopped.")
