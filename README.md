# Vestige — DnD AI Avatar System

> **Your absent players, always at the table.**  
> Vestige brings AI-powered avatars to your D&D sessions — characters that listen, react, remember, and roleplay in real-time voice, as if they never left.

---

## Features

### Fully Voiced, In-Character Avatars

Each avatar speaks in its own distinct voice via ElevenLabs streaming TTS. Assign a distinct ElevenLabs voice to each character and tune expressiveness with per-avatar stability, style, and similarity sliders. Emotion tags (`[somber]`, `[excited]`, `[laughing]`) are injected automatically before synthesis via a secondary LLM pass, so combat lines sound tense and triumphant moments feel earned.

Two model tracks let you balance quality against latency:

- **`eleven_v3`** (~300ms TTFB) — supports inline emotion and sound tags; used for roleplay, emotional beats, and backstory moments
- **`eleven_flash_v2_5`** (~170ms TTFB) — no tags, pure speed; used for combat turns and quick reactions

### Sub-Second Transcript Latency

Speech-to-text uses Deepgram's nova-3 streaming WebSocket. Unlike batch STT systems that wait for silence, Deepgram handles VAD and endpointing internally and fires the `speech_final` callback within ~200ms of sentence completion — dramatically reducing the time from someone speaking to the avatar beginning to respond.

### Two-Layer Conversational Presence

Vestige uses two parallel layers to prevent the turn-based feel of most voice AI:

- **Presence Layer** — real-time, no LLM. Backchannels ("mm", "yeah", "right") played probabilistically while humans speak. Holding phrases bridge the generation gap. The avatar is _in the room_.
- **Reasoning Layer** — full STT → LLM → TTS cascade with jitter-delayed responses and context-aware routing. Every response sounds considered, not instant.

### Avatar-to-Avatar Banter

When one avatar speaks, other avatars evaluate whether to react — producing natural multi-avatar exchanges, disagreements, and collaborative problem-solving without human input. A chain depth limit (default 3) and per-archetype gates prevent crosstalk spirals:

- **Stoic** avatars never react to avatar speech unless directly named
- **Introvert** avatars react at most once per minute to other avatars
- All avatars use an 8-second cooldown between avatar-speech reactions

### Intelligent Personality System

Every avatar is driven by a rich, LLM-generated personality prompt — a 150–200 word first-person internal monologue describing how the character thinks, speaks, and chooses when to engage.

Four **personality archetypes** govern when an avatar speaks:

- **Extrovert** — joins most conversations freely
- **Introvert** — only speaks when directly addressed
- **Reactive** — engages questions and combat; ignores idle chatter
- **Stoic** — speaks only when named, addressed, or in combat

### Character Trait Evolution

Avatars develop persistent psychological traits from campaign events. A spider encounter leaves an arachnophobia that lingers for weeks. Betrayal by a party member creates measured distrust. Each trait has:

- **Strength** (0–1) that decays ~10% per week without reinforcement
- **Trigger keywords** that fire a stochastic manifestation check when they appear in the transcript
- **Emotional signatures** that override the TTS emotion tag when the trait manifests
- **Active trait injection** into the system prompt so the LLM knows what tensions are present

Structured relationship axes (trust, affection, respect) evolve similarly and are extracted from post-session summaries by Claude.

### Smart LLM Routing

Vestige routes between two backends based on context type:

- **GPT-4o** handles combat turns, casual roleplay, and direct questions — fast, with ~460ms average latency
- **Claude Sonnet 4.6** handles emotional beats, moral dilemmas, backstory calls, and NPC social encounters — richer responses with prompt caching enabled (system prompt cached; dynamic sections bypass the cache)

Routing keywords are fully configurable in plain YAML files.

### Full D&D 5e Rules Engine

The built-in rules engine tracks action economy, spell slot expenditure and recovery, concentration, and all standard conditions. Avatars won't cast a spell they've already used. Combat turns are tracked automatically and surfaced to the AI context.

### Persistent Memory Across Sessions

Every session is transcribed, embedded, and stored in a local vector database. Relevant memories — a name mentioned before, a promise made three sessions ago, a grudge carried forward — are retrieved and injected into context. Post-session summaries include psychological trait and relationship deltas extracted by Claude.

Layered summary context: the last 6 prior session summaries are injected when generating a new one, giving the model a running narrative thread.

### LLM Observability with Arize Phoenix

