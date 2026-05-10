# Phase 9 — Audio Stack Revamp

## Overview

Phase 9 replaces the local-model audio stack (faster-whisper + silero-VAD + XTTS-v2 + Ollama) with cloud APIs tuned for low latency and high expressiveness. It also adds avatar-to-avatar banter, character trait evolution, and prompt architecture refinements.

**Headline latency improvement:** ~8–10s voice-to-audio (XTTS-v2 batch) → ~1.5–2s (ElevenLabs Flash streaming + GPT-4o).

---

## Phase 1 — Deepgram Streaming STT

**Files:** `backend/app/audio/deepgram_stt.py`, `audio_ws.py`, `pipeline.py`

Replaced faster-whisper + silero-VAD with Deepgram nova-3 streaming WebSocket. Key changes:

- `DeepgramSTTClient` opens a persistent WebSocket to `wss://api.deepgram.com/v1/listen` with `model=nova-3`, `encoding=linear16`, `sample_rate=16000`, `interim_results=true`, `endpointing=800`
- `audio_ws.py` simplified: forwards raw int16 PCM directly to `pipeline._deepgram_stt.send()` (no VAD accumulation, no silence-gap flush)
- `pipeline._on_transcript_final(text, confidence)` replaces `_flush_buffer()` — same downstream logic (backchannel check, context engine, dispatch)
- `DEEPGRAM_API_KEY` added to `config.py`; `deepgram_endpointing_ms` tunable

**Latency gain:** 30s+ startup wait + 2–5s batch latency → ~200ms time-to-transcript.

---

## Phase 3 — GPT-4o + Claude Prompt Caching

**Files:** `backend/app/llm/router.py`

Replaced Ollama with GPT-4o as the fast-path LLM:

- `call_gpt4o()` uses OpenAI SDK (`gpt-4o`, `max_tokens=200`, `temperature=0.85`)
- `call_claude()` sends the system message as a single block with `cache_control: {"type": "ephemeral"}` — static sections (identity, voice, rules) are cached; dynamic sections (memory, transcript) change each call
- `select_route()` returns `"gpt4o"` or `"claude"` (removed `"ollama"`)
- Routing table: combat/casual/ambient → GPT-4o; emotional_beat/backstory/npc_social/moral_dilemma → Claude

---

## Phase 6 — Prompt Architecture

**Files:** `backend/app/llm/prompt_builder.py`

Three refinements from Character Card V2 / Talemate research:

1. **Author framing** — `"You are voicing {name}, a Level N Race Class in a D&D 5e campaign."` (not `"You are {name}"`). Improves long-session consistency; prevents character capture.

2. **Actor instructions offset** — compact actor reminder injected `actor_instructions_offset` (default 3) lines from the end of the transcript, not at the top. Avoids recency bias while keeping guidance "recent enough to matter."

3. **Post-history instructions** — critical response rules appended *after* the transcript so they're the last thing the model reads before generating.

---

## Phase 4 — Avatar-to-Avatar Reactions

**Files:** `backend/app/audio/pipeline.py`, `context_engine.py`

When an avatar responds, `_on_avatar_spoke_chain()` evaluates all other active avatars:

- Checks `session_chain_depth` against `max_avatar_chain_depth` (default 3)
- Tracks `session_chain_speaker_ids` — if avatar already spoke this chain, skip (prevents A→B→A loop)
- Calls `context_engine.evaluate(source="avatar_speech")` with a 30% score penalty and 8s cooldown
- Stoic avatars: never respond to avatar speech
- Introvert avatars: max 1 response per 60s to avatar speech
- Chain resets when a human speaks

---

## Phase 5 — Character Trait Evolution

**Files:** `backend/app/models/character_trait.py`, `relationship_state.py`, `services/trait_service.py`, `memory/summariser.py`, `routers/traits.py`

### Trait lifecycle

