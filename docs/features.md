# Features

How each of Vestige's systems works. If you're looking for setup instructions, start with the [README](../README.md). For system architecture and data flow, see [Architecture](architecture.md). For configuration options, see [Configuration](configuration.md).

---

## Contents

- [Fully Voiced Avatars](#fully-voiced-avatars)
- [Sub-Second Transcript Latency](#sub-second-transcript-latency)
- [Two-Layer Conversational Presence](#two-layer-conversational-presence)
- [Avatar-to-Avatar Reactions](#avatar-to-avatar-reactions)
- [Personality System](#personality-system)
- [Character Trait Evolution](#character-trait-evolution)
- [LLM Routing](#llm-routing)
- [Rules Engine](#rules-engine)
- [Persistent Memory](#persistent-memory)
- [Observability with Arize Phoenix](#observability-with-arize-phoenix)

---

## Fully Voiced Avatars

Each avatar is assigned an ElevenLabs voice ID and produces streaming audio through the browser's AudioContext. The voice synthesis pipeline uses two model tracks, switchable per avatar:

| Model | TTFB | Tags | Best for |
| ----- | ---- | ---- | -------- |
| `eleven_v3` | ~300ms | Emotion + sound tags | Roleplay, emotional beats, backstory |
| `eleven_flash_v2_5` | ~170ms | None | Combat turns, quick reactions |

**Voice parameters.** Each avatar has per-voice sliders for stability, style exaggeration, and speaker similarity, stored in the avatar record and applied at synthesis time.

**Emotion injection.** Before synthesis, a secondary LLM pass (Claude Haiku) rewrites the response with an inline emotion tag — `[tense]`, `[excited]`, `[somber]`, `[laughing]`, `[quietly]`, `[whispering]`, `[urgently]` — based on context type. Combat lines land differently from banter, and reunions sound different from ultimatums. If an active character trait manifests during the response (see [Trait Evolution](#character-trait-evolution)), its emotional signature overrides the context-derived tag.

**Fallbacks.** If no ElevenLabs voice is configured, Vestige falls back to Edge-TTS automatically (free, Microsoft voices). XTTS-v2 is also supported as a local GPU-powered fallback for completely offline operation (requires CUDA).

**Streaming playback.** Raw PCM chunks stream from the backend to the browser as they're synthesised and are handed to AudioContext before the full response is ready, keeping perceived latency low.

---

## Sub-Second Transcript Latency

Speech-to-text uses [Deepgram nova-3](https://deepgram.com/product/speech-understanding) via streaming WebSocket. Each session creates a dedicated Deepgram client, not a shared singleton — this keeps session state clean and allows concurrent sessions.

Unlike batch STT that waits for a silence window to expire before transcribing, Deepgram handles voice activity detection and endpointing internally. The `speech_final` callback fires within ~200ms of sentence completion. Endpointing sensitivity is configurable via `deepgram_endpointing_ms` (default: 800ms — increase this if avatars cut off mid-sentence, decrease for snappier triggering).

An AEC (Acoustic Echo Cancellation) gate filters PCM frames that contain avatar speech played back through speakers, preventing avatars from hearing themselves and retriggering.

---

## Two-Layer Conversational Presence

Most voice AI systems feel turn-based — you speak, it processes, it responds, repeat. Vestige uses two parallel layers to break that rhythm.

### Presence layer

Real-time, zero LLM latency. Runs while humans are speaking:

- **Backchannels** — short acknowledgement sounds ("mm", "yeah", "right") played probabilistically while speech is in progress. Weighted by the avatar's verbosity setting so quieter characters stay quieter.
- **Holding phrases** — when the full pipeline is generating a response, a context-appropriate filler phrase is played to bridge the gap. Phrases are context-aware: a combat `[tense]` context gets different fillers than a reflective `emotional_beat`.

Together, these make avatars feel present even between responses.

### Reasoning layer

The full pipeline, triggered on `speech_final`:

1. Backchannel classifier — is this a short acknowledgement? If so, skip the full pipeline.
2. Context engine evaluates each avatar — should it respond? (See [Personality System](#personality-system).)
3. For each avatar that passes: memory retrieval → prompt assembly → LLM → emotion tag injection → TTS → audio output.

A jitter delay (configurable `response_jitter_min` / `response_jitter_max`, default 1.5–4.0s) is applied before responses to avoid the instant-reply feel of most AI systems. Responses sound considered, not robotic.

---

## Avatar-to-Avatar Reactions

When an avatar speaks, its utterance is broadcast to the context engines of the other avatars. Each evaluates whether to react — producing natural multi-avatar exchanges, disagreements, and collaborative problem-solving without GM input.

**Chain depth.** The maximum number of consecutive avatar-to-avatar reactions is capped at 3 (configurable via `max_avatar_chain_depth`). This prevents runaway crosstalk spirals.

**Archetype gates.**

- **Stoic** avatars never react to another avatar's speech unless their name appears in the utterance.
- **Introvert** avatars react to other avatars at most once per minute.

**Cooldown.** All avatars observe an 8-second minimum between reactions to avatar speech (`avatar_speech_cooldown_s`). The self-cooldown check runs before the any-avatar cooldown, which matters for edge cases where an avatar is both in its own cooldown and the shared cooldown window.

---

## Personality System

### The personality prompt

At avatar creation, Vestige calls GPT-4o to generate a 150–200 word first-person internal monologue: how the character thinks, what they notice, what makes them speak up, what makes them hold back, and what they sound like under pressure. This is injected directly into the LLM system prompt on every dispatch.

The prompt can be edited manually after creation, and older avatars can have it regenerated via `POST /api/avatars/generate-personality`.

### Archetypes

Four archetypes govern participation decisions in the context engine:

| Archetype | When they speak |
| --------- | --------------- |
| **Extrovert** | Joins most conversations freely — high base participation rate |
| **Introvert** | Engages primarily when directly addressed |
| **Reactive** | Responds to questions, combat, and direct calls; ignores ambient chatter |
| **Stoic** | Speaks only when named, in combat, or directly addressed |

### Verbosity

A 0–1 float controlling how aggressively the avatar participates above its archetype's baseline. A high-verbosity Extrovert is difficult to shut up. A low-verbosity Introvert is nearly silent even when called upon. The holding phrase chance scales with this setting.

---

## Character Trait Evolution

Avatars develop persistent psychological traits extracted by Claude from post-session summaries. A spider encounter can leave an arachnophobia that surfaces in gameplay for weeks. Betrayal by a party member creates measured distrust. These aren't cosmetic — they change what the LLM knows about the character and how the voice sounds.

### Trait structure

| Field | Type | Description |
| ----- | ---- | ----------- |
| Name | str | Short label (e.g., "Arachnophobia", "Distrust of Lyra") |
| Description | str | What happened and what it means to the character |
| Strength | float (0–1) | Current intensity; starts at the value Claude extracted and decays over time |
| Trigger keywords | list[str] | Words in the transcript that fire a manifestation check |
| Emotional signature | str | Emotion tag override when the trait manifests (e.g., `[fearful]`) |
| Manifestation rate | float | How likely the trait is to surface when triggered (scales with strength) |

### Decay

Trait strength decays ~10% per week by default (`trait_decay_weekly_pct`). Without reinforcement — the spiders don't come up again, the betrayal is forgiven — the trait fades naturally. It can also be manually adjusted or removed from the Traits panel.

### Manifestation

When a trigger keyword appears in the transcript, a stochastic check fires proportional to the trait's current strength. On success:

- The trait's emotional signature overrides the TTS emotion tag for this response
- A note is prepended to the LLM context: "This response is coloured by [trait name]"

### Relationship states

Structured relationship axes — trust, affection, respect — are tracked per avatar pair. Values evolve similarly to traits, extracted from summaries, reviewed, approved, and decaying slowly without reinforcement.

---

## LLM Routing

Every utterance that reaches the dispatcher is classified by context type and routed to one of two backends:

| Backend | Context types | Why |
| ------- | ------------- | --- |
| **GPT-4o** | `combat_turn`, `casual_roleplay`, `direct_question`, `party_debate` | Low latency (~460ms avg), broad capability |
| **Claude Sonnet 4.6** | `emotional_beat`, `backstory_call`, `npc_social`, `moral_dilemma` | Richer, more nuanced responses; prompt caching reduces cost on repeated system prompts |

### Prompt caching on the Claude path

The system prompt sent to Claude is split into cacheable and non-cacheable sections. Static content — character identity, rules, static traits — is marked as cacheable. Dynamic content — current transcript, retrieved memories, active combat state — is appended after the cache breakpoint. Cache hits appear in Arize Phoenix spans as `cache_read_tokens`.

### Configuring routing

Routing is keyword-driven. The keywords that route to Claude are defined in `backend/prompts/routing_keywords.yaml`. Edit them and reload without restarting:

```http
POST http://localhost:8000/api/prompts/reload
```

---

## Rules Engine

The rules engine tracks tabletop RPG mechanics so the LLM plays characters accurately:

- **Action economy** — actions, bonus actions, and reactions, reset on turn end
- **Spell slots** — per-level expenditure and recovery on short and long rest
- **Concentration** — which avatar holds concentration on which spell; new concentration breaks existing
- **Conditions** — standard conditions (frightened, poisoned, incapacitated, etc.), with mechanical effects applied to the context

This state is injected into the system prompt so the LLM doesn't violate rules — an avatar won't cast a spell already expended this encounter, and a concentrating avatar won't double-concentrate. Combat turn order is tracked via the initiative tracker on the Table page and surfaces to each avatar on their turn.

---

## Persistent Memory

### Storage

Every utterance is stored in SQLite with speaker, speaker type, text, and timestamp. After the session ends, a summariser reads the full transcript and produces a structured summary.

### Retrieval

At dispatch time, the memory retriever queries sqlite-vec (vector search on text embeddings stored in SQLite) for the most relevant memories given the current transcript context. The top-`k` results (`memory_top_k`, default 5) are injected into the system prompt before the LLM call.

### Post-session summaries

Summaries are generated by Claude on the Memory Review page and require GM approval before anything is written to the database. The summariser:

1. Reads the full session transcript
2. Reads the last 6 prior session summaries for narrative continuity (`summary_previous_sessions`)
3. Extracts notable events, NPC names, and plot developments
4. Extracts trait deltas — new traits, reinforced traits, weakened traits
5. Extracts relationship deltas — trust/affection/respect changes per avatar pair

The GM reviews each extracted item, edits if needed, and approves. Only then are changes written.

**Summary verbosity** is configurable via `summary_method`: `facts` (terse event list), `short`, `balanced` (default), or `long` (narrative prose).

---

## Observability with Arize Phoenix

Vestige integrates with [Arize Phoenix](https://phoenix.arize.com) for LLM observability. This is entirely optional — the app runs normally without it — but it's very useful for debugging unexpected avatar behaviour.

### Setup

```bash
pip install arize-phoenix
phoenix serve   # → http://localhost:6006
```

Start Phoenix before the backend. The backend detects Phoenix at startup and begins exporting OpenTelemetry spans automatically.

### What each span includes

- Full system prompt — character identity, traits, memory chunks, rules state
- User message (the transcript utterance)
- Avatar response
- End-to-end latency
- Token counts including `cache_read_tokens` and `cache_write_tokens` for Claude calls
- Span attributes: avatar ID, context type, LLM route, session ID

### What to look for

If an avatar says something wrong or out of character, find the span and inspect the system prompt. Common causes: a stale trait with a conflicting emotional signature, a retrieved memory chunk that doesn't apply, or a routing decision that sent an emotional moment to GPT-4o instead of Claude.
