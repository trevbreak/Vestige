# Vestige — DnD AI Avatar System

> **Your absent players, always at the table.**  
> Vestige brings AI-powered avatars to your D&D sessions — characters that listen, react, remember, and roleplay in real-time voice, as if they never left.

---

## Features

### Fully Voiced, In-Character Avatars

Each avatar speaks in its own distinct voice. Vestige ships with a catalogue of regional British and Irish neural voices — automatically matched to the avatar's race, class, and personality at creation time. Assign a brooding Irish ranger a low, deliberate tenor. Give your Welsh druid something ancient and warm. Every character sounds like someone, not something.

### Two-Layer Conversational Presence

Vestige was built to solve the core flaw of every voice AI system: they feel robotic because they're turn-based. Real people at a table don't wait for silence to react — they murmur agreement mid-story, half-start sentences, chime in before you finish.

Vestige uses two parallel layers:

*   **Presence Layer** — real-time, no LLM. Backchannels ("mm", "yeah", "right") played probabilistically while the humans speak. Holding phrases ("Let me think on that…") bridge the generation gap. The avatar is _in the room_.
*   **Reasoning Layer** — a full STT → LLM → TTS cascade with jitter-delayed responses and context-aware routing. Every response sounds considered, not instant.

Combined, avatars feel like they're at the table — not waiting in a queue.

### Intelligent Personality System

Every avatar is driven by a rich, LLM-generated personality prompt — a 150–200 word first-person internal monologue describing how the character thinks, speaks, and chooses when to engage. Dry and clipped? Verbose and digressive? Fierce when threatened, jokey otherwise? It's all there, and it shapes every response.

Four **personality archetypes** govern when an avatar speaks:

*   **Extrovert** — joins most conversations freely
*   **Introvert** — only speaks when directly addressed
*   **Reactive** — engages questions and combat; ignores idle chatter
*   **Stoic** — speaks only when named, addressed, or in combat

A per-avatar **verbosity** dial (0.0–1.0) controls how often ambient triggers produce a response. An **interrupts often** flag lowers the interrupt threshold — some characters just can't help themselves.

### Full D&D 5e Rules Engine

Vestige knows the rules. The built-in rules engine tracks action economy (action, bonus action, reaction, free actions), spell slot expenditure and recovery, concentration, and all standard conditions (stunned, grappled, frightened, and more). Avatars won't cast a spell they've already used. They won't burn a reaction they don't have. Combat turns are tracked automatically and surfaced to the AI context so responses stay tactically coherent.

### Persistent Memory Across Sessions

Avatars remember. Every session is transcribed, embedded, and stored in a local vector database. When something relevant comes up — a name mentioned before, a promise made three sessions ago, a grudge carried forward — Vestige retrieves the right memories and injects them into the AI context. Characters grow over time.

### Smart LLM Routing

Not every response needs the same depth. Vestige routes between two LLM backends based on context type:

*   **Ollama (local, fast)** handles combat turns, casual roleplay, and direct short-answer questions — low latency, no API call.
*   **Claude (Anthropic API)** handles deep roleplay, emotional beats, moral dilemmas, and backstory moments — richer, more considered responses when it matters.

The routing keywords are fully configurable in plain YAML files, editable without restarting the server.

### Configurable Prompts — No Code Required

All keyword lists, holding phrase text, routing rules, and system prompt sections live in editable YAML files under `backend/prompts/`. Change what triggers combat mode. Add new holding phrases. Adjust response length guidance per context type. After editing, a single API call hot-reloads everything atomically.

### LLM Observability with Arize Phoenix

Every LLM call — Claude and Ollama — is traced and surfaced in Arize Phoenix, a local observability UI running at `http://localhost:6006`. Inspect the full system prompt and response for any avatar interaction, review latency and token counts, annotate responses, and run evaluations. Install once, start alongside the backend.

### Inter-Avatar Dynamics

