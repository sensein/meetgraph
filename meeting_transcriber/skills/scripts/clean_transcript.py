#!/usr/bin/env python3
"""
clean_transcript.py — turn a WebVTT / SRT / plain transcript into clean,
speaker-attributed plain text that is easy to summarize.

What it does
------------
- Strips cue numbers, timestamps, and NOTE / STYLE / REGION blocks.
- Removes inline tags (<i>, <c>, <00:00:00.000>, ...).
- Detects speakers from WebVTT <v Speaker> voice tags or "Name: text" prefixes.
- Merges consecutive cues from the same speaker into one turn.

Usage
-----
    python clean_transcript.py TRANSCRIPT [options]

Options
-------
    --keep-timestamps    Prefix each turn with [start -> end].
    --no-merge           Keep one line per cue (do not merge same-speaker runs).
    --speakers           Print the detected speaker list to stderr.
    -o, --output FILE    Write to FILE instead of stdout.

Format (.vtt / .srt / plain text) is auto-detected. Standard library only.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from typing import List, Optional, Set

ARROW = re.compile(r"-->")
# WebVTT uses 00:00:00.000, SRT uses 00:00:00,000; the hour field is optional.
TIME = re.compile(r"(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}")
VOICE = re.compile(r"^<v\s+([^>]+)>(.*?)(?:</v>)?$", re.IGNORECASE | re.DOTALL)
TAG = re.compile(r"<[^>]+>")
# A speaker label is 1–4 capitalised tokens (handles "Tek Raj Chhetri").
NAME = re.compile(r"^[A-Z][\w.'\u2019\-]*(?:\s+[A-Z][\w.'\u2019\-]*){0,3}$")
# "Speaker: text" — colon within the first 40 chars.
PREFIX = re.compile(r"^\s*([^:\n]{1,40}?):\s+(.*\S)\s*$", re.DOTALL)
# Capitalised sentence-starters / section labels that are NOT speaker names.
# A prefix whose first token is here is rejected even if it looks like a name.
STOP = {
    "okay", "ok", "so", "yeah", "yes", "no", "well", "right", "sure", "and",
    "but", "then", "now", "hi", "hey", "hello", "thanks", "thank", "note",
    "question", "answer", "action", "re", "subject", "date", "from", "to",
    "update", "edit", "warning", "error", "example", "summary", "conclusion",
    "background", "todo", "fyi", "ps", "caveat", "agenda", "topic", "decision",
}


@dataclass
class Cue:
    start: Optional[str]
    end: Optional[str]
    speaker: Optional[str]
    text: str


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        return fh.read()


def split_time(ts_line: str):
    left, _, right = ts_line.partition("-->")

    def first(side: str):
        m = TIME.search(side)
        return m.group(0).replace(",", ".") if m else None

    return first(left), first(right)


def parse(raw: str) -> List[Cue]:
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    # Plain text (no timestamps anywhere): treat each non-empty line as a cue.
    if "-->" not in raw:
        return [Cue(None, None, None, ln.strip()) for ln in raw.split("\n") if ln.strip()]

    # Drop a leading WEBVTT header and its metadata (up to the first blank line).
    lines = raw.split("\n")
    if lines and lines[0].lstrip().upper().startswith("WEBVTT"):
        i = 1
        while i < len(lines) and lines[i].strip():
            i += 1
        raw = "\n".join(lines[i:])

    cues: List[Cue] = []
    for block in re.split(r"\n\s*\n", raw):
        blines = block.split("\n")
        if not blines:
            continue
        if blines[0].strip().upper().startswith(("NOTE", "STYLE", "REGION")):
            continue

        ts_idx = next((i for i, ln in enumerate(blines) if ARROW.search(ln)), None)
        if ts_idx is None:
            start = end = None
            payload = [ln for ln in blines if ln.strip()]
        else:
            start, end = split_time(blines[ts_idx])
            payload = [ln for ln in blines[ts_idx + 1:] if ln.strip()]
        if not payload:
            continue

        text = " ".join(p.strip() for p in payload).strip()
        speaker = None
        m = VOICE.match(text)
        if m:
            speaker = m.group(1).strip()
            text = m.group(2)
        text = re.sub(r"\s+", " ", TAG.sub("", text)).strip()
        if text:
            cues.append(Cue(start, end, speaker, text))
    return cues


def _candidate(text: str) -> Optional[str]:
    """Return the speaker label if ``text`` starts with a 'Name: ' prefix."""
    m = PREFIX.match(text)
    if not m:
        return None
    sp = m.group(1).strip()
    if not NAME.match(sp):
        return None
    if sp.split()[0].lower() in STOP:
        return None
    return sp


def detect_speakers(cues: List[Cue]) -> Set[str]:
    return {sp for c in cues if not c.speaker and (sp := _candidate(c.text))}


def assign_speakers(cues: List[Cue], speakers: Set[str]) -> None:
    for c in cues:
        if c.speaker:
            continue
        sp = _candidate(c.text)
        if sp and sp in speakers:
            c.speaker = sp
            c.text = PREFIX.match(c.text).group(2).strip()


def merge_turns(cues: List[Cue]) -> List[Cue]:
    out: List[Cue] = []
    for c in cues:
        if out and (out[-1].speaker == c.speaker or c.speaker is None) and out[-1].speaker is not None:
            out[-1].text = (out[-1].text + " " + c.text).strip()
            out[-1].end = c.end or out[-1].end
        else:
            out.append(Cue(c.start, c.end, c.speaker, c.text))
    return out


def render(cues: List[Cue], keep_ts: bool = False) -> str:
    chunks = []
    for c in cues:
        label = f"{c.speaker}: " if c.speaker else ""
        ts = f"[{c.start} -> {c.end or ''}] " if (keep_ts and c.start) else ""
        chunks.append(f"{ts}{label}{c.text}")
    return "\n\n".join(chunks) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Clean a WebVTT/SRT/plain transcript for summarization.")
    ap.add_argument("transcript", help="Path to .vtt, .srt, or plain-text transcript.")
    ap.add_argument("--keep-timestamps", action="store_true", help="Prefix each turn with [start -> end].")
    ap.add_argument("--no-merge", action="store_true", help="Do not merge consecutive same-speaker cues.")
    ap.add_argument("--speakers", action="store_true", help="Print detected speakers to stderr.")
    ap.add_argument("-o", "--output", help="Write to FILE instead of stdout.")
    args = ap.parse_args(argv)

    cues = parse(read_text(args.transcript))
    speakers = detect_speakers(cues)
    assign_speakers(cues, speakers)
    if not args.no_merge:
        cues = merge_turns(cues)

    if args.speakers:
        found = sorted({c.speaker for c in cues if c.speaker})
        print("Detected speakers: " + (", ".join(found) if found else "(none)"), file=sys.stderr)

    text = render(cues, keep_ts=args.keep_timestamps)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
