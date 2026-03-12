"""
Combat Manager — session-scoped combat state coordinator.

Holds one CombatState per active session.
Processes CombatDetector signals from the audio pipeline.
Provides the available_actions_text for the current combatant.

Used by:
  - AudioPipeline._flush_buffer → detect signals → update state
  - AudioPipeline._dispatch_response → inject available_actions_text into DispatchRequest
  - /api/combat/* endpoints for manual DM control
"""

from __future__ import annotations

import structlog
from typing import TYPE_CHECKING

from app.rules.combat import CombatState, CombatantEntry, CombatPhase
from app.rules.combat_detector import CombatDetector, CombatSignal
from app.rules.available_actions import AvailableActionsBuilder
from app.rules.spell_slots import SpellSlotTracker
from app.rules.conditions import ConditionTracker
from app.rules.concentration import ConcentrationTracker
from app.rules.action_economy import ActionEconomyTracker

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

_detector = CombatDetector()
_actions_builder = AvailableActionsBuilder()


class CombatManager:
    """
    Manages all active CombatState instances.
    One instance per application (singleton).
    """

    def __init__(self):
        self._states: dict[int, CombatState] = {}

    # ── State access ───────────────────────────────────────────────────────

    def get_state(self, session_id: int) -> CombatState | None:
        return self._states.get(session_id)

    def get_or_create(self, session_id: int) -> CombatState:
        if session_id not in self._states:
            self._states[session_id] = CombatState(session_id=session_id)
        return self._states[session_id]

    def is_in_combat(self, session_id: int) -> bool:
        state = self._states.get(session_id)
        return state is not None and state.is_active

    # ── Pipeline integration ───────────────────────────────────────────────

    def process_transcript(
        self,
        session_id: int,
        speaker: str,
        text: str,
        avatar_names: list[str] | None = None,
    ) -> CombatSignal:
        """
        Called from the audio pipeline for each transcript segment.
        Only processes DM speech for combat signals.
        Returns the detected CombatSignal (NONE if no signal).
        """
        if not _detector.is_dm_speech(speaker):
            return CombatSignal.NONE

        result = _detector.detect(text)
        state = self.get_or_create(session_id)

        if result.signal == CombatSignal.START_COMBAT:
            if not state.is_active:
                log.info("combat.detected_start", session_id=session_id)
                state.phase = CombatPhase.ROLLING
                # Actual combatants added via API (DM sets initiative)

        elif result.signal == CombatSignal.END_COMBAT:
            if state.is_active:
                log.info("combat.detected_end", session_id=session_id)
                state.end()

        elif result.signal == CombatSignal.TURN_PROMPT:
            if state.is_active and result.addressed_name:
                log.debug(
                    "combat.turn_prompt_detected",
                    name=result.addressed_name,
                    session_id=session_id,
                )

        elif result.signal == CombatSignal.NEXT_ROUND:
            log.debug("combat.next_round", session_id=session_id, round=state.round)

        return result.signal

    def get_available_actions_text(
        self,
        session_id: int,
        avatar_id: int,
        avatar_name: str,
        spells_known: list[str] | None = None,
        equipment: list[str] | None = None,
    ) -> str:
        """
        Build the available actions block for a specific avatar.
        Returns empty string if not in combat.
        """
        state = self._states.get(session_id)
        if state is None or not state.is_active:
            return ""

        combatant = state.get_combatant(avatar_id)
        if combatant is None:
            return ""

        return _actions_builder.build(
            avatar_name=avatar_name,
            budget=combatant.action_economy.get_budget(),
            conditions=combatant.conditions,
            concentration=combatant.concentration,
            spell_slots=combatant.spell_slots,
            spells_known=spells_known,
            equipment=equipment,
        )

    # ── Manual DM control ─────────────────────────────────────────────────

    def start_combat(
        self,
        session_id: int,
        combatants: list[dict],
    ) -> CombatState:
        """
        Manually start combat with a list of combatant dicts:
        [{"avatar_id": 1, "name": "Aldric", "initiative": 18, "hp_current": 40, "hp_max": 40, "is_enemy": False}]
        """
        state = self.get_or_create(session_id)
        entries = []
        for c in combatants:
            entry = CombatantEntry(
                avatar_id=c.get("avatar_id", 0),
                name=c.get("name", "Unknown"),
                initiative=c.get("initiative", 0),
                initiative_bonus=c.get("initiative_bonus", 0),
                is_avatar=not c.get("is_enemy", False),
                is_enemy=c.get("is_enemy", False),
                hp_current=c.get("hp_current", 10),
                hp_max=c.get("hp_max", 10),
            )
            # Initialise spell slots from dict if provided
            if c.get("spell_slots"):
                entry.spell_slots = SpellSlotTracker.from_dict(c["spell_slots"])
            entries.append(entry)
        state.start(entries)
        log.info("combat.started", session_id=session_id, combatants=len(entries))
        return state

    def end_combat(self, session_id: int) -> None:
        state = self._states.get(session_id)
        if state:
            state.end()
            log.info("combat.ended", session_id=session_id)

    def next_turn(self, session_id: int) -> CombatantEntry | None:
        state = self._states.get(session_id)
        if state and state.is_active:
            return state.next_turn()
        return None

    def set_initiative(self, session_id: int, avatar_id: int, initiative: int) -> bool:
        state = self.get_or_create(session_id)
        return state.set_initiative(avatar_id, initiative)

    def record_death_save(self, session_id: int, avatar_id: int, success: bool) -> str:
        state = self.get_or_create(session_id)
        return state.record_death_save(avatar_id, success)

    def deal_damage(self, session_id: int, avatar_id: int, damage: int) -> dict:
        state = self.get_or_create(session_id)
        return state.deal_damage(avatar_id, damage)

    def heal(self, session_id: int, avatar_id: int, hp: int) -> dict:
        state = self.get_or_create(session_id)
        return state.heal(avatar_id, hp)

    def add_condition(
        self,
        session_id: int,
        avatar_id: int,
        condition_name: str,
        source: str = "",
        duration_rounds: int = -1,
    ) -> bool:
        from app.rules.conditions import Condition
        state = self.get_or_create(session_id)
        c = state.get_combatant(avatar_id)
        if c is None:
            return False
        try:
            cond = Condition(condition_name.lower())
        except ValueError:
            return False
        c.conditions.add(cond, source=source, duration_rounds=duration_rounds)
        return True

    def remove_condition(self, session_id: int, avatar_id: int, condition_name: str) -> bool:
        from app.rules.conditions import Condition
        state = self._states.get(session_id)
        if not state:
            return False
        c = state.get_combatant(avatar_id)
        if c is None:
            return False
        try:
            cond = Condition(condition_name.lower())
        except ValueError:
            return False
        return c.conditions.remove(cond)

    def rest(self, session_id: int, avatar_id: int, rest_type: str) -> bool:
        """Apply short or long rest recovery."""
        state = self._states.get(session_id)
        if not state:
            return False
        c = state.get_combatant(avatar_id)
        if c is None:
            return False
        if rest_type == "long":
            c.spell_slots.long_rest()
            c.conditions.clear_all()
        elif rest_type == "short":
            c.spell_slots.short_rest()
        return True

    def get_combat_state_dict(self, session_id: int) -> dict:
        state = self._states.get(session_id)
        if state is None:
            return {"session_id": session_id, "phase": "inactive"}
        return state.to_dict()

    def stop_session(self, session_id: int) -> None:
        """Clean up when a session ends."""
        self._states.pop(session_id, None)


# Module-level singleton
combat_manager = CombatManager()
