"""Transcript model + Markdown rendering and sharing helpers."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Entry:
    timestamp: datetime
    speaker: str   # "You" / "Meeting"
    text: str


@dataclass
class Transcript:
    title: str = "Meeting Transcript"
    started_at: datetime | None = None
    entries: list[Entry] = field(default_factory=list)

    def add(self, speaker: str, text: str, when: datetime | None = None) -> Entry:
        entry = Entry(timestamp=when or datetime.now(), speaker=speaker, text=text)
        self.entries.append(entry)
        return entry

    def clear(self) -> None:
        self.entries.clear()
        self.started_at = None

    def to_plain(self) -> str:
        """Speaker-labelled plain text (used for the on-screen/live transcript)."""
        return "\n".join(f"{e.speaker}: {e.text}" for e in self.entries)

    def to_content(self) -> str:
        """Spoken content without speaker/diarization labels - what the notes
        agent summarizes. Keeping diarization (Speaker 1/2/...) out of the summary
        means notes describe *what was said*, not a per-person breakdown."""
        return "\n".join(e.text for e in self.entries)

    def to_markdown(self) -> str:
        lines: list[str] = [f"# {self.title}", ""]
        started = self.started_at or (self.entries[0].timestamp if self.entries else None)
        if started:
            lines.append(f"*Recorded: {started:%Y-%m-%d %H:%M}*")
            lines.append("")
        speakers = sorted({e.speaker for e in self.entries})
        if speakers:
            lines.append(f"*Sources: {', '.join(speakers)}*")
            lines.append("")
        lines.append("---")
        lines.append("")
        for e in self.entries:
            lines.append(f"**[{e.timestamp:%H:%M:%S}] {e.speaker}:** {e.text}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def save_markdown(self, path: str) -> str:
        md = self.to_markdown()
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        return path


def reveal_in_file_manager(path: str) -> None:
    """Reveal/select the saved file in the OS file manager (cross-platform)."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", path], check=False)
        elif sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", os.path.normpath(path)], check=False)
        else:  # Linux / other: open the containing folder
            folder = os.path.dirname(os.path.abspath(path)) or "."
            subprocess.run(["xdg-open", folder], check=False)
    except Exception:
        pass
