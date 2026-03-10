# Phase 1 — Foundation

## What Was Built

### Backend (FastAPI + SQLite)

**Entry point:** `backend/app/main.py`

FastAPI application with async lifespan that initialises the SQLite database on startup.

**Database models** (`backend/app/models/`):

| Model | Table | Purpose |
|---|---|---|
| `Avatar` | `avatars` | Full D&D 5e character sheet + voice/AI config |
| `Session` | `sessions` | Game session with participating avatar list |
| `Transcript` | `transcripts` | Per-utterance log with speaker type and LLM metadata |

**API endpoints** (`/api/...`):

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/avatars/` | List all active avatars |
| `POST` | `/api/avatars/` | Create avatar |
| `GET` | `/api/avatars/{id}` | Get avatar |
| `PATCH` | `/api/avatars/{id}` | Update avatar (partial) |
| `DELETE` | `/api/avatars/{id}` | Archive avatar (soft delete) |
| `POST` | `/api/avatars/{id}/portrait` | Upload portrait image |
| `PATCH` | `/api/avatars/{id}/mode` | Set avatar mode (active/passive/absent) |
| `GET` | `/api/sessions/` | List sessions |
| `POST` | `/api/sessions/` | Create session |
| `GET` | `/api/sessions/{id}` | Get session |
| `PATCH` | `/api/sessions/{id}` | Update session |
| `POST` | `/api/sessions/{id}/end` | End session |
| `GET` | `/api/transcripts/session/{id}` | Get session transcripts |
| `POST` | `/api/transcripts/` | Append transcript entry |
| `WS` | `/ws` | Real-time WebSocket (ping/pong in Phase 1) |

**Static files:** portrait images served at `/uploads/`

### Frontend (React + Vite)

Three pages accessed via top nav:

- **Avatars** (`/`) — Avatar roster with cards showing full stat block, mode controls, edit/archive actions. Create/edit via modal form with full character sheet input.
- **Sessions** (`/sessions`) — Create sessions (name, campaign, avatar selection), list all sessions with active/ended state, end active sessions.
- **Table** (`/table`) — Live game view: session picker, avatar panels (portrait, HP, AC, mode badge), live transcript panel with WebSocket updates.

**D&D visual theme:** dark parchment background (`#0f0d0a`), Cinzel headings, IM Fell English body, amber/gold accents (`#c8973a`), deep crimson highlights (`#8b1a1a`), candleflame pulse animation for speaking avatars.

**State management:** Zustand stores (`avatarStore`, `sessionStore`).

**API client:** `src/api/client.js` — thin fetch wrapper over all backend endpoints.

## Running Locally

### Backend
```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/Mac
cp ../.env.example ../.env   # fill in your ANTHROPIC_API_KEY
python -m uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

The frontend dev server proxies `/api`, `/ws`, and `/uploads` to `localhost:8000`.

## Running Tests

```bash
cd backend
.venv/Scripts/python -m pytest tests/ -v
```

15 tests covering:
- Health endpoint
- Avatar CRUD (create, list, get, update, soft-delete, mode change)
- Session CRUD (create, list, end, update)
- Transcript creation and paginated retrieval

## Key Design Decisions

- **Soft deletes** for avatars (`is_active = False`) — campaign history preserved
- **Async SQLAlchemy** with `aiosqlite` — non-blocking DB access, compatible with FastAPI's async handlers
- **Pydantic v2** schemas with `exclude_unset=True` on PATCH — true partial updates
- **WebSocket manager** in `routers/websocket.py` — broadcast-capable from Phase 2 onward
- **CSS Modules** for component scoping; global design tokens in `index.css`
