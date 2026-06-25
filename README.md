# MeetGraph

> *Turning meetings into a knowledge graph…*

A cross-platform desktop app (PyQt6) that records your **microphone** *and* the
**meeting/system audio** (Zoom, Teams, Meet, …), transcribes both in **real time**,
and turns the conversation into structured, linked, shareable knowledge.

- 🎙️ Captures mic + system audio as separate, labelled speakers (*You* / *Meeting*)
- ⚡ Live transcription with voice-activity segmentation
- 🖥️ **Auto-detects the best accelerator** — Apple Silicon GPU (MLX), NVIDIA CUDA, or CPU
- 🔁 Transcription engines: **Local Whisper**, **OpenAI**, or any **OpenAI-compatible** audio endpoint (Groq, self-hosted, …)
- 🤖 **AI meeting notes** — a provider-agnostic Pydantic AI agent (Claude / OpenAI / OpenRouter / local Ollama) produces faithful notes (topics · decisions · open questions · action items), and **fixes obvious transcription errors**
- 🔗 **Key terms auto-linked to Wikipedia + Wikidata** (verified, clickable)
- 🧠 **Knowledge graph** — every meeting exported as RDF (JSON-LD / Turtle / N-Quads) conforming to the bundled **MCO** ontology, with PROV temporal data
- 🕸️ **Automatic cross-meeting linking** — an agent connects related meetings (shared topics/entities, follow-ups, continuations)
- 🔬 **PubMed** — for scientific discussions, links relevant publications (with a few key points each) and proposes **research gaps**
- 👥 **Teams** — one shareable key centralizes everyone's notes in a shared database; in-app team feed; audit log of who-did-what
- 🗄️ **Bring your own database** — relational (PostgreSQL/MySQL/SQLite via SQLAlchemy) **or MongoDB**, and a **graph triplestore** (Oxigraph/Fuseki/GraphDB/Blazegraph) — endpoints auto-derived by type
- 📤 **Send anywhere** — email (SMTP), REST webhook, MCP server — per-meeting or in bulk, with de-duplication
- 🔄 Background enrichment with **status + auto-resume** if interrupted
- 💾 Local **SQLite** storage; searchable summary table; per-meeting detail windows
- 🌍 Works on **macOS, Windows, and Linux**

---

## 1. Install

Requires **Python 3.10–3.13** and the system **PortAudio** library.

```bash
# system audio library
#   macOS:         brew install portaudio
#   Debian/Ubuntu: sudo apt install portaudio19-dev libportaudio2
#   Fedora:        sudo dnf install portaudio
#   Windows:       bundled with the sounddevice wheel — nothing to install

python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt   # Windows: .venv\Scripts\python
```

Optional extras are only needed for specific features and degrade gracefully if
missing: `mlx-whisper` (Apple-GPU transcription, macOS arm64), `pyoxigraph`
(graph export — included), `SQLAlchemy` + a DB driver (relational sync),
`pymongo` (MongoDB), `mcp` (MCP delivery).

## 2. Run

```bash
./run.sh        # or:  .venv/bin/python -m meeting_transcriber
```

First launch asks your **name** (and optional email, used for team activity logs).
Paste a **team key** here to join a team instantly.

---

## 3. Capturing meeting (system) audio

OSes don't let an app record other apps' audio directly, so route system audio
through a **virtual loopback** that appears as a normal input. The app
auto-detects the common ones.

- **macOS — BlackHole:** `brew install blackhole-2ch`, create a Multi-Output Device
  (your speakers + BlackHole) in *Audio MIDI Setup*, set it as output, then pick
  **BlackHole 2ch** in the app.
