# Worked example

A short, self-contained run through the method on a small fictional meeting.

## 0. Raw input (`standup.vtt`)

```
WEBVTT

1
00:00:02.100 --> 00:00:05.400
Priya: Okay so, um, the API migration — where are we on that?

2
00:00:05.400 --> 00:00:09.000
Marcus: We're, we're basically done. Just the auth endpoints left.

3
00:00:09.000 --> 00:00:12.500
Marcus: I can finish those by Thursday I think.

4
00:00:12.500 --> 00:00:16.200
Priya: Great. Let's hold the release until auth is in. No partial cutover.

5
00:00:16.200 --> 00:00:20.800
Dana: One thing — we still haven't decided whether to keep the v1 endpoints alive.

6
00:00:20.800 --> 00:00:23.000
Priya: Yeah, let's park that for next week.
```

## 1. Clean

```
$ python scripts/clean_transcript.py standup.vtt --speakers
Detected speakers: Dana, Marcus, Priya        # (stderr)

Priya: Okay so, um, the API migration — where are we on that?

Marcus: We're, we're basically done. Just the auth endpoints left. I can finish those by Thursday I think.

Priya: Great. Let's hold the release until auth is in. No partial cutover.

Dana: One thing — we still haven't decided whether to keep the v1 endpoints alive.

Priya: Yeah, let's park that for next week.
```

Cue numbers and timestamps are gone, Marcus's two cues are merged, and speakers are detected.

## 2a. Mode A — full summary

> **Context** — Engineering standup; status check on the API migration.
>
> **Key points by topic**
> - *API migration* — Per Marcus, the migration is essentially complete; only the auth endpoints remain, which he expects to finish by Thursday.
> - *v1 endpoints* — Dana raised that the team hasn't decided whether to keep the old v1 endpoints running.
>
> **Decisions**
> - Hold the release until the auth endpoints are merged — no partial cutover.
>
> **Open questions**
> - Whether to keep the v1 endpoints alive (parked for next week).
>
> **Action items**
> - Marcus — finish the auth endpoints, by Thursday.

Note what the rules enforce: Marcus's estimate stays hedged ("expects," "by Thursday I think" → "expects to … by Thursday"), the v1 question is logged as open rather than resolved, and no owner is invented for the parked decision.

## 2b. Mode C — structured JSON

```json
{
  "meeting": {
    "title": null,
    "date": null,
    "participants": ["Priya", "Marcus", "Dana"],
    "purpose": "Engineering standup — API migration status"
  },
  "topics": [
    {
      "topic": "API migration",
      "points": [
        "Migration is essentially complete; only auth endpoints remain.",
        "Marcus expects to finish the auth endpoints by Thursday."
      ],
      "attribution": "Marcus"
    },
    {
      "topic": "v1 endpoints",
      "points": ["Undecided whether to keep the old v1 endpoints running."],
      "attribution": "Dana"
    }
  ],
  "decisions": [
    "Hold the release until auth endpoints are merged; no partial cutover."
  ],
  "open_questions": [
    "Whether to keep the v1 endpoints alive (parked for next week)."
  ],
  "action_items": [
    { "item": "Finish the auth endpoints", "owner": "Marcus", "due": "Thursday" }
  ]
}
```

`title` and `date` are `null` because the transcript never states them — they are not guessed.
