# Architecture

System design, data flow, and project structure for Vestige. For feature-level documentation, see [Features](features.md). For configuration options, see [Configuration](configuration.md).

---

## Overview

Vestige is a locally-hosted web app. The frontend is a React SPA served by Vite. The backend is a FastAPI application that manages the audio pipeline, LLM dispatch, memory storage, and a WebSocket connection to the browser. Everything persists to a local SQLite database.

```
Browser (React)  ←──────── HTTP REST + WebSocket ──────────→  FastAPI Backend
                                                                     │
                                                         SQLite (avatars, sessions,
                                                         transcripts, memories,
                                                         traits, relationships)
```

External API calls go only to Deepgram (STT), ElevenLabs (TTS), OpenAI (GPT-4o), and Anthropic (Claude). No other data leaves the machine.

---

## Full System Diagram

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
│  │     │  Memory Retriever (sqlite-vec)              │                 │   │
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
│  │     └──────────────────────┼───────────────────────┘                │   │
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
│  │          │         ── fallbacks ──          │                       │   │
│  │          │  Edge-TTS  /  XTTS-v2 (CUDA)    │                       │   │
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

## Data Flow

### Session startup

1. GM creates a session on the Sessions page, assigns avatars
2. Frontend opens a WebSocket connection to `/ws`
3. GM navigates to Table, selects the session, clicks **Start Listening**
4. Backend spawns a `PipelineManager` for the session
5. `PipelineManager` initialises a per-session Deepgram STT client and begins forwarding PCM frames from the browser mic

### Per utterance — human speaker

```
Browser mic
  → PCM frames over WebSocket
  → AEC Gate (filters frames containing avatar playback)
  → Deepgram streaming STT
  → speech_final fires (~200ms after sentence end)
  → Transcript stored in SQLite
  → Backchannel Classifier
      ├─ Is this a short acknowledgement? → play backchannel sound, done
      └─ No → Context Engine
               ├─ Per-avatar evaluation:
               │    · cooldown checks (self, any-avatar)
               │    · archetype gate (stoic, introvert)
               │    · verbosity threshold
               │    · trait trigger keyword scan
               └─ For each avatar that passes → DispatchRequest
                    → LLM Dispatcher
                         · Memory retriever (sqlite-vec similarity search)
                         · Prompt builder (identity + traits + memory + rules + transcript)
                         · Route: GPT-4o or Claude (by context type)
                         · Response post-processor (emotion tag, trait override)
                    → TTS Engine (ElevenLabs streaming PCM)
                    → Browser AudioContext (plays as chunks arrive)
```

### Per utterance — avatar speaker

The avatar's synthesised speech is broadcast via WebSocket as an `avatar_speaking` event. Other avatars' context engines evaluate whether to react — subject to chain depth limits (`max_avatar_chain_depth`), archetype gates, and the avatar-speech cooldown. The evaluation and dispatch path is identical to human speech from that point.

### Post-session

1. GM clicks **End Session** on the Sessions page
2. GM navigates to Memory Review for the session
3. Clicks **Generate Summary** — Claude reads the full transcript and the last 6 session summaries
4. Summary, trait deltas, and relationship deltas are displayed for review
5. GM edits if needed, approves — changes are written to SQLite

---

## Project Structure

