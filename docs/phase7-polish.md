# Phase 7 — Inter-Avatar Dynamics & Polish

## Overview

Phase 7 adds inter-avatar awareness, runtime settings control, and aesthetic polish. The system now feels like a complete product: avatars reference each other naturally, the DM can tune all timing parameters live from the browser, and the UI carries a full D&D atmosphere.

---

## New Features

### Cross-Avatar Reference Injection

`backend/app/audio/cross_avatar.py` — `CrossAvatarReferencer`

Maintains a rolling buffer of recent avatar speech per session. When an avatar is about to respond, there is a 25% chance that a brief note about another avatar's recent speech is injected into the LLM prompt as `cross_avatar_note`.

- Quotes are only eligible if spoken by a *different* avatar
- Quotes older than 120 seconds are excluded
- Very short utterances (< 4 words) are not recorded
- The most recent eligible quote is always selected
- Truncates long quotes at 120 characters
- Buffer capped at 10 entries

Wired into the pipeline in `_dispatch_response` and recorded in `LLMDispatcher.dispatch` (step 10, after the response is generated).

The `cross_avatar_note` field was already present on `AvatarContext` and `DispatchRequest` (from Phase 4 planning); Phase 7 provides the implementation.

**Prompt injection location:** Inside the `== PARTY RELATIONSHIPS ==` section, as a `(recent)` note.

---

### Settings Panel

`backend/app/routers/settings.py` — REST API at `/api/settings`

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/settings` | Return all tunable runtime settings |
| PATCH | `/api/settings` | Update one or more settings (in-memory) |

All changes take effect immediately without restart. Values reset on server restart — edit `.env` for permanent changes.

**Tunable at runtime:**
- LLM: `ollama_model`, `claude_model`, `claude_max_tokens`, `ollama_timeout_s`
- Audio: `vad_threshold`, `aec_decay_ms`
- Timing: `silence_gap_trigger`, `self_cooldown_seconds`, `avatar_cooldown_seconds`, `interrupt_confidence_threshold`
- Naturalism: `response_jitter_min`, `response_jitter_max`, `backchannel_min_gap`, `backchannel_chance`
- Memory: `memory_top_k`, `transcript_context_lines`

`frontend/src/pages/SettingsPage.jsx` — React settings panel at `/settings`. Sections match the API groupings. Unsaved fields are highlighted in amber. Save/Discard buttons with inline feedback.

---

### D&D Aesthetic Enhancements

`frontend/src/index.css` additions:
- **Parchment noise texture** — SVG noise filter overlay on `body::before` (mix-blend-mode: overlay, 3% opacity — adds grain without impacting readability)
- **Floating ember particles** — `EmberParticles.jsx` component; 5 amber CSS-animated embers rise from the bottom of the Table page
- **Ornate divider** — `.ornate-divider` utility class with gradient gold lines
- **Portrait frame** — `.portrait-frame` class adds a gold gradient border overlay
- **Card lift** — `.card-interactive` adds hover lift effect

Fonts (already loaded): Cinzel (headings), IM Fell English (transcript/body text), Inter (UI).
Candleflame animation (`.speaking`) already present from Phase 1 — applied to avatar panels when speaking.

---

### DM Hotword Suppression

Already implemented in Phase 2 (`ContextEngine.on_dm_hotword()` with 30-second suppression window). Phase 7 confirms and tests this behaviour. Hotwords: `hold`, `pause`, `stop`, `wait`, `cut`.

---

## Modified Files

| File | Change |
|------|--------|
| `backend/app/audio/pipeline.py` | Instantiate `CrossAvatarReferencer`; get note in `_dispatch_response` |
| `backend/app/llm/dispatcher.py` | Record avatar speech into `pipeline._cross_avatar` after each response |
| `backend/app/main.py` | Register `settings_router` |
| `frontend/src/App.jsx` | Add Settings nav link and route |
| `frontend/src/api/client.js` | Add `getSettings`, `updateSettings` |
| `frontend/src/pages/TablePage.jsx` | Add `EmberParticles` |
| `frontend/src/index.css` | Parchment texture, ember animation, ornate utilities |

---

## Tests

27 new tests in `backend/tests/test_phase7_polish.py` (305 total passing):

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestCrossAvatarReferencer` | 12 | Recording, retrieval, probability, age cutoff, buffer size, format |
| `TestSettingsAPI` | 5 | GET, PATCH, validation, none-field handling |
| `TestContextEngineDMHotword` | 7 | Hotword suppression, cooldown, multi-avatar, mode filtering |
| `TestPromptBuilderCrossAvatarNote` | 3 | Note injection, no-op when empty, section placement |
