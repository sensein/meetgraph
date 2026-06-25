# Installing & using this skill

This is a standard `SKILL.md` skill — a folder with frontmatter that lets a model discover it from the `description`.

## Claude Code

Drop the folder into a skills directory:

```
~/.claude/skills/meeting-notes/        # available in every project
# or
<project>/.claude/skills/meeting-notes/   # available in this project only
```

The skill is auto-discovered from the `name`/`description` in `SKILL.md`. Then just ask, e.g. *"summarize this transcript"* with a `.vtt` attached, and the model loads the relevant prompt.

## Claude Cowork / claude.ai

Upload the folder as a skill (or zip and upload). The same `description` drives when it triggers.

## Using the pieces directly (no skill runtime)

- **Clean a transcript** for any tool:
  ```
  python scripts/clean_transcript.py meeting.vtt -o meeting.clean.txt
  ```
- **Summarize**: paste the contents of `prompts/summary-full.md` (or `action-items.md`) into any LLM, replacing `{{TRANSCRIPT}}` with the cleaned text.
- **Pipeline / JSON**: use `prompts/structured-json.md` as the system+user prompt, substitute `{{SCHEMA}}` with `schemas/meeting-summary.schema.json` and `{{TRANSCRIPT}}` with the text, run at `temperature: 0`, then validate the output against the schema.

## Notes

- `clean_transcript.py` is standard-library only (Python 3.8+); no install needed.
- Speaker detection keys off WebVTT `<v Name>` tags or `Name:` line prefixes. Single-word section labels like `Note:` or `Action:` are intentionally **not** treated as speakers (see the stopword list in the script).
- License: MIT — change the `license` field in `SKILL.md` to suit your project.
