# ⚔ Vestige — DnD AI Avatar System

> Locally-hosted AI avatars that stand in for absent D&D players.
> Avatars listen passively, chime in naturally with in-character voice responses,
> maintain persistent memory, and play by 5e rules.
> All audio runs locally on a 24 GB NVIDIA GPU. LLM brain: Ollama + Claude API.

---

## Project Status

| Phase | Description | Status |
|---|---|---|
| **1** | Foundation — API, DB schema, avatar/session CRUD, D&D UI | ✅ Complete |
| **2** | Voice Input — mic capture, VAD (silero), STT (faster-whisper), AEC | ✅ Complete |
| **3** | Voice Output — XTTS-v2 TTS, voice cloning, backchannel pre-gen | ✅ Complete |
| **4** | AI Brain — Ollama/Claude router, context engine, prompt builder | ✅ Complete |
| **5** | Memory — session transcripts, embeddings, sqlite-vec retrieval | ✅ Complete |
| **6** | Rules Engine — D&D 5e action economy, spells, conditions, combat | 🔲 Pending |
| **7** | Polish — inter-avatar dynamics, DM controls, settings panel | 🔲 Pending |

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
|---|---|
| faster-whisper large-v3 | ~3 GB |
| Coqui XTTS-v2 | ~3–4 GB |
| Ollama llama3.1:8b Q4 | ~5–6 GB |
| **Total** | **~12 GB** (12 GB headroom) |

---

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 20+
- NVIDIA GPU with CUDA (for Phase 2+)
- [Ollama](https://ollama.ai) running locally (for Phase 4+)
- Anthropic API key (for Phase 4+)

### Backend

```bash
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

### Frontend

```bash
cd frontend
npm install
npm run dev   # opens http://localhost:5173
```

### Tests

```bash
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

- [Phase 1 — Foundation](docs/phase1-foundation.md)
- [Phase 2 — Voice Input Pipeline](docs/phase2-voice-input.md)
- [Phase 3 — Voice Output Pipeline](docs/phase3-voice-output.md)
- [Phase 4 — AI Brain](docs/phase4-ai-brain.md)
- [Phase 5 — Memory System](docs/phase5-memory.md)

---

## Design Philosophy

Traditional voice AI pipelines feel robotic because they are fully turn-based.
This system uses a **two-layer architecture**:

1. **Presence Layer** — real-time, no LLM. Pre-generated backchannels ("mm", "yeah")
   played probabilistically while humans speak. Holding phrases during generation delay.

2. **Reasoning Layer** — cascade pipeline (STT → LLM → TTS) with jitter-delayed
   responses and context-aware routing (Ollama for fast combat, Claude for deep roleplay).

Combined, this produces avatars that feel like they're *at the table*, not *waiting to respond*.

---

## Configuration

Key `.env` settings:

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required for Claude routing (Phase 4+) |
| `MIC_DEVICE_INDEX` | `0` | Audio device index (run `scripts/list_audio_devices.py`) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/campaign.db` | SQLite path |
| `HOST` | `0.0.0.0` | Backend bind address |
| `PORT` | `8000` | Backend port |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed frontend origins |
