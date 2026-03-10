# Phase 3 — Voice Output Pipeline

## What Was Built

### Audio Output Modules (`backend/app/audio/`)

| Module | Purpose |
|---|---|
| `tts.py` | XTTS-v2 wrapper — synthesizes WAV from text+emotion; silent-stub fallback |
| `response_post_processor.py` | Cleans LLM output before TTS (emotion, markdown, stage dirs, length) |
| `output_manager.py` | Serialises audio playback; priority queue with preemption; WAV → WS streaming |

### Presence Layer (`backend/app/presence/`)

| Module | Purpose |
|---|---|
| `backchannel_player.py` | Per-avatar WAV library for short reactive clips ("mm", "yeah") |
| `ambient_reactions.py` | Holding phrase text library, grouped by context type |
| `layer.py` | Orchestrator — plays backchannels and holding phrases at the right time |

### Response Post-Processing Pipeline

```
raw LLM text
      │
      ├─ 1. Extract emotion tag   [quietly] / [urgently] / [tense] / etc.
      ├─ 2. Strip markdown        **bold**, _italic_, ## headings, • bullets
      ├─ 3. Strip stage directions (laughs), *sighs*, [narrator voice]
      ├─ 4. Enforce first-person  "Aldric draws" → "I draw"
      ├─ 5. Normalise whitespace
      ├─ 6. Enforce length limit  (context_type → max sentences)
      └─ 7. Response jitter       random 1.5–4.0 s delay before playback
```

Context-type sentence limits:

| Context | Max Sentences |
|---|---|
| `combat_turn` | 2 |
| `casual_roleplay` | 2 |
| `direct_question` | 3 |
| `npc_social` | 4 |
| `moral_dilemma` | 4 |
| `emotional_beat` | 5 |
| `backstory_call` | 5 |

### Audio Output Manager

```
enqueue(avatar_id, wav_bytes, priority)
      │
      ▼
asyncio.PriorityQueue  ← lower number = higher priority
      │
      ▼
_play_job():
      ├─ gate.on_tts_start()          ← close AEC gate (block mic)
      ├─ broadcast avatar_speaking=True
      ├─ broadcast audio_start
      ├─ loop: broadcast audio_chunk  ← base64-encoded STREAM_CHUNK_BYTES=4096
      ├─ broadcast audio_end
      ├─ broadcast avatar_speaking=False
      └─ gate.on_tts_end()            ← open AEC gate after 200ms decay
```

Priority preemption: if a higher-priority job arrives while a lower-priority one is playing,
`_cancel_current` event is set and the current job streams `cancelled=true`.

### Presence Layer Behaviour

**Backchannels** — During human speech:
- `BackchannelLibrary.should_play()` checks elapsed ≥ `BACKCHANNEL_MIN_GAP` (8s) and random roll < `BACKCHANNEL_CHANCE` (35%)
- Picks a clip from the matching category (neutral / surprised / agreeing / uncertain / engaged)
- Broadcasts a `backchannel` TranscriptEntry + queues audio at 60% volume (priority 10)

**Holding Phrases** — When context engine fires:
- `get_holding_phrase(context_type)` picks a phrase from `AMBIENT_REACTIONS`
- `strip_holding_emotion` extracts `[tense]`/`[quietly]` tag if present
- TTS synthesizes the clean text with the emotion speed
- Queues at priority 3 (preempts backchannels but not core speech)

### New WebSocket Message Types (Server → Client)

```json
{ "type": "avatar_speaking", "session_id": 1, "avatar_id": 2, "avatar_name": "Aldric",
  "utterance_type": "speech", "speaking": true }

{ "type": "audio_start", "session_id": 1, "avatar_id": 2, "avatar_name": "Aldric",
  "utterance_type": "speech", "total_bytes": 98304 }

{ "type": "audio_chunk", "session_id": 1, "avatar_id": 2,
  "data": "<base64>", "offset": 0 }

{ "type": "audio_end", "session_id": 1, "avatar_id": 2, "avatar_name": "Aldric",
  "cancelled": false }
```

### Frontend (`frontend/src/`)

| File | Change |
|---|---|
| `hooks/useAudioPlayer.js` | New hook — Web Audio API queue for WAV playback |
| `pages/TablePage.jsx` | Wired `useAudioPlayer`; merged `speaking.avatarId` into status badges |

`useAudioPlayer` flow:
1. `audio_start` → initialise accumulation buffer for `avatar_id`
2. `audio_chunk` → push base64 strings into buffer
3. `audio_end` → join all chunks → `atob` → `decodeAudioData` → `AudioBufferSourceNode` → queue → `playNext()`
4. `avatar_speaking` → update `speaking` state for UI badges
5. Backchannels play at 60% via `gainNode.gain.value = 0.6`

### Pipeline Manager (`backend/app/services/pipeline_manager.py`)

Updated to initialise Phase 3 components per session start:

- **TTSEngine** — singleton, loaded once across all sessions
- **AudioOutputManager** — per session, shares the pipeline's `EchoGate`
- **PresenceLayer** — per session, holds reference to `TTSEngine` for holding phrases
- Speaker embeddings loaded automatically from `avatar.voice_embedding_path` at session start

### One-Time Scripts (`scripts/`)

| Script | Purpose |
|---|---|
| `clone_voice.py` | Extract XTTS-v2 speaker embedding from a WAV sample → `.npz` |
| `generate_backchannels.py` | Pre-synthesize all backchannel clips for one avatar |

#### Voice Cloning

```bash
cd backend
python ../scripts/clone_voice.py --avatar-id 1 --sample voice_samples/aldric.wav
# Output: data/embeddings/1.npz
```

Then update the avatar record:
```
PATCH /api/avatars/1  { "voice_embedding_path": "data/embeddings/1.npz" }
```

#### Pre-generating Backchannels

```bash
python ../scripts/generate_backchannels.py --avatar-id 1
# Output: data/backchannels/1/{category}/{text}.wav  (25 clips)
```

## Hardware Dependencies

| Library | Status | Fallback |
|---|---|---|
| `TTS` (Coqui) | Optional | Silent WAV stub returned |
| `torch` | Optional | TTS falls back automatically |
| `numpy` | **Required** | — |

## Installing TTS (CUDA)

```bash
cd backend
.venv/Scripts/pip install TTS
# Ensure CUDA-enabled PyTorch is already installed from Phase 2
```

XTTS-v2 model is downloaded on first use (~1.8GB). VRAM: ~3–4GB.

## Tests

40 new tests added (90 total), covering:
- `TTSEngine` — stub mode, speaker loading, emotion speeds
- `ResponsePostProcessor` — all 7 pipeline steps, edge cases
- `AmbientReactions` — holding phrase selection, emotion tag extraction
- `BackchannelPlayer` — should_play logic, clip selection, manager registration
- `AudioOutputManager` — start/end broadcasts, cancel, priority ordering