1. **Emergence** — Claude's post-session summary extracts `TraitDelta` objects (trait_name, description, trigger_keywords, emotional_signature, strength_change). DM approves → `CharacterTrait` records created/updated.
2. **Decay** — `decay_traits()` applies `(1 - 0.10) ** weeks_elapsed` decay. Traits below 0.1 strength are marked resolved.
3. **Manifestation** — each `_dispatch_response()` fetches active traits, checks trigger keywords in recent transcript, calls `should_manifest()` (stochastic: `random() < probability * strength`). Manifesting traits add their `emotional_signature` to `emotion_hints`.
4. **Reinforcement** — `reinforce_trait()` bumps `current_strength` by 0.1 on manifestation.
5. **Prompt injection** — active traits text injected under `== ACTIVE CHARACTER TRAITS ==` in system prompt.
6. **Emotion override** — first `emotion_hint` overrides the TTS emotion tag for the response.

### RelationshipState

Structured trust/affection/respect axes (replacing freetext JSON). Deltas extracted from post-session summaries and applied at approval time. DM-editable via `PATCH /api/avatars/{id}/relationships/{rel_id}`.

### Layered summary context

Last 6 prior session summaries injected as context when Claude generates a new post-session summary, providing narrative continuity ("this builds on the trust forged in Session 3").

---

## Phase 2 — ElevenLabs Streaming TTS

**Files:** `backend/app/audio/elevenlabs_tts.py`, `audio_tag_injector.py`, `tts.py`, `output_manager.py`, `llm/dispatcher.py`, `frontend/src/hooks/useAudioPlayer.js`, `frontend/src/components/AvatarForm.jsx`

### Dual-track model selection

| Model | TTFB | Audio tags | Use when |
|---|---|---|---|
| `eleven_v3` | ~300ms | Yes | Roleplay, emotional beats, backstory |
| `eleven_flash_v2_5` | ~170ms | No | Combat, quick reactions |

### Audio tag injection

For `eleven_v3`, a secondary fast LLM pass (GPT-4o-mini → Claude Haiku fallback) injects ElevenLabs tone/sound tags before synthesis. Tone tags placed at sentence start (`[somber]`, `[excited]`, `[resolute]`); sound tags placed inline (`[laughing]`, `[sighs]`). Maximum 2 tone changes per response to avoid over-tagging.

### Streaming delivery

`output_manager.enqueue_stream()` accepts an `AsyncIterator[bytes]` of raw PCM chunks. The browser receives `audio_start` with `encoding: "pcm_s16le"`, then `audio_chunk` messages, then `audio_end`. `StreamingPCMPlayer` in `useAudioPlayer.js` pre-buffers 100ms then schedules chunks on a running `AudioBufferSourceNode` cursor — audio starts playing within ~5ms of the first chunk arriving.

### Per-avatar voice params

Stored on the `Avatar` model (`elevenlabs_voice_params` JSON): stability, similarity_boost, style, use_speaker_boost. Emotion deltas applied on top at synthesis time (e.g. `urgently` → `style += 0.3, stability -= 0.2`).

---

## Alembic Migration

`a2f1c9e4b857_phase9_traits_relationships_elevenlabs.py` adds:

- `character_traits` table
- `relationship_states` table
- `elevenlabs_voice_id`, `elevenlabs_voice_params`, `elevenlabs_model_preference` columns on `avatars`

Run: `cd backend && .venv/Scripts/python -m alembic upgrade head`

---

## New Dependencies

```
deepgram-sdk>=3.0.0
elevenlabs>=1.0.0
openai>=1.0.0
```

---

## Verification Checklist

1. Set `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` in `.env`
2. Run `alembic upgrade head`
3. Set `elevenlabs_voice_id` for at least one avatar in the UI
4. Start a session — speak a question naming the avatar
5. Confirm Deepgram transcript arrives within ~300ms of speech completion
6. Confirm avatar audio starts playing before full synthesis completes (streaming check)
7. Speak again naming avatar A — confirm avatar B reacts (chain depth ≤ 3)
8. Close session, run post-session summarise — confirm `trait_deltas` in JSON
9. Approve summary — confirm `CharacterTrait` records created in DB
10. Start new session with same avatars — trigger a trait keyword — confirm trait sometimes manifests in emotion
