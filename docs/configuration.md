# Configuration Reference

Everything you can configure in Vestige — environment variables, tuning parameters, and the hot-reloadable YAML prompt files.

---

## Environment Variables

Copy `.env.example` to `.env` before starting the backend. The backend reads these at startup via pydantic-settings.

### API Keys

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `ANTHROPIC_API_KEY` | Yes | Claude Sonnet 4.6 — deep-path LLM and post-session summariser |
| `OPENAI_API_KEY` | Yes | GPT-4o — fast-path LLM for combat and casual roleplay |
| `DEEPGRAM_API_KEY` | Yes | Streaming speech-to-text |
| `ELEVENLABS_API_KEY` | No | Avatar voice synthesis. Falls back to Edge-TTS if not set. |

### Server

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `HOST` | `127.0.0.1` | Backend bind address |
| `PORT` | `8000` | Backend bind port |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:4173` | Comma-separated list of allowed frontend origins |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/campaign.db` | Database connection string |

### Debugging

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `DEBUG_MODE` | `false` | Enables verbose backend logging |
| `VITE_DEBUG_MODE` | `false` | Logs all errors and rejected promises to the browser console |
| `LOG_LEVEL` | `INFO` | Backend log level: `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

### Audio hardware

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `MIC_DEVICE_INDEX` | `0` | Index of the input device to capture from. Run `scripts/list_audio_devices.py` to find yours. |

---

## Tuning Parameters

These settings are exposed via the Settings page in the UI and the `GET / PATCH /api/settings` endpoint. Changes applied through the API take effect immediately without restarting. They map to fields in `backend/app/config.py`.

### Audio pipeline

| Setting | Default | Description |
| ------- | ------- | ----------- |
| `deepgram_model` | `nova-3` | Deepgram STT model |
| `deepgram_endpointing_ms` | `800` | Milliseconds of silence that mark utterance end. Increase if avatars interrupt mid-sentence; decrease for snappier triggering. |
| `sample_rate` | `16000` | Microphone sample rate in Hz |
| `aec_decay_ms` | `200` | How long after avatar speech stops before the AEC gate reopens |

### Response timing

| Setting | Default | Description |
| ------- | ------- | ----------- |
| `response_jitter_min` | `1.5` | Minimum delay (seconds) before an avatar responds, to avoid instant-reply feel |
| `response_jitter_max` | `4.0` | Maximum delay (seconds) — actual delay is random within this range |
| `silence_gap_trigger` | `4.0` | Seconds of table silence that can prompt an ambient avatar reaction |
| `self_cooldown_seconds` | `12.0` | Minimum gap before an avatar can speak again after speaking |
| `avatar_cooldown_seconds` | `3.0` | Minimum gap before an avatar can respond to a *different* avatar's speech |

### Avatar participation

| Setting | Default | Description |
| ------- | ------- | ----------- |
| `max_avatar_chain_depth` | `3` | Maximum consecutive avatar-to-avatar reaction chain before the loop is cut |
| `avatar_speech_cooldown_s` | `8.0` | Minimum seconds between any avatar reacting to avatar speech |
| `interrupt_confidence_threshold` | `0.6` | Minimum context-engine score required for an avatar to interrupt an ongoing utterance |
| `backchannel_chance` | `0.35` | Base probability an avatar plays a backchannel sound while someone speaks |
| `backchannel_min_gap` | `8.0` | Minimum seconds between backchannel sounds per avatar |

### LLM

| Setting | Default | Description |
| ------- | ------- | ----------- |
| `claude_model` | `claude-sonnet-4-6` | Anthropic model for deep-path responses and summarisation |
| `claude_max_tokens` | `256` | Maximum response tokens on the Claude path |
| `gpt4o_model` | `gpt-4o` | OpenAI model for fast-path responses |
| `gpt4o_max_tokens` | `200` | Maximum response tokens on the GPT-4o path |
| `gpt4o_temperature` | `0.85` | Sampling temperature for GPT-4o responses |
| `actor_instructions_offset` | `3` | Lines from the end of the transcript where the "stay in character" reminder is injected |

### Memory

| Setting | Default | Description |
| ------- | ------- | ----------- |
| `memory_top_k` | `5` | Number of memory chunks retrieved per dispatch via vector similarity |
| `transcript_context_lines` | `30` | Lines of recent transcript included in the LLM prompt |
| `summary_method` | `balanced` | Post-session summary style: `facts` · `short` · `balanced` · `long` |
| `summary_previous_sessions` | `6` | How many prior session summaries to include when generating a new one |
| `mid_session_compress_mins` | `60` | Minutes of inactivity before mid-session transcript compression runs |

### Trait evolution

| Setting | Default | Description |
| ------- | ------- | ----------- |
| `trait_decay_weekly_pct` | `0.10` | Fractional strength decay per week — 10% by default |
| `trait_manifestation_base_probability` | `0.30` | Base probability a trait manifests when its keyword is triggered (scales with strength) |

### ElevenLabs TTS

| Setting | Default | Description |
| ------- | ------- | ----------- |
| `elevenlabs_model_quality` | `eleven_v3` | Model used for roleplay and emotional contexts (~300ms TTFB, emotion tags supported) |
| `elevenlabs_model_fast` | `eleven_flash_v2_5` | Model used for combat and quick reactions (~170ms TTFB, no emotion tags) |

---

## Hot-Reloadable Prompt Files

All routing logic and prompt text lives in `backend/prompts/`. Edit these files at any time and reload without restarting the server:

```
POST http://localhost:8000/api/prompts/reload
```

### `routing_keywords.yaml`

Controls which context types are routed to Claude vs GPT-4o.

```yaml
claude_context_types:
  - emotional_beat
  - backstory_call
  - npc_social
  - moral_dilemma

