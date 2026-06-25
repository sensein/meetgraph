# MeetGraph

> *Turning meetings into a knowledge graph…*

A cross-platform desktop app (PyQt6) that records your **microphone** *and* the
**meeting/system audio** (Zoom, Teams, Meet, …) and transcribes both to text in
**real time**. Transcripts are saved as **Markdown** and easily shared.

- 🎙️ Captures mic + system audio as separate, labelled speakers (*You* / *Meeting*)
- ⚡ Live transcription with voice-activity segmentation
- 🔁 Two interchangeable engines — **Local (faster-whisper)** or **OpenAI API**
- 🤖 **AI meeting notes** — a Pydantic AI agent turns the transcript into structured
  notes (topics · decisions · open questions · action items), provider-agnostic:
  **Claude, OpenAI, OpenRouter, or any open-source / local OpenAI-compatible server**
- 📝 Export to Markdown · copy to clipboard · reveal in file manager to share
- 🖥️ Works on **macOS, Windows, and Linux**

---

## 1. Install

Requires **Python 3.10–3.13** (3.12 recommended; 3.14 has no wheels yet for some deps)
and the system **PortAudio** library.

```bash
# system audio library
#   macOS:        brew install portaudio
#   Debian/Ubuntu: sudo apt install portaudio19-dev libportaudio2
#   Fedora:        sudo dnf install portaudio
#   Windows:       bundled with the sounddevice wheel — nothing to install

python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt   # Windows: .venv\Scripts\python
```

## 2. Run

```bash
./run.sh
# or:
.venv/bin/python -m meeting_transcriber
```

---

## 3. Capturing meeting (system) audio

Operating systems don't let an app record other apps' audio directly, so you
route system audio through a **virtual loopback device** that then appears as a
normal input. The app auto-detects the common ones and pre-selects it in the
**Meeting / system audio** dropdown.

### macOS — BlackHole
1. Install: `brew install blackhole-2ch` (already installed on this machine ✅).
2. Open **Audio MIDI Setup** → **＋** → *Create Multi-Output Device*.
3. Tick **both** your speakers/headphones **and** *BlackHole 2ch* so you still
   hear the call while it's captured.
4. Set that Multi-Output Device as your Mac's **Output** (and/or as Zoom's speaker).
5. In the app, pick **BlackHole 2ch** as the system-audio source.

### Windows — Stereo Mix or VB-Cable
- Many machines have **Stereo Mix**: Sound settings → Recording → enable
  *Stereo Mix*, then select it as the system-audio source.
- Otherwise install **[VB-Audio Cable](https://vb-audio.com/Cable/)** (free),
  set it as your playback device, and pick **CABLE Output** in the app.

### Linux — PulseAudio / PipeWire monitor
- Every output has a `.monitor` source. Pick the device whose name contains
  `monitor` (e.g. *Monitor of Built-in Audio*) as the system-audio source.
  `pavucontrol` can help route specific apps.

> Tip: capturing only your **microphone** needs none of the above — just leave
> the *Meeting / system audio* box unchecked.

---

## 4. Choosing an engine

| | Local (faster-whisper) | OpenAI API |
|---|---|---|
| Cost | Free | Per-minute API cost |
| Privacy | 100% on-device | Audio sent to OpenAI |
| Internet | Not required | Required |
| Setup | One-time model download | Needs API key |
| Models | `tiny`→`large-v3` | `whisper-1`, `gpt-4o-transcribe`, … |

For OpenAI, paste your key in the app or set `OPENAI_API_KEY` in your environment.

---

## 5. Output & sharing

- **Copy Markdown** — full transcript to clipboard.
- **Save .md** — write a Markdown file.
- **Share…** — saves the `.md` and reveals it in your file manager so you can
  right-click → *Share*, drag it into Slack/email, or attach it anywhere.

Example output:

```markdown
# Meeting Transcript

*Recorded: 2026-06-25 10:00*
*Sources: Meeting, You*

---

**[10:00:05] You:** Hello there
**[10:00:09] Meeting:** Hi, can you hear me?
```

---

## 6. AI meeting notes (structured)

Click **✦ Generate Meeting Notes** to run a [Pydantic AI](https://ai.pydantic.dev)
agent over the live transcript. It produces a faithful, schema-validated
`MeetingSummary` (meeting info · topics · decisions · open questions · action
items) following the bundled **`meeting-notes`** skill's rules — never inventing
owners, dates, or decisions. The dialog lets you copy / save (`.md` + `.json`) /
share the result.

Pick any **provider** in the UI, with your own **API key** and **base URL**:

| Provider | Default model | Base URL | Notes |
|---|---|---|---|
| **Claude (Anthropic)** | `claude-opus-4-8` | default | Most capable; needs `ANTHROPIC_API_KEY` |
| **OpenAI** | `gpt-4o` | default | Needs `OPENAI_API_KEY` |
| **OpenRouter** | `anthropic/claude-opus-4-8` | `https://openrouter.ai/api/v1` | Any OpenRouter model id |
| **Open-source / Custom** | `llama3.1` | `http://localhost:11434/v1` | Ollama / vLLM / LM Studio — key usually not required |

CLI equivalent (also handles `.vtt` / `.srt` via the skill's cleaner):

```bash
.venv/bin/python -m meeting_transcriber.agent transcript.md \
  --provider anthropic --model claude-opus-4-8        # --json for raw JSON
.venv/bin/python -m meeting_transcriber.agent call.vtt \
  --provider opensource --base-url http://localhost:11434/v1 --model llama3.1
```

The agent and the transcription engine are **independent** — e.g. transcribe
locally with faster-whisper, then summarize with a local Ollama model, fully offline.

---

## Project layout

```
meeting_transcriber/
  audio.py        # PortAudio capture + RMS/silence voice-activity segmentation
  transcribe.py   # Local (faster-whisper) + OpenAI engines behind one interface
  transcript.py   # Transcript model, Markdown rendering, sharing helpers
  controller.py   # Threads: capture → queue → transcription → Qt signals
  agent.py        # Provider-agnostic Pydantic AI notes agent (Claude/OpenAI/OpenRouter/local)
  ui.py           # PyQt6 window
  skills/         # Bundled "meeting-notes" skill (schema, prompts, transcript cleaner)
  __main__.py     # entry point  (python -m meeting_transcriber)
```

## Notes & tuning
- Transcription is **segment-based**: speech is split on short silences (≈0.6 s)
  and each utterance is transcribed, so text appears a beat after you pause.
- If quiet speech is missed or noise creates phantom segments, adjust the RMS
  `threshold` in `Segmenter` (`audio.py`).
- Larger local models are more accurate but slower; `base`/`small` are a good
  real-time balance on Apple Silicon.
```
