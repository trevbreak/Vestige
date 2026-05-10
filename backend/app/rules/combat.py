"""
Combat State Machine.

Tracks:
  - Initiative order (sorted list of combatants)
  - Current round and whose turn it is
  - Death saving throw state per avatar
  - Per-combatant action economy + conditions

The state is session-scoped and held in memory (not persisted to DB —
the transcript serves as the authoritative combat log).

Lifecycle:
  CombatState.start(combatants)
  loop:
    state.next_turn()   → CombatantEntry (whose turn it is)
    # actions happen, conditions/HP updated externally
    state.end_turn()
  state.end()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.rules.action_economy import ActionEconomyTracker
from app.rules.conditions import ConditionTracker, Condition
from app.rules.concentration import ConcentrationTracker
from app.rules.spell_slots import SpellSlotTracker


class CombatPhase(str, Enum):
    INACTIVE = "inactive"
    ROLLING  = "rolling"      # initiative being set
    ACTIVE   = "active"       # combat in progress
    ENDED    = "ended"


@dataclass
class DeathSaveState:
    """Tracks death saving throw progress for an avatar at 0 HP."""
    avatar_id: int
    successes: int = 0
    failures: int = 0
    is_stable: bool = False
    is_dead: bool = False

    def save_success(self) -> str:
        """Record a success. Returns 'stable' | 'ongoing'."""
        if self.is_stable or self.is_dead:
            return "stable" if self.is_stable else "dead"
        self.successes += 1
        if self.successes >= 3:
            self.is_stable = True
            return "stable"
        return "ongoing"

    def save_failure(self) -> str:
        """Record a failure. Returns 'dead' | 'ongoing'."""
        if self.is_stable or self.is_dead:
            return "stable" if self.is_stable else "dead"
        self.failures += 1
        if self.failures >= 3:
            self.is_dead = True
            return "dead"
        return "ongoing"

    def critical_hit(self) -> str:
        """Critical hit at 0 HP = 2 death save failures."""
        self.save_failure()
        return self.save_failure()

    def heal(self) -> None:
        """Healing at 0 HP resets death saves and brings avatar to 1 HP."""
        self.successes = 0
        self.failures = 0
        self.is_stable = False
        self.is_dead = False

    def to_dict(self) -> dict:
        return {
            "avatar_id": self.avatar_id,
            "successes": self.successes,
            "failures": self.failures,
            "is_stable": self.is_stable,
            "is_dead": self.is_dead,
        }


@dataclass
class CombatantEntry:
    """One participant in a combat encounter."""
    avatar_id: int          # 0 for NPCs/enemies
    name: str
    initiative: int = 0
    initiative_bonus: int = 0
    is_avatar: bool = True
    is_enemy: bool = False
    hp_current: int = 10
    hp_max: int = 10

    # Per-combatant rule trackers (populated on combat start)
    action_economy: ActionEconomyTracker = field(default_factory=lambda: ActionEconomyTracker(0))
    conditions: ConditionTracker = field(default_factory=lambda: ConditionTracker(0))
    concentration: ConcentrationTracker = field(default_factory=lambda: ConcentrationTracker(0))
    spell_slots: SpellSlotTracker = field(default_factory=SpellSlotTracker)

    @property
    def is_at_zero_hp(self) -> bool:
        return self.hp_current <= 0

    @property
    def is_incapacitated(self) -> bool:
        return self.conditions.is_incapacitated

    def to_dict(self) -> dict:
        return {
            "avatar_id": self.avatar_id,
            "name": self.name,
            "initiative": self.initiative,
            "is_avatar": self.is_avatar,
            "is_enemy": self.is_enemy,
            "hp_current": self.hp_current,
            "hp_max": self.hp_max,
            "conditions": self.conditions.active_conditions,
            "concentration": self.concentration.to_dict(),
            "action_budget": self.action_economy.get_budget().to_dict(),
            "at_zero_hp": self.is_at_zero_hp,
        }


class CombatState:
    """
    Session-scoped combat state machine.

    One instance per session, stored in CombatManager.
    """

    def __init__(self, session_id: int):
        self.session_id = session_id
        self.phase: CombatPhase = CombatPhase.INACTIVE
        self.round: int = 0
        self._combatants: list[CombatantEntry] = []
        self._turn_index: int = 0
        self._death_saves: dict[int, DeathSaveState] = {}

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self, combatants: list[CombatantEntry]) -> None:
        """Begin combat with the given combatants (already sorted by initiative)."""
        self._combatants = sorted(
            combatants, key=lambda c: (-c.initiative, c.initiative_bonus)
        )
        # Wire tracker IDs
        for c in self._combatants:
            c.action_economy = ActionEconomyTracker(c.avatar_id, speed=c.hp_max)
            c.conditions = ConditionTracker(c.avatar_id)
            c.concentration = ConcentrationTracker(c.avatar_id)
        self._turn_index = 0
        self.round = 1
        self.phase = CombatPhase.ACTIVE
        self._death_saves = {}
        # Start first turn
        if self._combatants:
            self._combatants[0].action_economy.start_turn()

    def end(self) -> None:
        """End combat. Clears all state."""
        self.phase = CombatPhase.ENDED
        self._combatants = []
        self._death_saves = {}
        self.round = 0

    # ── Turn management ────────────────────────────────────────────────────

    @property
    def current_combatant(self) -> CombatantEntry | None:
        if not self._combatants or self.phase != CombatPhase.ACTIVE:
            return None
        return self._combatants[self._turn_index % len(self._combatants)]

    def next_turn(self) -> CombatantEntry | None:
        """
        Advance to the next combatant's turn.
        Skips dead/unconscious/incapacitated combatants.
        Increments round counter when the full order wraps.
        Returns the CombatantEntry whose turn it now is.
        """
        if self.phase != CombatPhase.ACTIVE or not self._combatants:
            return None

        # End current turn
        current = self._combatants[self._turn_index % len(self._combatants)]
        current.action_economy.end_turn()

        # Tick conditions on round boundary (when index wraps)
        next_idx = (self._turn_index + 1) % len(self._combatants)
        if next_idx == 0:
            self.round += 1
            for c in self._combatants:
                expired = c.conditions.tick()
                # Break concentration on expired conditions if relevant
                if any(cond in expired for cond in [Condition.STUNNED, Condition.PARALYZED]):
                    pass  # already removed from conditions

        # Find next combatant who can act (skip dead)
        n = len(self._combatants)
        for _ in range(n):
            self._turn_index = (self._turn_index + 1) % n
            candidate = self._combatants[self._turn_index]
            if not candidate.is_at_zero_hp or candidate.conditions.has(Condition.UNCONSCIOUS) is False:
                break

        next_combatant = self._combatants[self._turn_index]
        next_combatant.action_economy.start_turn()
        return next_combatant

    def end_turn(self) -> None:
        """Signal current combatant's turn is done (alias for next_turn initiation)."""
        pass  # Callers use next_turn() to advance

    # ── Combatant management ───────────────────────────────────────────────

    def add_combatant(self, combatant: CombatantEntry) -> None:
        """Add a late-joining combatant at the correct initiative position."""
        self._combatants.append(combatant)
        self._combatants.sort(key=lambda c: (-c.initiative, c.initiative_bonus))

    def remove_combatant(self, avatar_id: int) -> bool:
        before = len(self._combatants)
        self._combatants = [c for c in self._combatants if c.avatar_id != avatar_id]
        # Adjust turn index if needed
        if self._turn_index >= len(self._combatants):
            self._turn_index = 0
        return len(self._combatants) < before

    def get_combatant(self, avatar_id: int) -> CombatantEntry | None:
        return next((c for c in self._combatants if c.avatar_id == avatar_id), None)

    def set_initiative(self, avatar_id: int, initiative: int) -> bool:
        c = self.get_combatant(avatar_id)
        if c is None:
            return False
        c.initiative = initiative
        self._combatants.sort(key=lambda x: (-x.initiative, x.initiative_bonus))
        return True

    # ── Death saving throws ────────────────────────────────────────────────

    def get_death_saves(self, avatar_id: int) -> DeathSaveState:
        if avatar_id not in self._death_saves:
            self._death_saves[avatar_id] = DeathSaveState(avatar_id=avatar_id)
        return self._death_saves[avatar_id]

    def record_death_save(self, avatar_id: int, success: bool) -> str:
        """Record a death save. Returns 'stable' | 'dead' | 'ongoing'."""
        saves = self.get_death_saves(avatar_id)
        result = saves.save_success() if success else saves.save_failure()
        # If dead, mark the combatant condition
        if result == "dead":
            c = self.get_combatant(avatar_id)
            if c:
                c.conditions.add(Condition.UNCONSCIOUS, source="death")
        return result

    def deal_damage(self, avatar_id: int, damage: int) -> dict[str, Any]:
        """
        Apply damage to a combatant. Handles:
          - HP reduction
          - Going to 0 HP
          - Instant death (damage > max HP while at 0)
          - Concentration checks
        Returns a dict describing what happened.
        """
        c = self.get_combatant(avatar_id)
        if c is None:
            return {"error": "combatant not found"}

        result: dict[str, Any] = {"avatar_id": avatar_id, "damage": damage}

        was_at_zero = c.is_at_zero_hp
        c.hp_current = max(0, c.hp_current - damage)
        result["hp_current"] = c.hp_current

        # Concentration check if was concentrating
        if c.concentration.is_concentrating:
            dc = max(10, damage // 2)
            c.concentration.check_concentration(damage)
            result["concentration_check_dc"] = dc
            result["concentration_spell"] = c.concentration.current_spell

        # Instant death: damage exceeds remaining HP and equals or exceeds max HP
        if c.hp_current == 0 and damage >= c.hp_max and not was_at_zero:
            c.conditions.add(Condition.UNCONSCIOUS, source="instant death")
            result["instant_death"] = True
            saves = self.get_death_saves(avatar_id)
            saves.is_dead = True
            result["outcome"] = "dead"
        elif c.hp_current == 0 and not was_at_zero:
            c.conditions.add(Condition.UNCONSCIOUS, source="0 HP")
            result["outcome"] = "down"
        elif c.hp_current == 0 and was_at_zero:
            # Damage while at 0 = critical death save failure (2 failures)
            saves = self.get_death_saves(avatar_id)
            saves.critical_hit()
            result["outcome"] = "death_save_failed" if not saves.is_dead else "dead"
        else:
            result["outcome"] = "damaged"

        return result

    def heal(self, avatar_id: int, hp: int) -> dict[str, Any]:
        c = self.get_combatant(avatar_id)
        if c is None:
            return {"error": "combatant not found"}
        was_down = c.is_at_zero_hp
        c.hp_current = min(c.hp_max, c.hp_current + hp)
        if was_down and c.hp_current > 0:
            c.conditions.remove(Condition.UNCONSCIOUS)
            if c.avatar_id in self._death_saves:
                self._death_saves[c.avatar_id].heal()
        return {"avatar_id": avatar_id, "hp_current": c.hp_current, "healed": hp}

    # ── State query ────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return self.phase == CombatPhase.ACTIVE

    @property
    def initiative_order(self) -> list[CombatantEntry]:
        return list(self._combatants)

    def to_dict(self) -> dict:
        current = self.current_combatant
        return {
            "session_id": self.session_id,
            "phase": self.phase.value,
            "round": self.round,
            "current_turn": current.name if current else None,
            "current_avatar_id": current.avatar_id if current else None,
            "initiative_order": [c.to_dict() for c in self._combatants],
            "death_saves": {
                str(aid): ds.to_dict()
                for aid, ds in self._death_saves.items()
            },
        }