Avatars are aware of each other. They react to what other avatars say, reference each other by name, and can form opinions. Cooldowns and directionality prevent crosstalk spirals. The DM retains full control with override hotwords and session management tools.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  React + Vite Frontend  (http://localhost:5173)                  │
│  Avatars │ Sessions │ Table (live transcript + avatar panels)    │
└────────────────────┬─────────────────────────────────────────────┘
                     │ HTTP REST + WebSocket
┌────────────────────▼─────────────────────────────────────────────┐
│  FastAPI Backend  (http://localhost:8000)                        │
│  /api/avatars  /api/sessions  /api/transcripts  /ws             │
│  SQLite (SQLAlchemy async)  •  Static file serving               │
└──────────────────────────────────────────────────────────────────┘
```

```
Mic → sounddevice → silero-vad → faster-whisper (CUDA)
                                       ↓
                           Backchannel Classifier
                                       ↓
                           Context Engine / LLM Router
                          /                         \
                   Ollama (fast)              Claude API (deep)
                          \                         /
                           Response Post-Processor
                                       ↓
                    XTTS-v2 (CUDA) or Edge-TTS (imageio-ffmpeg) → Speaker

LLM Tracing UI: http://localhost:6006 (separate Phoenix process)
```

### GPU Memory Budget (24 GB)

| Model | VRAM |
| --- | --- |
| faster-whisper large-v3 | ~3 GB |
| Coqui XTTS-v2 | ~3–4 GB |
| Ollama llama3.1:8b Q4 | ~5–6 GB |
| **Total** | **~12 GB** (12 GB headroom) |

---

## Quick Start

### Prerequisites

*   Python 3.12+
*   Node.js 20+
*   NVIDIA GPU with CUDA (for audio pipeline)
*   [Ollama](https://ollama.com/download) installed and running locally
*   Anthropic API key (for Claude routing)
*   No system ffmpeg needed — Edge-TTS MP3 decoding uses the `imageio-ffmpeg` bundled binary (installed automatically via `requirements.txt`)
*   `arize-phoenix` for LLM tracing (optional but recommended): `pip install arize-phoenix`

### 1\. Install and Start Ollama

Vestige uses Ollama for fast, local LLM inference. It must be running before you start the backend.

**Install:** Download from [ollama.com/download](https://ollama.com/download) and run the installer.

**Start the server** (it may already run as a background service after install):

```
ollama serve
```

**Pull the required model:**

```
ollama pull llama3.1:8b
```

**Verify:**

```
curl http://localhost:11434/api/tags
# Should return JSON listing available models
```

> Ollama must stay running while using Vestige. Without it, fast-path responses (combat, roleplay) will be silently skipped.

### 2\. Backend

```
cd backend
python -m venv .venv

# Windows:
.venv\Scripts\pip install -r requirements.txt
# Linux/Mac:
source .venv/bin/activate && pip install -r requirements.txt

cp ../.env.example ../.env
# Edit .env — add ANTHROPIC_API_KEY at minimum

python -m uvicorn app.main:app --reload --port 8000
```

### 3\. Frontend

```
cd frontend
npm install
npm run dev   # opens http://localhost:5173
```

### Startup Order

Start services in this order each session:

1.  `ollama serve` (or confirm it's already running)
2.  Phoenix (optional): `phoenix serve` — starts the tracing UI at `http://localhost:6006`
3.  Backend: `cd backend && .venv/Scripts/uvicorn app.main:app --reload --port 8000`
4.  Frontend: `cd frontend && npm run dev`

---

## Navigation Guide

### Avatars Page — `http://localhost:5173/avatars`

Create and manage your avatar roster. Each avatar has a full D&D 5e character card: race, class, alignment, traits, ideals, bonds, flaws, and backstory. At creation time, Vestige calls Ollama to generate a personality prompt, archetype, verbosity, and voice assignment automatically.

**Key controls:**

*   **Create Avatar** — opens the avatar form. Fill in the character card fields; the personality prompt will be generated on save.
*   **Edit Avatar** — revisit any field including the generated personality prompt, which you can freely edit before saving.
*   **Voice Assignment** — `voice_id` is chosen automatically by Ollama at creation time based on the character's race, class, and personality. Each active avatar is assigned a distinct voice from the catalogue. To reassign all existing avatars, run `scripts/seed_avatar_voices.py`.
*   **Voice Engine** — `tts_engine_preference` switches between `edge` (accent voices, default) and `xtts` (voice cloning from a reference `.wav`). Leave as `auto` to use Edge-TTS when a `voice_id` is set and fall back to XTTS-v2 if a speaker embedding is loaded.
*   **Backfill Personality** — for avatars created before Phase 8, call `POST /api/avatars/generate-personality` to generate missing personality data.

### Sessions Page — `http://localhost:5173/sessions`

Manage campaign sessions. Create a new session to begin tracking a game night; close it when done. Session metadata (date, participant avatars) is stored and linked to all transcripts and memories generated during that session.

### Table Page — `http://localhost:5173/table`

The live game view. This is where you run Vestige during an actual session.

*   **Live transcript** — every spoken utterance is transcribed and displayed in real-time.
*   **Avatar panels** — one panel per active avatar showing current state, last response, and combat status.
*   **DM controls** — override hotwords allow the DM to force an avatar to speak, go silent, or reset state mid-session.
*   **Combat tracker** — initiate and manage combat encounters; the rules engine tracks action economy and spell slots per avatar automatically.

### Settings Page — `http://localhost:5173/settings`

Configure audio devices, microphone selection, and system-level behavior. Changes are persisted to the database and take effect immediately — no restart required.

### Memory Review Page — `http://localhost:5173/memory`

Browse and inspect stored memories per avatar. Memories are vector-embedded summaries of past session transcripts, retrieved and injected into context when relevant. Use this page to audit what an avatar "knows" going into a session.

---

## Monitoring with Arize Phoenix

Phoenix runs as a separate process alongside Vestige. Install it once:

```
pip install arize-phoenix
phoenix serve
```

The backend sends OTel spans to Phoenix automatically when it's running. If Phoenix is not running, the backend starts normally — no errors, just no tracing. Open `**http://localhost:6006**` to access the UI.

### What Phoenix shows you

Phoenix captures every LLM call made by Vestige — both Claude and Ollama — as a trace. Each trace includes:

*   The full system prompt sent to the model (including the injected personality prompt, memory context, and rules state)
*   The user message (what was said at the table)
*   The model's full response
*   Latency (end-to-end and time-to-first-token)
*   Token counts (prompt and completion)
*   Avatar ID and context type as span attributes

### Navigating Phoenix

1.  Open `http://localhost:6006` in your browser.
2.  The **Traces** tab lists every LLM call in reverse chronological order. Click any row to expand the full span detail.
3.  Use the **filter bar** to narrow by avatar ID (`avatar_id = 3`), context type (`context_type = emotional_beat`), or date range.
4.  The **Span Detail** panel shows the full prompt/response, latency breakdown, and all custom attributes.
5.  The **Evaluations** tab allows you to annotate responses (thumbs up/down, free text notes) for quality tracking over time.

Phoenix is read-only from Vestige's perspective — it observes but does not affect the pipeline. You can leave it open during a session to watch traces arrive in real-time.

For advanced workflows (batch evaluations, dataset export, custom metrics), see the [Arize Phoenix docs](https://docs.arize.com/phoenix).

---

## Configuration

Key `.env` settings:

| Variable | Default | Description |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | — | Required for Claude routing |
| `MIC_DEVICE_INDEX` | `0` | Audio device index (run `scripts/list_audio_devices.py`) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `llama3.1:8b` | Model used for fast-path LLM calls |
| `CLAUDE_MODEL` | `claude-haiku-4-5-20251001` | Model used for deep/emotional LLM calls |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/campaign.db` | SQLite path |
| `HOST` | `0.0.0.0` | Backend bind address |
| `PORT` | `8000` | Backend port |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed frontend origins |

### Hot-Reloadable Prompt Files

All routing logic and prompt text lives in `backend/prompts/*.yaml`. Edit these files to customise behavior without touching Python code:

| File | Controls |
| --- | --- |
| `routing_keywords.yaml` | What triggers Claude vs Ollama |
| `context_keywords.yaml` | Combat triggers, DM hotwords, directed fragments |
| `length_instructions.yaml` | Per context-type response length guidance |
| `holding_phrases.yaml` | "Thinking out loud" phrases per context type |
| `system_prompt_sections.yaml` | Static rule strings injected into system prompt |

After editing, reload without restarting:

```
POST http://localhost:8000/api/prompts/reload
```

---

## Project Structure

```
vestige/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # Settings (pydantic-settings)
│   │   ├── tracing.py           # Arize Phoenix + OpenTelemetry init
│   │   ├── db/database.py       # Async engine, session, Base
│   │   ├── models/              # SQLAlchemy models
│   │   ├── schemas/             # Pydantic schemas
│   │   ├── routers/             # API routers + WebSocket
│   │   ├── audio/               # Pipeline, VAD, STT, TTS, AEC, post-processor
│   │   │   └── edge_tts_engine.py  # Edge-TTS accent voices
│   │   ├── llm/                 # Prompt builder, router, dispatcher
│   │   │   └── avatar_generator.py  # LLM-generated personality + voice
│   │   ├── prompts/             # Prompt loader module
│   │   ├── presence/            # Backchannel player, ambient reactions, layer
│   │   └── services/            # Business logic (pipeline manager, etc.)
│   ├── prompts/                 # Editable YAML prompt/keyword files
│   ├── alembic/                 # DB migrations
│   ├── tests/                   # pytest test suite (305 tests)
│   ├── requirements.txt
│   └── pytest.ini
├── frontend/
│   ├── src/
│   │   ├── api/client.js        # Fetch wrapper for all endpoints
│   │   ├── stores/              # Zustand state stores
│   │   ├── components/          # Reusable UI components
│   │   └── pages/               # Avatars, Sessions, Table, Settings, MemoryReview
│   └── package.json
├── voice_samples/               # Avatar voice .wav reference files
├── data/                        # SQLite DB (gitignored)
├── docs/                        # Per-phase implementation notes
├── scripts/                     # Setup / utility scripts
├── plan.md                      # Master build plan
├── .env.example
└── README.md
```

---

## Running Tests

```
cd backend
.venv/Scripts/python -m pytest tests/ -v
```

305 tests across all phases. All should pass on a clean install.

---

## Documentation

*   [Phase 1 — Foundation](docs/phase1-foundation.md)
*   [Phase 2 — Voice Input Pipeline](docs/phase2-voice-input.md)
*   [Phase 3 — Voice Output Pipeline](docs/phase3-voice-output.md)
*   [Phase 4 — AI Brain](docs/phase4-ai-brain.md)
*   [Phase 5 — Memory System](docs/phase5-memory.md)
*   [Phase 6 — Rules Engine & Combat](docs/phase6-rules.md)
*   [Phase 7 — Polish & Inter-Avatar Dynamics](docs/phase7-polish.md)
*   [Phase 8 — Avatar Personality & Voice Behaviors](docs/phase8-avatar-personality-behaviors.md)

---

## Build Status

| Phase | Description | Status |
| --- | --- | --- |
| **1** | Foundation — API, DB schema, avatar/session CRUD, D&D UI | ✅ Complete |
| **2** | Voice Input — mic capture, VAD (silero), STT (faster-whisper), AEC | ✅ Complete |
| **3** | Voice Output — XTTS-v2 TTS, voice cloning, backchannel pre-gen | ✅ Complete |
| **4** | AI Brain — Ollama/Claude router, context engine, prompt builder | ✅ Complete |
| **5** | Memory — session transcripts, embeddings, sqlite-vec retrieval | ✅ Complete |
| **6** | Rules Engine — D&D 5e action economy, spells, conditions, combat | ✅ Complete |
| **7** | Polish — inter-avatar dynamics, DM controls, settings panel | ✅ Complete |
| **8** | Avatar Realism — personality prompts, differentiated voices, Phoenix tracing | ✅ Complete |