claude_routing_keywords:
  - backstory
  - trauma
  - betrayal
  - forgive
  - sacrifice
  # ... (18 keywords total)
```

Add or remove keywords to change routing. Context types not listed here go to GPT-4o.

### `context_keywords.yaml`

Keyword lists that classify utterance context type.

| Key | What it controls |
| --- | ---------------- |
| `combat_triggers` | Phrases like "roll initiative" or "your turn" that activate combat context |
| `dm_hotwords` | Words like "hold", "pause", "stop" that suppress avatar responses |
| `directed_fragments` | Fragments like "what do you think" that score an utterance as directly addressed |
| `moral_keywords` | Words that push context toward `moral_dilemma` |
| `backstory_keywords` | Words that push context toward `backstory_call` |
| `npc_social_keywords` | Words like "persuade", "negotiate" that push context toward `npc_social` |

### `length_instructions.yaml`

Per context-type response length guidance injected into the LLM prompt.

| Context type | Default guidance |
| ------------ | ---------------- |
| `combat_turn` | One sentence action + one optional flavour line |
| `casual_roleplay` | 1–2 sentences |
| `direct_question` | 2–3 sentences |
| `emotional_beat` | Up to 4 sentences if warranted |
| `backstory_call` | Up to 4 sentences |
| `moral_dilemma` | 2–3 sentences |

### `holding_phrases.yaml`

Filler phrases played while the LLM generates a response, organised by context type. Combat contexts get tense fillers; reflective contexts get quieter ones.

### `system_prompt_sections.yaml`

Static rule strings injected into the system prompt header. Contains the core behavioural constraints applied to all avatar responses:

- Output format: spoken words only, first person, no markdown
- No narration, no meta-commentary, no breaking character
- Allowed emotion cues: `[quietly]`, `[urgently]`, `[laughing]`, `[tense]`, `[whispering]`

---

## API Key Cost Estimates

All services are pay-as-you-go. Costs scale with session length and avatar verbosity.

| Service | Rough cost per 3-hour session | Notes |
| ------- | ----------------------------- | ----- |
| Deepgram | $0.50–1.50 | Billed per minute of audio processed; only runs while mic is active |
| ElevenLabs | $0.50–2.00 | Billed per character synthesised; scales with how much avatars talk |
| OpenAI (GPT-4o) | $0.10–0.50 | Fast-path responses; combat-heavy sessions cost more |
| Anthropic (Claude) | $0.05–0.30 | Deep-path responses; prompt caching reduces repeated system-prompt cost significantly |
| **Total** | **~$1–5 per session** | |

Prompt caching on the Claude path means the static portions of the system prompt (character identity, rules, trait descriptions) are billed at ~10× lower cost after the first call. On sessions with many dispatches, this makes a meaningful difference.

---

## Startup Order

### With Arize Phoenix (recommended for development)

```bash
# Terminal 1
phoenix serve       # → http://localhost:6006

# Terminal 2
cd backend
.venv\Scripts\uvicorn app.main:app --reload --port 8000

# Terminal 3
cd frontend
npm run dev         # → http://localhost:5173
```

### Without Phoenix

```bash
# Terminal 1
cd backend
.venv\Scripts\uvicorn app.main:app --reload --port 8000

# Terminal 2
cd frontend
npm run dev
```

The backend logs a warning if Phoenix isn't running but starts successfully either way.

---

## Seeding Sample Data

The scripts directory includes a seed script for populating the database with four detailed sample avatars and an active session with a seeded transcript — useful for screenshots, UI development, or testing without a live group:

```bash
cd backend
.venv\Scripts\python ..\scripts\seed_sample_data.py
```

Creates: Lyra Ashveil (Half-Elf Sorcerer), Tormund Greystone (Dwarf Paladin), Pip Nettlefinch (Halfling Rogue), and Varek of the Ashen Shore (Human Ranger) — each with full character sheets, personality prompts, and archetypes.
