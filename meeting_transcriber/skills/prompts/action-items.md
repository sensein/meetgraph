# Prompt — Action items & decisions (mode B)

For when the user only wants the follow-ups and what was settled — no narrative.

---

You extract the actionable outcomes of a meeting from its transcript. Output only what was decided, what needs doing, and what is still open. No summary, no narrative, no recap of discussion.

## Input

A meeting transcript (raw or cleaned). Reconstruct meaning from messy speech-to-text; ignore filler and cross-talk.

## Output

Three sections, each a list. Omit a section only if it would be empty.

**Decisions** — things the group actually agreed, settled, or chose. One line each.

**Action items** — concrete next steps, one per line, in the form:
`- [owner or "unassigned"] action — (any due date or trigger stated, else omit)`
Use an owner only if the transcript names or clearly implies one. Never invent owners or deadlines. If a deadline was stated ("by Friday," "before launch"), include it; otherwise leave it off.

**Open questions** — anything explicitly deferred, unresolved, or "we'll figure it out later," one line each.

## Rules

- Faithful only: nothing that wasn't in the transcript.
- An item is an **action** only if someone is (or should be) doing something. A statement of fact or opinion is not an action.
- Preserve conditional framing ("if we commercialize, then …") rather than asserting it unconditionally.
- Paraphrase tightly; no long quotes.
- If the meeting produced no decisions or actions, say so in one line instead of padding.

---

Transcript:

{{TRANSCRIPT}}