- **Windows — Stereo Mix / VB-Cable:** enable *Stereo Mix*, or install
  [VB-Audio Cable](https://vb-audio.com/Cable/) and pick **CABLE Output**.
- **Linux — PulseAudio/PipeWire monitor:** pick the device whose name contains
  `monitor`.

> Mic-only capture needs none of this — just leave *Meeting / system audio* unchecked.

---

## 4. Transcription engine & acceleration

Pick an engine in **Configuration → Transcription engine**:

| Engine | Notes |
|---|---|
| **Local — Whisper** | faster-whisper (CPU/CUDA) or **Apple MLX** (Apple-GPU). Free, on-device. |
| **OpenAI** | `whisper-1`, `gpt-4o-transcribe`, … (needs `OPENAI_API_KEY`). |
| **OpenAI-compatible** | Pick a provider (Groq, OpenRouter, Anthropic, local server, custom); endpoint auto-filled. Calls the standard `/audio/transcriptions` API, so new providers work as they add speech-to-text. |

The **Compute** selector auto-resolves to the best device (Apple GPU / CUDA / CPU);
unavailable options are disabled. Configured models are **pre-downloaded when you
leave Configuration**, so there's no cold-start wait on Start.

> Note: speech-to-text needs an audio model — Claude/Anthropic and OpenRouter don't
> offer one, so transcription uses Whisper/OpenAI/compatible. Your Claude/OpenRouter
> choice is still used to write the **notes**.

---

## 5. AI meeting notes

The live summary regenerates **automatically as you talk** (no button), and a
final pass runs on Stop. Notes are a faithful, schema-validated `MeetingSummary`
(meeting info · topics · decisions · open questions · action items · key terms),
following the bundled **`meeting-notes`** skill — never inventing owners, dates,
or decisions, but silently fixing obvious speech-to-text errors.

| Provider | Default model | Base URL |
|---|---|---|
| **Claude (Anthropic)** | `claude-opus-4-8` | default |
| **OpenAI** | `gpt-4o` | default |
| **OpenRouter** | `anthropic/claude-opus-4-8` | `https://openrouter.ai/api/v1` |
| **Open-source / Custom** | `llama3.1` | `http://localhost:11434/v1` (Ollama/vLLM/LM Studio) |

**Key terms** are resolved to verified **Wikipedia** articles and **Wikidata**
entities (clickable). For **scientific** meetings (enable *Scientific literature*
+ optional NCBI API key), MeetGraph searches **PubMed**, attaches the relevant
publications with a few key points each, and lists **research gaps**.

CLI (also handles `.vtt` / `.srt`):

```bash
.venv/bin/python -m meeting_transcriber.agent transcript.md --provider anthropic   # --json for raw JSON
```

---

## 6. Knowledge graph & cross-meeting links

Each meeting exports as RDF — **JSON-LD / Turtle / N-Quads** — conforming to the
**Meeting Content Ontology** (`meeting_transcriber/skills/schemas/mco.yaml`), with
PROV temporal data (`startedAtTime` / `endedAtTime` / `generatedAtTime`), key-term
links, cited publications, and team membership.

- **Export RDF…** on a meeting, or **⬡ Export graph** for the whole connected corpus.
- After each meeting, a **cross-link agent** connects it to related meetings
  (shared entities/topics, follow-ups, continuations) — shown as *Related meetings*.
- Enrichment runs in the background with a **status** indicator and **auto-resumes**
  if the app was closed mid-process.

---

## 7. Storage, databases & teams

- **Local:** everything is stored in SQLite; the **Summary** tab is a searchable
  table; click a row for a detail window (copy / export `.md` / RDF / email / send).
- **External databases** (Configuration → *External databases*): mirror meetings to
  your own **relational** DB (PostgreSQL/MySQL/SQLite, or **MongoDB**) and/or a
  **graph triplestore** (Oxigraph/Fuseki/GraphDB/Blazegraph). Pick the DB type and
  enter a base URL — endpoints are derived automatically. **Storage mode**
  (Local + Remote / Remote only / Local only) and **Sync policy** (mirror incl.
  deletions / add-only) control what syncs. Enabling a DB auto-backfills existing
  meetings.
- **Teams:** generate a shareable **team key** (bundles the shared DB config) — issue
  several, view, copy, or **revoke** them. Teammates **join** with the key (on the
  welcome screen or in Configuration) and their notes flow into the shared DB.
  The **Team meetings (shared DB)** toggle shows everyone's meetings in-app. Every
  action (create / summary / delete / send / sync) is recorded in an **audit log**
  with the member's name + email, mirrored centrally.

## 8. Sending & sharing

Send a meeting's summary + transcript to:

- **Email** (SMTP — Configuration → *Email*; "Fill from team members" pulls teammate addresses)
- **REST API** webhook (JSON payload)
- **MCP** server tool

Use **Email…/Send…** on a meeting, or **⇪ Send…** on the Summary tab for **bulk**
send across meetings — already-sent items are skipped (de-duplicated).

---

## Project layout

```
meeting_transcriber/
  audio.py        # PortAudio capture + voice-activity segmentation
  transcribe.py   # Local (faster-whisper/MLX) + OpenAI/compatible engines; accelerator detection
  transcript.py   # Transcript model, Markdown rendering, sharing helpers
  controller.py   # Threads: capture → queue → transcription → Qt signals
  agent.py        # Provider-agnostic notes agent; key-term + PubMed enrichment
  wikipedia.py    # Verified Wikipedia/Wikidata resolution
  pubmed.py       # NCBI E-utilities (search + abstracts)
  crosslink.py    # Automatic cross-meeting linking (deterministic + agent)
  kg.py           # RDF/knowledge-graph build & serialize (pyoxigraph)
  external.py     # Relational/Mongo + graph sinks; team revocation registry
  email_send.py   # SMTP delivery
  delivery.py     # REST + MCP delivery
  team.py         # Shareable team keys
  storage.py      # SQLite (content DB + separate config DB; jobs, audit, links)
  ui.py           # PyQt6 window
  skills/         # Bundled "meeting-notes" skill + MCO ontology (schemas/mco.yaml)
  __main__.py     # entry point  (python -m meeting_transcriber)
```

## Notes & tuning
- Transcription is **segment-based**: speech is split on short silences and each
  utterance transcribed, so text appears a beat after you pause.
- Larger local models are more accurate but slower; `base`/`small` are a good
  real-time balance on Apple Silicon.
- The config database (API keys, DB credentials, team key) is kept **separate**
  from your meeting content and is readable only by your user account.
```
