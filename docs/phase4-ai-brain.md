# Phase 4 — AI Brain

## What Was Built

### New Modules (`backend/app/llm/`)

| Module | Purpose |
|---|---|
| `prompt_builder.py` | Assembles full modular system prompt + user message at runtime |
| `router.py` | Routes LLM calls to Ollama or Claude; graceful stubs when unavailable |
| `dispatcher.py` | End-to-end orchestrator: holding phrase → LLM → post-process → TTS → audio |

---

## End-to-End Response Flow

```
AudioPipeline._flush_buffer()
      │
      ├─ context_engine.evaluate() fires: should_respond = True
      │
      └─ AudioPipeline._dispatch_response()
               │
               └─ asyncio.create_task(dispatcher.dispatch(req))  ← non-blocking
                        │
                        ├─ 1. PresenceLayer.play_holding_phrase()   ← immediate
                        │         └─ TTS synth of "Hmm…" / "Give me a moment..."
                        │            broadcast holding_phrase transcript entry
                        │            enqueue audio at priority 3
                        │
                        ├─ 2. PromptBuilder.build(AvatarContext)
                        │         └─ Assembles system + user message
                        │
                        ├─ 3. call_llm()  [thread pool, non-blocking]
                        │         ├─ select_route() → "ollama" or "claude"
                        │         └─ call_ollama() or call_claude()
                        │
                        ├─ 4. ResponsePostProcessor.process()
                        │         └─ emotion, markdown, stage dirs, length, jitter
                        │
                        ├─ 5. asyncio.sleep(delay_seconds)   ← jitter 1.5–4s
                        │
                        ├─ 6. TTSEngine.synthesize()  [thread pool]
                        │
                        ├─ 7. broadcast transcript entry (type: "transcript")
                        │
                        ├─ 8. AudioOutputManager.enqueue(wav_bytes, priority)
                        │
                        └─ 9. context_engine.on_avatar_spoke()   ← cooldown reset
```

---

## Prompt Builder (`prompt_builder.py`)

Assembles a modular system prompt from `AvatarContext` at runtime. All sections optional — absent data degrades gracefully.

### Prompt Structure

```
You are {NAME}, a {RACE} {CLASS} (Level {LEVEL}).
Your player ({PLAYER}) is absent tonight. Portray them faithfully.

== IDENTITY ANCHOR ==
Alignment: {ALIGNMENT}
Background: {BACKGROUND}
Personality: {TRAITS}
Ideals / Bonds / Flaws (if set)

== CHARACTER VOICE ==         ← omitted if all fields empty
Sentence style: {SENTENCE_STYLE}
Verbal habits: {VERBAL_TICS}
Never say: {NEVER_SAY}

== MECHANICAL STATE ==
Current HP: {HP}/{MAX_HP}
Spell slots remaining: ... (if any)
Active conditions: ...       (if any)

== PARTY RELATIONSHIPS ==     ← omitted if dict is empty
{name}: {note}
(recent) {cross_avatar_note}

== RELEVANT MEMORY ==         ← omitted if list is empty (Phase 5 will fill)
- {chunk}

== RESPONSE RULES (CRITICAL) ==
• Length: {context-type-specific instruction}
• Always first person
• No markdown, no asterisks, no parentheticals
• NEVER narrate outcomes (DM's job)
• NEVER speak as another character or the DM
• Allowed emotion cues: [quietly] [urgently] [laughing] [tense] [whispering]
CONTEXT TYPE: {CONTEXT_TYPE}
```

**User message** — the last 30 transcript lines followed by `[Respond now as {NAME}.]`

---

## LLM Router (`router.py`)

### Routing Table

| Context type | Route |
|---|---|
| `combat_turn` | Ollama |
| `casual_roleplay` | Ollama |
| `direct_question` | Ollama |
| `party_debate` | Ollama |
| `emotional_beat` | Claude |
| `backstory_call` | Claude |
| `npc_social` | Claude |
| `moral_dilemma` | Claude |

**Keyword escalation** — if any of these appear in the last 5 transcript lines, route escalates to Claude regardless of context type:

```python
CLAUDE_ROUTING_KEYWORDS = {
    "backstory", "trauma", "betrayal", "forgive", "sacrifice", "regret",
    "childhood", "died", "loved", "swore", "oath", "memory", "dream",
    "fear", "family", "vow", "alone", "promised"
}
```

### Graceful Degradation

- **Ollama unreachable**: returns `LLMResponse(text="", route="stub", error=...)`
- **Claude: no API key**: returns `LLMResponse(text="", route="stub", error="no_api_key")`
- **Claude: API failure**: logs error, returns stub — dispatcher logs warning and skips TTS

### Ollama Call Parameters

```python
{
    "model": "llama3.1:8b",
    "stream": False,
    "options": {"temperature": 0.85, "top_p": 0.9, "num_predict": 120}
}
```

### Claude Call Parameters

Model: `claude-haiku-4-5-20251001`, `max_tokens: 256`

---

## LLM Dispatcher (`dispatcher.py`)

Per-session orchestrator. Injected with:
- `TTSEngine` (singleton)
- `AudioOutputManager` (per session)
- `PresenceLayer` (per session)
- `ContextEngine` (per pipeline)
- `broadcast_fn` (WebSocket)
- `_avatar_profiles` (dict of avatar DB fields, snapshotted at session start)
- `_pipeline` reference (for appending avatar speech to transcript context)

`dispatch()` is designed to be called with `asyncio.create_task()` — it does not block the pipeline loop.

---

## Pipeline Wiring

`AudioPipeline._flush_buffer` now calls `_dispatch_response()` (instead of the Phase 2/3 placeholder `_broadcast_status`).

`_dispatch_response()` builds a `DispatchRequest` from:
- The context engine `EngineDecision`
- The current `_recent_lines` transcript snapshot
- The avatar profile from `dispatcher._avatar_profiles[avatar_id]`

The pipeline's `_recent_lines` ring buffer (max 30 lines) tracks both human speech and avatar responses, keeping the LLM context window fresh.

---

## Configuration Added

| Setting | Default | Description |
|---|---|---|
| `OLLAMA_MODEL` | `llama3.1:8b` | Ollama model name |
| `OLLAMA_TIMEOUT_S` | `30.0` | HTTP timeout for Ollama calls |
| `CLAUDE_MODEL` | `claude-haiku-4-5-20251001` | Claude model ID |
| `CLAUDE_MAX_TOKENS` | `256` | Max response tokens (short responses) |

---

## Tests

39 new tests added (129 total), covering:
- `PromptBuilder` — all 7 prompt sections, edge cases, transcript capping, empty fallbacks
- `LLMRouter` — routing table, keyword escalation, stub behaviour for unreachable backends
- `LLMDispatcher` — full dispatch cycle with mocked LLM/TTS, holding phrase, cooldown, empty response handling
