# ⚔ Vestige — DnD AI Avatar System

> Locally-hosted AI avatars that stand in for absent D&D players.  
> Avatars listen passively, chime in naturally with in-character voice responses,  
> maintain persistent memory, and play by 5e rules.  
> All audio runs locally on a 24 GB NVIDIA GPU. LLM brain: Ollama + Claude API.

---

## Project Status

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

---

## Architecture Overview

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

**Phase 2+ additions:**

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
                           XTTS-v2 (CUDA) → Speaker
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
*   NVIDIA GPU with CUDA (for Phase 2+)
*   [Ollama](https://ollama.com/download) installed and running locally (for Phase 4+)
*   Anthropic API key (for Phase 4+)
*   [ffmpeg](https://ffmpeg.org/download.html) on your system PATH (for Phase 8+ Edge-TTS voice playback — MP3 decode)

### 1\. Install and Start Ollama

Vestige uses Ollama for fast, local LLM inference (combat turns, casual roleplay, direct questions). It must be running before you start the backend.

**Install:** Download from [ollama.com/download](https://ollama.com/download) and run the installer.

**Start the Ollama server** (it may already run as a background service after install):

```
ollama serve
```

**Pull the required model:**

```
ollama pull llama3.1:8b
```

**Verify it's working:**

```
curl http://localhost:11434/api/tags
# Should return JSON listing available models
```

> Ollama must stay running in the background while using Vestige. Without it, avatar responses for fast-path context types (combat, roleplay) will be silently skipped.

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
2.  Backend: `cd backend && .venv/Scripts/uvicorn app.main:app --reload --port 8000`
3.  Frontend: `cd frontend && npm run dev`

**LLM Tracing UI (Phase 8+):** Once the backend starts, Arize Phoenix is automatically launched at [http://localhost:6006](http://localhost:6006). Open it to inspect every LLM prompt/response, latency, token counts, and run evaluations. No extra setup needed — it starts in-process with the backend. See the [Phoenix docs](https://docs.arize.com/phoenix) for eval/annotation workflows.

### Tests

```
cd backend
.venv/Scripts/python -m pytest tests/ -v
```

---

## Project Structure

```
vestige/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # Settings (pydantic-settings)
│   │   ├── db/database.py       # Async engine, session, Base
│   │   ├── models/              # SQLAlchemy models
│   │   ├── schemas/             # Pydantic schemas
│   │   ├── routers/             # API routers + WebSocket
│   │   ├── audio/               # Pipeline, VAD, STT, TTS, AEC, post-processor
│   │   ├── presence/            # Backchannel player, ambient reactions, layer
│   │   └── services/            # Business logic (pipeline manager, etc.)
│   ├── tests/                   # pytest test suite
│   ├── requirements.txt
│   └── pytest.ini
├── frontend/
│   ├── src/
│   │   ├── api/client.js        # Fetch wrapper for all endpoints
│   │   ├── stores/              # Zustand state stores
│   │   ├── components/          # Reusable UI components
│   │   └── pages/              # Avatars, Sessions, Table
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

## Documentation

*   [Phase 1 — Foundation](docs/phase1-foundation.md)
*   [Phase 2 — Voice Input Pipeline](docs/phase2-voice-input.md)
*   [Phase 3 — Voice Output Pipeline](docs/phase3-voice-output.md)
*   [Phase 4 — AI Brain](docs/phase4-ai-brain.md)
*   [Phase 5 — Memory System](docs/phase5-memory.md)
*   [Phase 6 — Rules Engine & Combat](docs/phase6-rules.md)
*   [Phase 7 — Polish & Inter-Avatar Dynamics](docs/phase7-polish.md)
*   [Phase 8 — Avatar Personality & Voice Behaviors](docs/avatar-personality-behaviors.md)

---

## Design Philosophy

Traditional voice AI pipelines feel robotic because they are fully turn-based.  
This system uses a **two-layer architecture**:

**Presence Layer** — real-time, no LLM. Pre-generated backchannels ("mm", "yeah")  
played probabilistically while humans speak. Holding phrases during generation delay.

**Reasoning Layer** — cascade pipeline (STT → LLM → TTS) with jitter-delayed  
responses and context-aware routing (Ollama for fast combat, Claude for deep roleplay).

Combined, this produces avatars that feel like they're _at the table_, not _waiting to respond_.

---

## Configuration

Key `.env` settings:

| Variable | Default | Description |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | — | Required for Claude routing (Phase 4+) |
| `MIC_DEVICE_INDEX` | `0` | Audio device index (run `scripts/list_audio_devices.py`) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/campaign.db` | SQLite path |
| `HOST` | `0.0.0.0` | Backend bind address |
| `PORT` | `8000` | Backend port |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed frontend origins |