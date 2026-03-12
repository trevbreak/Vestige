# Phase 5 — Memory System

## What Was Built

### New Modules (`backend/app/memory/`)

| Module | Purpose |
|---|---|
| `embedder.py` | Wraps sentence-transformers; produces 384-dim float32 embeddings; graceful zero-stub when unavailable |
| `store.py` | Async MemoryChunk persistence + cosine similarity search (Python fallback; sqlite-vec ready) |
| `summariser.py` | Post-session + rolling mid-session Claude summarisation → structured JSON |
| `retriever.py` | Embeds query text; returns top-K relevant memory chunk texts for prompt injection |

### New DB Models (`backend/app/models/memory.py`)

| Model | Purpose |
|---|---|
| `SessionSummary` | One-per-session structured summary (JSON + prose). DM reviews before approval. |
| `MemoryChunk` | Single retrievable memory unit for an avatar. Stores text + float32 embedding bytes. |

---

## Memory Flow

### Post-Session

```
Session ends
    │
    ├─ DM calls POST /api/memory/sessions/{id}/summarise
    │       └─ Claude reads full transcript → structured JSON + prose
    │          Stored in SessionSummary (is_approved=False)
    │
    ├─ DM reviews in MemoryReview UI (edit events, NPCs, items, etc.)
    │
    └─ DM calls POST /api/memory/sessions/{id}/approve
            └─ All summary chunks embedded (sentence-transformers)
               Stored as MemoryChunks per avatar
               SessionSummary.is_approved = True
```

### Mid-Session (Rolling)

```
~60 minutes of play
    │
    └─ POST /api/memory/sessions/{id}/rolling-summary
            └─ Claude condenses last N lines → prose
               Appended to SessionSummary.rolling_summaries
```

### Real-Time Retrieval (per response)

```
AudioPipeline._flush_buffer → should_respond = True
    │
    └─ _dispatch_response()
            ├─ MemoryRetriever.retrieve_from_transcript(db, avatar_id, transcript_lines)
            │       ├─ Embed last 10 transcript lines
            │       ├─ Cosine search MemoryChunks for avatar
            │       └─ Return top-K texts (filtered by score ≥ 0.3)
            │
            └─ DispatchRequest.memory_chunks = [...retrieved texts...]
                    └─ PromptBuilder injects into == RELEVANT MEMORY == section
```

---

## Structured Summary Schema

```json
{
  "events": ["Description of major plot events"],
  "npcs": [{"name": "NPC name", "notes": "relationship/event"}],
  "items": [{"name": "Item", "owner": "Character", "notes": "context"}],
  "relationship_deltas": [{"avatar": "Name", "target": "Other", "note": "how changed"}],
  "avatar_updates": [{
    "avatar_name": "Name",
    "hp_delta": -5,
    "spell_slots_used": {"3": 1},
    "items_gained": ["Potion"],
    "items_lost": [],
    "xp_gained": 200,
    "notes": "Narrative note"
  }],
  "summary_text": "2–4 sentence prose campaign log entry."
}
```

---

## MemoryChunk Importance Weights

| Type | Importance |
|---|---|
| `relationship` | 0.8 |
| `event` from avatar notes | 0.9 |
| `session_summary` | 0.8 |
| `event` (general) | 0.7 |
| `npc` | 0.6 |
| `item` | 0.5 |

Retrieval score = cosine_similarity × 0.8 + importance × 0.2

---

## New API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/memory/sessions/{id}/summarise` | Generate post-session summary via Claude |
| `GET` | `/api/memory/sessions/{id}/summary` | Retrieve stored SessionSummary |
| `POST` | `/api/memory/sessions/{id}/approve` | DM approves; embeds chunks into memory |
| `GET` | `/api/memory/avatars/{id}/chunks` | List MemoryChunks for avatar |
| `DELETE` | `/api/memory/chunks/{id}` | Soft-delete a MemoryChunk |
| `POST` | `/api/memory/sessions/{id}/rolling-summary` | Mid-session Claude summary |
| `POST` | `/api/sessions/{id}/speakers` | Remap "Unknown"/"Speaker 0" to player names |
| `POST` | `/api/avatars/{id}/sheet-update` | Apply session state changes to avatar sheet |

---

## Character Sheet Auto-Update

`POST /api/avatars/{id}/sheet-update` accepts:

```json
{
  "hp_delta": -10,
  "hp_set": 25,
  "spell_slots_used": {"3": 1},
  "spell_slots_restore": true,
  "items_gained": ["Holy Symbol"],
  "items_lost": ["Torch"],
  "level_up": true,
  "xp_gained": 300,
  "relationship_updates": {"Garrick": "Saved his life"},
  "conditions_add": ["Poisoned"],
  "conditions_remove": ["Frightened"]
}
```

---

## Frontend — MemoryReview Page

Route: `/sessions/:sessionId/memory`
Accessible via "Memory Review" button on each session in SessionsPage.

Sections:
1. **Session Summary** — Generate / approve workflow with structured breakdown
2. **Speaker Attribution** — Remap "Unknown"/"Speaker 0" to player names post-session
3. **Memory Chunks** — Per-avatar chunk list with soft-delete

---

## Graceful Degradation

| Dependency | Unavailable → |
|---|---|
| `sentence-transformers` | Embedder returns zero-vectors; retriever returns [] (no false matches) |
| Claude API key | Summariser returns stub text; system continues without summaries |
| `sqlite-vec` | Pure-Python cosine scan over all chunks (slower but correct) |

---

## Tests

48 new tests added (177 total), covering:
- `Embedder` — pack/unpack roundtrip, cosine similarity, stub mode, batch
- `MemoryStore` — upsert, list, search ordering, soft-delete
- `SessionSummariser` — stub mode, JSON parse, rolling summary, chunk extraction
- `MemoryRetriever` — empty query, stub embedder guard, transcript join
- Memory API — summarise, get, approve, 409 on re-approve, rolling summary, 404s
- Speaker attribution — remap, DM type, 404
- Sheet update — HP delta/set, item gain/loss, level up, relationships, 404
