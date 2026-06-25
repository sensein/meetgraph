# Prompt — Structured JSON (mode C)

For pipeline use: emit one JSON object conforming to `schemas/meeting-summary.schema.json`.
Mirror the JSON discipline used elsewhere: strict JSON, `temperature: 0`, no markdown fences.

---

**System message (include verbatim):**

> You convert a meeting transcript into a single JSON object. Output strict JSON only. No prose. No markdown fences. Use `null` for any field whose value is not stated in the transcript — never guess owners, dates, or decisions.

**User message:** the schema below, then the transcript.

## Target schema (summary)

```json
{
  "meeting": {
    "title": "string | null",
    "date": "string | null (ISO 8601 if a date is stated)",
    "participants": ["string", "..."],
    "purpose": "string | null"
  },
  "topics": [
    { "topic": "string", "points": ["string", "..."], "attribution": "string | null" }
  ],
  "decisions": ["string", "..."],
  "open_questions": ["string", "..."],
  "action_items": [
    { "item": "string", "owner": "string | null", "due": "string | null" }
  ]
}
```

Validate against `schemas/meeting-summary.schema.json` before returning.

## Rules

- **Strict JSON, no fences, `temperature: 0`.**
- **Faithful.** Only transcript-grounded content. Unknown owner/date → `null`, not a guess. Empty list → `[]`, not `null`.
- **`points`** are short, paraphrased, factual statements — not quotes, not whole paragraphs.
- **`attribution`** names the person whose view a topic primarily reflects, when one person owns it; otherwise `null`.
- **`decisions`** vs **`action_items`**: a decision is something settled; an action item is something to be done. Conditional decisions keep their condition in the string (e.g. "If commercialized, output inherits the NC license").
- Preserve hedges inside the strings ("considered unsettled," "publishers may disagree") rather than dropping them.

## Repair

If the model returns invalid JSON, strip any ```json fences and re-parse; if still invalid, re-prompt with the parser error and the schema, asking only for corrected JSON.

---

Schema:

{{SCHEMA}}

Transcript:

{{TRANSCRIPT}}