Every LLM call is traced and surfaced in Arize Phoenix at `http://localhost:6006`. Inspect full prompts, responses, latency, token counts (including cache hits), and avatar/context attributes.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    BROWSER  ·  http://localhost:5173                         │
│                                                                              │
│   ┌─────────────┐  ┌──────────┐  ┌──────────────────────┐  ┌────────────┐  │
│   │  Avatars    │  │ Sessions │  │  Table (live game)   │  │ Settings / │  │
│   │  (CRUD +    │  │  (CRUD + │  │  transcript • avatar │  │  Memory /  │  │
│   │   voices)   │  │  history)│  │  panels • DM controls│  │  Traits    │  │
│   └─────────────┘  └──────────┘  └──────────────────────┘  └────────────┘  │
│                         React 19 + Vite 7 + Zustand + CSS Modules            │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │  HTTP REST + WebSocket (/ws)
┌──────────────────────────────────▼───────────────────────────────────────────┐
│                    BACKEND  ·  http://localhost:8000                         │
│                    FastAPI 0.115  ·  Python 3.13                             │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                        AUDIO PIPELINE                                │   │
│  │                                                                      │   │
│  │  🎤 Mic → PCM frames                                                 │   │
│  │   └─ AEC Gate ──► Deepgram STT (nova-3, streaming WebSocket)        │   │
│  │                        ↓ speech_final (~200ms latency)               │   │
│  │           ┌────────────────────────┐                                 │   │
│  │           │  Backchannel Classifier│──► Presence Layer               │   │
│  │           └──────────┬─────────────┘    (backchannels + holding)    │   │
│  │                      ▼                                               │   │
│  │           ┌────────────────────────┐                                 │   │
│  │           │  Context Engine        │                                 │   │
│  │           │  · overlap detector    │                                 │   │
│  │           │  · per-avatar eval     │                                 │   │
│  │           │  · archetype/verbosity │                                 │   │
│  │           │  · avatar-speech gates │                                 │   │
│  │           │  · trait trigger check │                                 │   │
│  │           └──────────┬─────────────┘                                │   │
│  │                      │ DispatchRequest                               │   │
│  │                      ▼                                               │   │
│  │     ┌─────────────────────────────────────────────┐                 │   │
│  │     │               LLM DISPATCHER                │                 │   │
│  │     │                                             │                 │   │
│  │     │  Memory Retriever (sqlite-vec)               │                 │   │
│  │     │  Prompt Builder (author framing, actor      │                 │   │
│  │     │    offset, active traits, YAML-driven)      │                 │   │
│  │     │  Cross-Avatar Referencer                    │                 │   │
│  │     │  Rules Engine (D&D 5e)                      │                 │   │
│  │     │         ↓ route selection                   │                 │   │
│  │     │  ┌─────────────────┐  ┌──────────────────┐  │                 │   │
│  │     │  │ GPT-4o          │  │ Claude Sonnet 4.6│  │                 │   │
│  │     │  │ (fast-path)     │  │ (deep-path,      │  │                 │   │
│  │     │  │ combat, roleplay│  │  emotional,      │  │                 │   │
│  │     │  │ questions       │  │  backstory,      │  │                 │   │
│  │     │  │                 │  │  + prompt cache) │  │                 │   │
│  │     │  └────────┬────────┘  └────────┬─────────┘  │                 │   │
│  │     │           └──────────┬──────────┘            │                 │   │
│  │     └──────────────────────┼──────────────────────-┘                │   │
│  │                            ▼                                         │   │
│  │          ┌──────────────────────────────────┐                       │   │
│  │          │  Response Post-Processor         │                       │   │
│  │          │  · emotion tag / trait override  │                       │   │
│  │          │  · audio tag injection (Haiku)   │                       │   │
│  │          └──────────────────┬───────────────┘                       │   │
│  │                             ▼                                        │   │
│  │          ┌──────────────────────────────────┐                       │   │
│  │          │  TTS ENGINE                      │                       │   │
│  │          │                                  │                       │   │
│  │          │  ElevenLabs (primary)            │                       │   │
│  │          │  · eleven_v3 (300ms, emotion     │                       │   │
│  │          │    tags, quality)                │                       │   │
│  │          │  · eleven_flash_v2_5 (170ms,     │                       │   │
│  │          │    combat/quick)                 │                       │   │
│  │          │  Streams raw PCM chunks → browser│                       │   │
│  │          │  (plays before synthesis done)   │                       │   │
│  │          │         ── fallbacks ──           │                       │   │
│  │          │  Edge-TTS  /  XTTS-v2 (CUDA)     │                       │   │
│  │          └──────────────────────────────────┘                       │   │
│  │                                        ▼                             │   │
│  │                              🔊 Browser AudioContext                 │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────┐   ┌────────────────────────────────────────┐  │
│  │  SQLite (aiosqlite)      │   │  Arize Phoenix (optional, separate     │  │
│  │  · avatars / sessions    │   │  process)  ·  http://localhost:6006    │  │
│  │  · transcripts           │   │  OTel spans: prompts · responses ·     │  │
│  │  · memories (embeddings) │   │  latency · cache tokens ·              │  │
│  │  · character_traits      │   │  avatar/context attributes             │  │
│  │  · relationship_states   │   └────────────────────────────────────────┘  │
│  └──────────────────────────┘                                                │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 20+
- API keys: **Deepgram**, **ElevenLabs**, **OpenAI**, **Anthropic**
- NVIDIA GPU with CUDA _optional_ (only needed if using XTTS-v2 local fallback)