```
vestige/
├── backend/
│   ├── app/
│   │   ├── main.py                   # FastAPI app, lifespan, router registration
│   │   ├── config.py                 # All settings via pydantic-settings (reads .env)
│   │   ├── tracing.py                # Arize Phoenix + OpenTelemetry initialisation
│   │   ├── db/
│   │   │   └── database.py           # Async engine, session factory, Base
│   │   ├── models/                   # SQLAlchemy ORM models
│   │   │   ├── avatar.py
│   │   │   ├── session.py
│   │   │   ├── transcript.py
│   │   │   ├── memory.py
│   │   │   ├── character_trait.py
│   │   │   └── relationship_state.py
│   │   ├── schemas/                  # Pydantic request/response schemas
│   │   │   ├── avatar.py
│   │   │   ├── session.py
│   │   │   └── transcript.py
│   │   ├── routers/                  # FastAPI route handlers
│   │   │   ├── avatars.py            # Avatar CRUD + personality generation
│   │   │   ├── sessions.py           # Session management
│   │   │   ├── transcripts.py        # Transcript read/write
│   │   │   ├── memory.py             # Memory chunks + summary approval
│   │   │   ├── traits.py             # Trait + relationship CRUD
│   │   │   ├── settings.py           # GET / PATCH /api/settings
│   │   │   ├── prompts.py            # POST /api/prompts/reload
│   │   │   └── ws.py                 # WebSocket handler + mic audio forwarding
│   │   ├── audio/                    # The core audio pipeline
│   │   │   ├── pipeline.py           # Orchestrates STT → context → dispatch → TTS
│   │   │   ├── aec_gate.py           # Acoustic echo cancellation gate
│   │   │   ├── deepgram_stt.py       # Deepgram streaming client (per-session)
│   │   │   ├── elevenlabs_tts.py     # ElevenLabs streaming TTS
│   │   │   ├── audio_tag_injector.py # Haiku-based emotion tag injection
│   │   │   ├── context_engine.py     # Per-utterance per-avatar evaluation
│   │   │   └── output_manager.py     # PCM playback + avatar_speaking broadcast
│   │   ├── llm/
│   │   │   ├── prompt_builder.py     # System prompt assembly (author framing, actor offset)
│   │   │   ├── router.py             # Context-type → GPT-4o / Claude routing
│   │   │   └── dispatcher.py        # LLM call execution + OTel span
│   │   ├── memory/
│   │   │   ├── embedder.py           # Text → embedding (for sqlite-vec)
│   │   │   ├── store.py              # Embedding storage + similarity retrieval
│   │   │   └── summariser.py         # Post-session summary + delta extraction
│   │   ├── prompts/                  # YAML loader module (reads backend/prompts/)
│   │   ├── presence/
│   │   │   ├── backchannel.py        # Backchannel classifier + sound player
│   │   │   └── layer.py              # Presence layer orchestration
│   │   └── services/
│   │       ├── pipeline_manager.py   # Per-session pipeline lifecycle
│   │       ├── combat_manager.py     # D&D 5e action economy + initiative
│   │       └── trait_service.py      # Trait decay + manifestation checks
│   ├── prompts/                      # Hot-reloadable YAML prompt configuration
│   │   ├── routing_keywords.yaml     # Claude vs GPT-4o context-type routing
│   │   ├── context_keywords.yaml     # Combat triggers, DM hotwords, directed fragments
│   │   ├── length_instructions.yaml  # Per context-type response length guidance
│   │   ├── holding_phrases.yaml      # Filler phrases per context type
│   │   └── system_prompt_sections.yaml  # Static rule strings for system prompt
│   ├── alembic/                      # Database migrations
│   ├── tests/                        # pytest suite (305 tests, no API keys needed)
│   ├── requirements.txt
│   └── pytest.ini
├── frontend/
│   ├── src/
│   │   ├── api/client.js             # Typed fetch wrapper for all backend endpoints
│   │   ├── stores/                   # Zustand state (avatars, sessions, settings)
│   │   ├── components/               # Shared UI components
│   │   └── pages/
│   │       ├── AvatarsPage.jsx       # Route: /
│   │       ├── SessionsPage.jsx      # Route: /sessions
│   │       ├── TablePage.jsx         # Route: /table
│   │       ├── SettingsPage.jsx      # Route: /settings
│   │       └── MemoryReviewPage.jsx  # Route: /sessions/:id/memory
│   └── package.json
├── docs/                             # This directory — user-facing docs + phase notes
├── scripts/
│   ├── seed_sample_data.py           # Populates DB with sample avatars + session
│   ├── take_screenshots.mjs          # Playwright headless screenshot capture
│   └── list_audio_devices.py         # Prints available mic device indices
├── voice_samples/                    # .wav reference files for XTTS-v2 fallback
├── data/                             # SQLite DB — gitignored
├── .env.example                      # Environment variable template
└── README.md
```

---

## Key Design Decisions

**SQLite over Postgres.** The target deployment is a single machine running a local session. SQLite with aiosqlite gives full async support without a separate database process, and sqlite-vec adds vector similarity search without a separate vector store.

**Per-session Deepgram clients.** Early versions used a singleton STT client shared across sessions. Per-session clients isolate session state, simplify lifecycle management (start/stop cleanly with the pipeline), and allow concurrent sessions without interference.

**Author framing in prompts.** The system prompt asks the LLM to *author dialogue for a character* rather than *be the character*. This produces more controlled, scene-appropriate responses and reduces the risk of the model breaking character by slipping into meta-commentary.

**YAML-driven prompt configuration.** All routing keywords, response length guidance, holding phrases, and static system prompt rules live in hot-reloadable YAML files. Prompt tuning — the most common operational change — requires no code changes and no server restart.

**Prompt caching on Claude.** The Claude dispatch path splits the system prompt at the boundary between static content (identity, rules, archetypes) and dynamic content (current transcript, active memories, combat state). Static content is marked as cacheable. This reduces Claude costs significantly on sessions with many dispatches — cache hits cost ~10× less than uncached tokens.

**Actor offset.** A "stay in character" reminder is injected at a fixed offset from the end of the transcript (`actor_instructions_offset`, default 3 lines), not at the bottom. This positions the reminder where the LLM attends to it most reliably while keeping the response-triggering utterance as the final token context.

---

## Build History

The `docs/` directory contains implementation notes from each phase. Useful context for understanding *why* something was built a particular way:

| Phase | Doc |
| ----- | --- |
| 1 — Foundation | [phase1-foundation.md](phase1-foundation.md) |
| 2 — Voice input | [phase2-voice-input.md](phase2-voice-input.md) |
| 3 — Voice output | [phase3-voice-output.md](phase3-voice-output.md) |
| 4 — AI brain | [phase4-ai-brain.md](phase4-ai-brain.md) |
| 5 — Memory | [phase5-memory.md](phase5-memory.md) |
| 6 — Rules engine | [phase6-rules.md](phase6-rules.md) |
| 7 — Polish | [phase7-polish.md](phase7-polish.md) |
| 8 — Avatar personality and behaviours | [phase8-avatar-personality-behaviors.md](phase8-avatar-personality-behaviors.md) |
| 9 — Audio revamp | [phase9-audio-revamp.md](phase9-audio-revamp.md) |
