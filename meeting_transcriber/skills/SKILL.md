---
name: meeting-notes
version: 0.1.0
description: Turn a meeting, call, or interview transcript into clean, faithful notes. Use this skill when the user uploads or pastes a transcript (WebVTT/SRT/plain text, with or without speaker labels and timestamps) and asks to summarize it, pull out action items or decisions, extract follow-ups, or convert the discussion into structured notes. Three output modes — a topic-organized summary, an action-items/decisions list, or strict JSON for a pipeline — and a dependency-free transcript cleaner (clean_transcript.py) that strips cue numbers and timestamps and merges speaker turns.
license: MIT
---

# Meeting Notes — transcripts into faithful, structured notes

A small, reliable methodology for converting a raw transcript into notes someone can act on. The emphasis is **faithfulness**: capture what was actually said and decided, preserve hedges and uncertainty, attribute positions to the right person, and never invent owners, dates, or conclusions.

## When to invoke this skill

Trigger when the user:

- Uploads or pastes a **meeting / call / interview transcript** and asks for a summary or notes.
- Wants the **action items**, **decisions**, **follow-ups**, or **open questions** pulled out of a discussion.
- Wants a discussion converted into a **structured object** (JSON) for storage or a downstream pipeline.
- Hands over a `.vtt` / `.srt` file, a Zoom/Teams/Meet transcript, or speaker-labelled text and wants it made useful.

Not for: drafting a meeting *agenda* from scratch, writing minutes for a meeting that didn't happen, or transcribing audio (this skill starts from text).

## The method

Three steps. Step 1 is optional but recommended for raw VTT/SRT.

```
  raw transcript           clean text                notes
 ┌──────────────┐  clean  ┌──────────────┐  choose  ┌──────────────────────┐
 │ .vtt / .srt  │────────►│ Speaker:     │  mode    │ A. topic summary     │
 │ Zoom / Teams │ (script)│ turns merged │─────────►│ B. action items      │
 │ plain text   │         │ ts stripped  │          │ C. strict JSON       │
 └──────────────┘         └──────────────┘          └──────────────────────┘
```

1. **Clean (optional).** For timestamped VTT/SRT, run `scripts/clean_transcript.py` to strip cue numbers/timestamps, drop inline tags, detect speakers, and merge consecutive same-speaker turns. This shrinks tokens and makes attribution reliable. Skip it if the input is already clean speaker-labelled text.
2. **Pick an output mode.** See the table below.
3. **Summarize faithfully** using the matching prompt in `prompts/`, obeying the Hard rules.

## Output modes

| Mode | Use when | Prompt | Shape |
|---|---|---|---|
| **A. Full summary** | The user wants readable notes / minutes. | `prompts/summary-full.md` | Context · Key points by topic · Decisions · Open questions · Action items |
| **B. Action items** | The user only wants the follow-ups and what was settled. | `prompts/action-items.md` | Decisions · Action items (owner if stated) · Open questions |
| **C. Structured JSON** | Output feeds storage, a tracker, or a pipeline. | `prompts/structured-json.md` | Strict JSON conforming to `schemas/meeting-summary.schema.json` |

When in doubt, mode A. If the user has already seen a long summary and asks "now just the to-dos," switch to mode B against the same transcript.

## Hard rules

These prevent the failures that make notes untrustworthy.

1. **Be faithful.** Include only what is in the transcript. Do not add outside facts, fill gaps with assumptions, or infer owners/dates that were never stated. If an action has no clear owner, leave it unassigned.
2. **Preserve nuance.** Keep caveats and hedges intact — "X said this is unsettled," "their read, not formal advice," "still being litigated," "we'll see." Never flatten a tentative opinion into a firm fact.
3. **Attribute where it matters.** When a position, commitment, or judgment belongs to a specific person, name them ("Per [name], …"). Neutral factual recaps don't need attribution.
4. **Separate firm from tentative.** Make explicit what was *decided* versus what was speculation, a personal view, or deferred.
5. **Paraphrase, don't quote.** Use your own words. Reserve short direct quotes for wording that is itself decision-critical (an exact commitment, a precise legal phrase, a specific number).
6. **Flag the messy parts.** If a thread was inconclusive, contradictory, or cut off, say so — don't paper over it to make the notes look tidy.
7. **Organize by topic, not by clock.** Group related discussion even if it was scattered across the meeting. Chronological retelling buries the substance.
8. **No invented structure.** For mode C, emit only fields defined in the schema; use `null` for unknown owners/dates rather than guessing.

## File map (load on demand)

### `prompts/`
- `summary-full.md` — mode A: the topic-organized summary (the default).
- `action-items.md` — mode B: decisions, action items with owners, open questions only.
- `structured-json.md` — mode C: strict-JSON extraction against the schema (temperature 0, no fences).

### `schemas/`
- `meeting-summary.schema.json` — JSON Schema (draft-07) for mode C output.

### `scripts/`
- `clean_transcript.py` — WebVTT/SRT/plain → speaker-attributed plain text. Dependency-free.
  `python clean_transcript.py TRANSCRIPT [--keep-timestamps] [--no-merge] [--speakers] [-o OUT]`

### `examples/`
- `example.md` — a worked example: messy VTT snippet → cleaned text → mode A and mode C outputs.

## Minimal mental model

> Clean the transcript so each line is `Speaker: text`. Then write notes that are faithful, organized by topic, keep the hedges, name who said what when it matters, and never invent an owner or a decision. Pick prose (A), a to-do list (B), or schema-locked JSON (C) depending on where the notes are going.
