"""
Combat API Router — Phase 6.

Endpoints:
  GET  /api/combat/{session_id}/state
      Return current combat state (phase, round, initiative order).

  POST /api/combat/{session_id}/start
      Start combat with a list of combatants + initiatives.

  POST /api/combat/{session_id}/end
      End combat.

  POST /api/combat/{session_id}/next-turn
      Advance to the next combatant's turn.

  POST /api/combat/{session_id}/initiative
      Set or update initiative for a specific combatant.

  POST /api/combat/{session_id}/death-save
      Record a death saving throw result.

  POST /api/combat/{session_id}/damage
      Apply damage to a combatant.

  POST /api/combat/{session_id}/heal
      Heal a combatant.

  POST /api/combat/{session_id}/condition
      Add a condition to a combatant.

  DELETE /api/combat/{session_id}/condition
      Remove a condition from a combatant.

  POST /api/combat/{session_id}/rest
      Apply short or long rest.

  GET  /api/combat/{session_id}/actions/{avatar_id}
      Get available actions block for a specific avatar.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.combat_manager import combat_manager

router = APIRouter(prefix="/combat", tags=["combat"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class CombatantIn(BaseModel):
    avatar_id: int = 0
    name: str
    initiative: int
    initiative_bonus: int = 0
    hp_current: int = 10
    hp_max: int = 10
    is_enemy: bool = False
    spell_slots: dict[str, Any] | None = None


class StartCombatRequest(BaseModel):
    combatants: list[CombatantIn]


class InitiativeUpdate(BaseModel):
    avatar_id: int
    initiative: int


class DeathSaveRequest(BaseModel):
    avatar_id: int
    success: bool


class DamageRequest(BaseModel):
    avatar_id: int
    damage: int


class HealRequest(BaseModel):
    avatar_id: int
    hp: int


class ConditionRequest(BaseModel):
    avatar_id: int
    condition: str
    source: str = ""
    duration_rounds: int = -1


class RemoveConditionRequest(BaseModel):
    avatar_id: int
    condition: str


class RestRequest(BaseModel):
    avatar_id: int
    rest_type: str   # "short" | "long"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{session_id}/state")
async def get_combat_state(session_id: int):
    """Return current combat state for a session."""
    return combat_manager.get_combat_state_dict(session_id)


@router.post("/{session_id}/start")
async def start_combat(session_id: int, body: StartCombatRequest):
    """Start combat. Sorts combatants by initiative automatically."""
    if not body.combatants:
        raise HTTPException(status_code=400, detail="At least one combatant required")
    state = combat_manager.start_combat(
        session_id,
        [c.model_dump() for c in body.combatants],
    )
    return state.to_dict()


@router.post("/{session_id}/end")
async def end_combat(session_id: int):
    """End combat and clear all combat state for this session."""
    combat_manager.end_combat(session_id)
    return {"session_id": session_id, "phase": "ended"}


@router.post("/{session_id}/next-turn")
async def next_turn(session_id: int):
    """Advance to the next combatant's turn."""
    if not combat_manager.is_in_combat(session_id):
        raise HTTPException(status_code=409, detail="No active combat for this session")
    combatant = combat_manager.next_turn(session_id)
    if combatant is None:
        raise HTTPException(status_code=500, detail="Could not advance turn")
    state = combat_manager.get_combat_state_dict(session_id)
    return {
        "current_combatant": combatant.to_dict(),
        "round": state.get("round"),
        "phase": state.get("phase"),
    }


@router.post("/{session_id}/initiative")
async def set_initiative(session_id: int, body: InitiativeUpdate):
    """Set or update a combatant's initiative roll."""
    ok = combat_manager.set_initiative(session_id, body.avatar_id, body.initiative)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Combatant with avatar_id={body.avatar_id} not found in combat",
        )
    return combat_manager.get_combat_state_dict(session_id)


@router.post("/{session_id}/death-save")
async def death_save(session_id: int, body: DeathSaveRequest):
    """Record a death saving throw result for an avatar."""
    result = combat_manager.record_death_save(session_id, body.avatar_id, body.success)
    state = combat_manager.get_state(session_id)
    death_saves = {}
    if state:
        ds = state.get_death_saves(body.avatar_id)
        death_saves = ds.to_dict()
    return {
        "avatar_id": body.avatar_id,
        "result": result,
        "death_saves": death_saves,
    }


@router.post("/{session_id}/damage")
async def apply_damage(session_id: int, body: DamageRequest):
    """Apply damage to a combatant."""
    result = combat_manager.deal_damage(session_id, body.avatar_id, body.damage)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{session_id}/heal")
async def apply_heal(session_id: int, body: HealRequest):
    """Heal a combatant."""
    result = combat_manager.heal(session_id, body.avatar_id, body.hp)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{session_id}/condition")
async def add_condition(session_id: int, body: ConditionRequest):
    """Add a condition to a combatant."""
    ok = combat_manager.add_condition(
        session_id,
        body.avatar_id,
        body.condition,
        source=body.source,
        duration_rounds=body.duration_rounds,
    )
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown condition '{body.condition}' or combatant not found",
        )
    return {"avatar_id": body.avatar_id, "condition_added": body.condition}


@router.delete("/{session_id}/condition")
async def remove_condition(session_id: int, body: RemoveConditionRequest):
    """Remove a condition from a combatant."""
    ok = combat_manager.remove_condition(session_id, body.avatar_id, body.condition)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Condition '{body.condition}' not found on avatar {body.avatar_id}",
        )
    return {"avatar_id": body.avatar_id, "condition_removed": body.condition}


@router.post("/{session_id}/rest")
async def rest(session_id: int, body: RestRequest):
    """Apply short or long rest to an avatar."""
    if body.rest_type not in ("short", "long"):
        raise HTTPException(status_code=400, detail="rest_type must be 'short' or 'long'")
    ok = combat_manager.rest(session_id, body.avatar_id, body.rest_type)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Avatar {body.avatar_id} not found in combat",
        )
    return {"avatar_id": body.avatar_id, "rest_type": body.rest_type, "applied": True}


@router.get("/{session_id}/actions/{avatar_id}")
async def get_available_actions(session_id: int, avatar_id: int, avatar_name: str = ""):
    """Get the available actions block for a specific avatar (for debugging/display)."""
    text = combat_manager.get_available_actions_text(
        session_id=session_id,
        avatar_id=avatar_id,
        avatar_name=avatar_name or f"Avatar {avatar_id}",
    )
    state = combat_manager.get_state(session_id)
    compact = None
    if state:
        c = state.get_combatant(avatar_id)
        if c:
            from app.rules.available_actions import available_actions_builder
            compact = available_actions_builder.build_compact(
                budget=c.action_economy.get_budget(),
                conditions=c.conditions,
                concentration=c.concentration,
                spell_slots=c.spell_slots,
            )
    return {
        "session_id": session_id,
        "avatar_id": avatar_id,
        "in_combat": combat_manager.is_in_combat(session_id),
        "actions_text": text,
        "actions_compact": compact,
    }