### 1. Backend

```bash
cd backend
python -m venv .venv

# Windows:
.venv\Scripts\pip install -r requirements.txt
# Linux/Mac:
source .venv/bin/activate && pip install -r requirements.txt

cp ../.env.example ../.env
# Edit .env — add API keys (see Configuration section below)

python -m alembic upgrade head   # create/migrate DB tables

python -m uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev   # opens http://localhost:5173
```

### 3. Configure Avatars

1. Open `http://localhost:5173/avatars`
2. Create an avatar and fill in the character sheet
3. In the **ElevenLabs Voice** section, enter a Voice ID from [elevenlabs.io/voice-lab](https://elevenlabs.io/voice-lab)
4. Choose model preference: Quality (v3) for roleplay, Fast (Flash) for combat
5. Adjust stability/style/similarity sliders to taste

### Startup Order

1. Phoenix (optional): `phoenix serve` → `http://localhost:6006`
2. Backend: `cd backend && .venv/Scripts/uvicorn app.main:app --reload --port 8000`
3. Frontend: `cd frontend && npm run dev`

---

## Navigation Guide

### Avatars Page — `http://localhost:5173/avatars`

Create and manage your avatar roster. Each avatar has a full D&D 5e character card. At creation time, Vestige calls GPT-4o to generate a personality prompt, archetype, verbosity, and voice assignment automatically.

**Key controls:**

- **Create Avatar** — opens the avatar form. Fill in the character sheet; personality is generated on save.
- **ElevenLabs Voice** — set Voice ID and expressiveness params (stability, style, similarity). Leave blank to fall back to Edge-TTS.
- **Model preference** — Quality (eleven_v3, emotion tags) vs Fast (eleven_flash_v2_5).
- **Backfill Personality** — for older avatars: `POST /api/avatars/generate-personality`.

### Sessions Page — `http://localhost:5173/sessions`

Manage campaign sessions. After closing a session, use **Memory Review** to generate a post-session summary with Claude, review trait and relationship deltas, then approve to persist them.

### Table Page — `http://localhost:5173/table`

The live game view:

- **Live transcript** — every utterance transcribed in real-time via Deepgram
- **Avatar panels** — current state, last response, and combat status
- **DM controls** — override hotwords to force an avatar to speak, go silent, or reset state
- **Combat tracker** — action economy and spell slots tracked automatically

### Settings Page — `http://localhost:5173/settings`

Configure API keys, audio devices, and behavior parameters. Changes are persisted and take effect immediately.

### Memory Review Page — `http://localhost:5173/memory`

Browse stored memories per avatar. After a session, generate a summary here — Claude extracts events, trait deltas, and relationship shifts. Review and approve to commit them to the avatar's long-term memory.

---

## Configuration

Key `.env` settings:

| Variable | Description |
| --- | --- |
| `DEEPGRAM_API_KEY` | Required for streaming STT |
| `OPENAI_API_KEY` | Required for GPT-4o (fast-path LLM) |
| `ANTHROPIC_API_KEY` | Required for Claude Sonnet 4.6 (deep-path LLM + summariser) |
| `ELEVENLABS_API_KEY` | Required for ElevenLabs TTS |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/campaign.db` |
| `HOST` | `0.0.0.0` |
| `PORT` | `8000` |
| `CORS_ORIGINS` | `http://localhost:5173,...` |

### Tuning Parameters (Settings page / config.py)

| Setting | Default | Description |
| --- | --- | --- |
| `deepgram_endpointing_ms` | `800` | ms of silence = utterance end |
| `max_avatar_chain_depth` | `3` | Max avatar-to-avatar reaction chain |
| `avatar_speech_cooldown_s` | `8.0` | Min seconds between avatar-speech reactions |
| `trait_decay_weekly_pct` | `0.10` | Trait strength decay per week (10%) |
| `actor_instructions_offset` | `3` | Lines from transcript end to inject actor reminder |
| `summary_method` | `balanced` | Post-session summary verbosity: facts/short/balanced/long |

### Hot-Reloadable Prompt Files

All routing logic and prompt text lives in `backend/prompts/*.yaml`:

| File | Controls |
| --- | --- |
| `routing_keywords.yaml` | What triggers Claude vs GPT-4o |
| `context_keywords.yaml` | Combat triggers, DM hotwords, directed fragments |
| `length_instructions.yaml` | Per context-type response length guidance |
| `holding_phrases.yaml` | "Thinking out loud" phrases per context type |
| `system_prompt_sections.yaml` | Static rule strings injected into system prompt |

After editing, reload without restarting:

```
POST http://localhost:8000/api/prompts/reload
```

---

## Monitoring with Arize Phoenix

Phoenix runs as a separate process alongside Vestige. Install it once:

```
pip install arize-phoenix
phoenix serve
```

The backend sends OTel spans to Phoenix automatically when it's running. Open `http://localhost:6006` to access the UI. Each span includes:

- Full system prompt (identity, traits, memory, rules state)
- User message and avatar response
- Latency end-to-end
- Token counts including `cache_read_tokens` and `cache_write_tokens` for Claude calls
- Avatar ID, context type, LLM route as span attributes

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
│   │   ├── models/              # SQLAlchemy models (avatar, session, transcript,
│   │   │                        #   memory, character_trait, relationship_state)
│   │   ├── schemas/             # Pydantic schemas
│   │   ├── routers/             # API routers + WebSocket
│   │   ├── audio/               # Pipeline, Deepgram STT, ElevenLabs TTS,
│   │   │                        #   audio tag injector, AEC, output manager
│   │   ├── llm/                 # Prompt builder, GPT-4o/Claude router, dispatcher
│   │   ├── memory/              # Embedder, store, summariser (trait/rel deltas)
│   │   ├── prompts/             # Prompt loader module
│   │   ├── presence/            # Backchannel player, ambient reactions, layer
│   │   └── services/            # Pipeline manager, combat manager, trait service
│   ├── prompts/                 # Editable YAML prompt/keyword files
│   ├── alembic/                 # DB migrations
│   ├── tests/                   # pytest test suite (305 tests)
│   ├── requirements.txt
│   └── pytest.ini
├── frontend/
│   ├── src/
│   │   ├── api/client.js        # Fetch wrapper for all endpoints
│   │   ├── stores/              # Zustand state stores
│   │   ├── components/          # Reusable UI components (AvatarForm with ElevenLabs config)
│   │   └── pages/               # Avatars, Sessions, Table, Settings, MemoryReview
│   └── package.json
├── voice_samples/               # Avatar voice .wav reference files (XTTS-v2 fallback)
├── data/                        # SQLite DB (gitignored)
├── docs/                        # Per-phase implementation notes
├── scripts/                     # Setup / utility scripts
├── plan.md                      # Master build plan
├── .env.example
└── README.md
```

---

## Running Tests

```bash
cd backend
.venv/Scripts/python -m pytest tests/ -v
```

305 tests across all phases. All should pass on a clean install (no API keys needed — all external calls are stubbed in tests).

---

## Documentation

- [Phase 1 — Foundation](docs/phase1-foundation.md)
- [Phase 2 — Voice Input Pipeline](docs/phase2-voice-input.md)
- [Phase 3 — Voice Output Pipeline](docs/phase3-voice-output.md)
- [Phase 4 — AI Brain](docs/phase4-ai-brain.md)
- [Phase 5 — Memory System](docs/phase5-memory.md)
- [Phase 6 — Rules Engine & Combat](docs/phase6-rules.md)
- [Phase 7 — Polish & Inter-Avatar Dynamics](docs/phase7-polish.md)
- [Phase 8 — Avatar Personality & Voice Behaviors](docs/phase8-avatar-personality-behaviors.md)
- [Phase 9 — Audio Revamp](docs/phase9-audio-revamp.md)

---

## Build Status

| Phase | Description | Status |
| --- | --- | --- |
| **1** | Foundation — API, DB schema, avatar/session CRUD, D&D UI | ✅ Complete |
| **2** | Voice Input — mic capture, VAD, STT, AEC | ✅ Complete |
| **3** | Voice Output — TTS, voice cloning, backchannel pre-gen | ✅ Complete |
| **4** | AI Brain — LLM router, context engine, prompt builder | ✅ Complete |
| **5** | Memory — session transcripts, embeddings, sqlite-vec retrieval | ✅ Complete |
| **6** | Rules Engine — D&D 5e action economy, spells, conditions, combat | ✅ Complete |
| **7** | Polish — inter-avatar dynamics, DM controls, settings panel | ✅ Complete |
| **8** | Avatar Realism — personality prompts, differentiated voices, Phoenix tracing | ✅ Complete |
| **9** | Audio Revamp — Deepgram STT, ElevenLabs TTS, GPT-4o, avatar banter, trait evolution | ✅ Complete |
