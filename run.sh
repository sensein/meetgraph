#!/usr/bin/env bash
# Launch the Meeting Transcriber app.
set -e
cd "$(dirname "$0")"
exec .venv/bin/python -m meeting_transcriber
