# Phase 6 — D&D 5e Rules Engine & Combat

## Overview

Phase 6 adds a full D&D 5e rules engine and real-time combat tracker. The system lets the DM start/end combat, track initiative order, apply damage and healing, manage conditions and spell slots, and automatically detects combat signals from the live transcript to feed relevant state into the avatar LLM context.

---

## New Files

### `backend/app/rules/`

| File | Purpose |
|------|---------|
| `action_economy.py` | Per-turn action budget: Action, Bonus Action, Reaction, Movement (feet) |
| `conditions.py` | All 14 5e standard conditions + exhaustion levels, incapacitation logic |
| `spell_slots.py` | Slot tracker with full caster / half caster progression tables (levels 1–20) |
| `concentration.py` | One-slot concentration tracking; displacement on new spell; DC calculation |
| `combat.py` | `CombatState` machine + `CombatantEntry` + `DeathSaveState` |
| `available_actions.py` | Builds formatted text block describing a combatant's available actions |
| `combat_detector.py` | Stateless regex-based detector for DM transcript signals |

### `backend/app/services/combat_manager.py`

Singleton service owning one `CombatState` per active session. Handles:
- Pipeline integration (`process_transcript` → `get_available_actions_text`)
- Manual DM control (start/end combat, damage, heal, conditions, rests)

### `backend/app/routers/combat.py`

REST API at `/api/combat/{session_id}/`:

| Method | Path | Action |
|--------|------|--------|
| GET | `/state` | Current combat state dict |
| POST | `/start` | Start combat with combatant list |
| POST | `/end` | End combat |
| POST | `/next-turn` | Advance to next turn |
| POST | `/initiative` | Set a combatant's initiative |
| POST | `/death-save` | Record a death saving throw |
| POST | `/damage` | Apply damage |
| POST | `/heal` | Apply healing |
| POST | `/condition` | Add a condition |
| DELETE | `/condition` | Remove a condition |
| POST | `/rest` | Apply short or long rest |
| GET | `/actions/{avatar_id}` | Get available actions text for an avatar |

### `frontend/src/components/InitiativeTracker.jsx` + `.module.css`

Combat panel embedded in the Table page sidebar:
- Start Combat form — set combatants, initiatives, HP; add enemy rows
- Initiative order list with current-turn highlight, HP bars, condition icons
- Inline damage/heal quick inputs on active combatant row
- Death save pips + Success/Failure buttons at 0 HP
- Next Turn button; End Combat control
- Round counter

---

## Modified Files

| File | Change |
|------|--------|
| `backend/app/llm/prompt_builder.py` | Added `available_actions_text` field to `AvatarContext`; injected into system prompt during combat |
| `backend/app/llm/dispatcher.py` | Added `available_actions_text` to `DispatchRequest` |
| `backend/app/audio/pipeline.py` | Combat signal detection in `_flush_buffer`; actions text in `_dispatch_response` |
| `backend/app/services/pipeline_manager.py` | Injects `combat_manager` into pipeline; calls `stop_session` on pipeline stop |
| `backend/app/main.py` | Registers `combat.router` |
| `frontend/src/api/client.js` | Added all combat API methods |
| `frontend/src/pages/TablePage.jsx` | Imports and renders `<InitiativeTracker>` in sidebar |

---

## Key Design Decisions

### In-memory combat state (no DB)
`CombatState` is session-scoped and held in the `CombatManager` dictionary. The transcript is the authoritative combat log — persisting intermediate HP to the DB would require migrations and add complexity with minimal benefit.

### Stateless combat detector
`CombatDetector` is purely functional (regex matching). It is called on every DM transcript segment from the pipeline. No state is held in the detector itself — priority ordering (end > start > death_save > damage > next_round > turn_prompt) ensures deterministic results.

### Available actions injection
The `AvailableActionsBuilder` produces a compact text block describing an avatar's current action budget, spell slots, conditions, and concentration. This is injected into the LLM system prompt only when the session is in active combat. Non-combat responses are unaffected (empty string is a no-op).

### Instant death rule
Damage that reduces an avatar from positive HP by an amount ≥ their HP max triggers instant death (marked `is_dead=True` on the `DeathSaveState`). This mirrors the 5e "massive damage" rule.

---

## Tests

101 new tests in `backend/tests/test_combat_modules.py` (278 total passing):

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestActionEconomyTracker` | 11 | Use/reset of action, bonus, reaction, movement |
| `TestConditionTracker` | 12 | Add/remove, tick/expire, incapacitation, exhaustion |
| `TestSpellSlotTracker` | 14 | Use, rests, from_dict, from_class_level, round-trip |
| `TestConcentrationTracker` | 13 | Start, displace, break, tick, DC calculation |
| `TestDeathSaveState` | 6 | Success/failure accumulation, crit, heal reset |
| `TestCombatState` | 17 | Start, turn order, damage, heal, death saves, round |
| `TestCombatDetector` | 13 | All signal types, priority ordering, DM detection |
| `TestCombatManager` | 15 | Full integration across all manager methods |
