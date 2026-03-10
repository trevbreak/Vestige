# Phase 2 — Voice Input Pipeline

## What Was Built

### Audio Processing Modules (`backend/app/audio/`)

| Module | Purpose |
|---|---|
| `aec_gate.py` | Acoustic Echo Cancellation gate — blocks mic during TTS + 200ms decay |
| `vad.py` | silero-vad wrapper — segments continuous PCM into speech regions |
| `transcriber.py` | faster-whisper wrapper — GPU transcription with graceful CPU/stub fallback |
| `backchannel_classifier.py` | Classifies utterances as "backchannel" or "statement" |
| `overlap_detector.py` | Detects simultaneous speakers via RMS variance; selects dominant half |
| `context_engine.py` | Full decision engine — interrupt scoring, suppression logic, routing |
| `pipeline.py` | Orchestrator tying all modules into a streaming background coroutine |

### Context Engine Decision Flow

```
incoming transcript
       │
       ├─ [Suppression checks] (fail-fast, ordered by priority)
       │     absent mode → reject
       │     AEC gate closed → reject
       │     human speaking → reject
       │     DM hotword < 30s → reject (Priority 1 cancel)
       │     self cooldown → reject
       │     any-avatar cooldown → reject
       │
       ├─ [Interrupt confidence scoring]
       │     avatar name mentioned   +0.8
       │     question mark           +0.3
       │     directed fragment       +0.4
       │     capped at 1.0
       │
       ├─ [Trigger evaluation]
       │     score ≥ 0.6   → full response (Priority 2–4)
       │     silence gap   → passive reaction (Priority 5)
       │     name recent   → elevated (Priority 3)
       │     combat phrase → combat_turn context
       │
       └─ [Context type classification]
             combat keywords   → combat_turn (Ollama)
             emotional keywords → emotional_beat / backstory_call (Claude)
             question          → direct_question (Ollama)
             NPC social words  → npc_social (Claude)
             default           → casual_roleplay (Ollama)
```

### New API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/pipeline/{id}/start` | Start mic capture for a session |
| `POST` | `/api/pipeline/{id}/stop` | Stop mic capture |
| `GET` | `/api/pipeline/{id}/status` | Check if pipeline is running |

### WebSocket Message Types

**Server → Client:**
```json
{ "type": "transcript", "session_id": 1, "entry": { ... } }
{ "type": "pipeline_status", "session_id": 1, "status": "started" }
{ "type": "pong" }
```

**Client → Server:**
```json
{ "type": "ping" }
```

### Frontend Updates (Table Page)

- **Start/Stop Listening button** — calls pipeline API, reflects running state
- **Avatar status badges** update in real-time from WebSocket: Listening → Thinking… → Speaking
- **Candleflame pulse animation** activates on speaking avatars
- **Transcript line types** rendered differently:
  - `speech` — normal
  - `holding_phrase` — italic, dimmed, shows ⏳
  - `backchannel` — extra dimmed, small font
  - `overlap` — amber left border
  - `inaudible` — hidden from view

## Architecture: How the Pipeline Runs

```
FastAPI startup
    │
    └─ pipeline_manager (singleton)

POST /api/pipeline/{id}/start
    │
    ├─ Creates AudioPipeline(session_id, avatar_ids, broadcast_fn)
    ├─ asyncio.create_task(pipeline.run())
    └─ Broadcasts "started" via WebSocket

AudioPipeline.run()
    │
    ├─ sounddevice InputStream (thread callback → asyncio.Queue)
    │
    └─ Loop:
         chunk (30ms PCM) → VAD score
         ├─ speech? → accumulate buffer
         └─ silence after speech? → flush:
               ├─ detect_overlap() → select dominant half if overlapping
               ├─ transcriber.transcribe() [in thread pool, non-blocking]
               ├─ classify_utterance() → backchannel | statement
               ├─ _is_dm_hotword() → flag if DM said "Hold"/"Pause"
               ├─ broadcast TranscriptEntry via WebSocket
               └─ context_engine.evaluate() per active avatar
                     → should_respond=True → broadcast "thinking" status
                        (Phase 4 will enqueue to LLM router here)
```

## Hardware Dependencies

Phase 2 modules degrade gracefully without GPU libraries:

| Library | Status | Fallback |
|---|---|---|
| `numpy` | **Required** | — |
| `sounddevice` | Optional | Pipeline won't start (logs error) |
| `silero-vad` + `torch` | Optional | Energy-based passthrough VAD |
| `faster-whisper` | Optional | Returns stub `[transcription unavailable]` |

## Running with GPU

Install Phase 2 GPU dependencies (after CUDA is set up):

```bash
cd backend
.venv/Scripts/pip install sounddevice faster-whisper
# For silero-vad:
.venv/Scripts/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
.venv/Scripts/pip install silero-vad
```

Set `.env`:
```
MIC_DEVICE_INDEX=0     # see scripts/list_audio_devices.py
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
```

## Tests

35 new tests added (50 total), covering:
- `EchoGate` — open/close/decay cycle
- `BackchannelClassifier` — token matching, length check, inaudible tags
- `OverlapDetector` — RMS computation, dominant-half selection
- `ContextEngine` — all suppression paths, confidence scoring, context routing
- Pipeline API — start/stop/status endpoints, edge cases

## Configuration Parameters Added

```
SAMPLE_RATE          = 16000   Hz
CHUNK_MS             = 30      ms per VAD chunk
VAD_THRESHOLD        = 0.5     silero sensitivity
AEC_DECAY_MS         = 200     ms gate after TTS
WHISPER_MODEL        = large-v3
WHISPER_DEVICE       = cuda
WHISPER_COMPUTE_TYPE = float16
SILENCE_GAP_TRIGGER  = 4.0    s
SELF_COOLDOWN_SECONDS = 12.0  s
AVATAR_COOLDOWN_SECONDS = 3.0 s
INTERRUPT_CONFIDENCE_THRESHOLD = 0.6
RESPONSE_JITTER_MIN  = 1.5   s
RESPONSE_JITTER_MAX  = 4.0   s
BACKCHANNEL_MIN_GAP  = 8.0   s
BACKCHANNEL_CHANCE   = 0.35
```
