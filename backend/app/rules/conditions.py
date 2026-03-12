"""
D&D 5e Condition Tracker.

Implements the 14 standard 5e conditions plus exhaustion levels.
Each condition carries its mechanical effects as a dict so the LLM and
available-actions builder can reference them.

Reference: PHB pp. 290-292
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Condition(str, Enum):
    BLINDED       = "blinded"
    CHARMED       = "charmed"
    DEAFENED      = "deafened"
    EXHAUSTION    = "exhaustion"   # tracked by level 1-6 separately
    FRIGHTENED    = "frightened"
    GRAPPLED      = "grappled"
    INCAPACITATED = "incapacitated"
    INVISIBLE     = "invisible"
    PARALYZED     = "paralyzed"
    PETRIFIED     = "petrified"
    POISONED      = "poisoned"
    PRONE         = "prone"
    RESTRAINED    = "restrained"
    STUNNED       = "stunned"
    UNCONSCIOUS   = "unconscious"


# ── Effect descriptions (for LLM prompt injection) ────────────────────────────

CONDITION_EFFECTS: dict[Condition, dict[str, Any]] = {
    Condition.BLINDED: {
        "summary": "Can't see; attack rolls against you have advantage; your attacks have disadvantage.",
        "blocks_action": False,
        "blocks_movement": False,
    },
    Condition.CHARMED: {
        "summary": "Can't attack charmer; charmer has advantage on social checks against you.",
        "blocks_action": False,
        "blocks_movement": False,
    },
    Condition.DEAFENED: {
        "summary": "Can't hear; automatically fail hearing checks.",
        "blocks_action": False,
        "blocks_movement": False,
    },
    Condition.EXHAUSTION: {
        "summary": "Levels 1-5 impose cumulative penalties; level 6 = death.",
        "blocks_action": False,
        "blocks_movement": False,
    },
    Condition.FRIGHTENED: {
        "summary": "Disadvantage on ability checks and attacks while source is visible; can't move closer to source.",
        "blocks_action": False,
        "blocks_movement": False,  # partial — can't move toward source
    },
    Condition.GRAPPLED: {
        "summary": "Speed reduced to 0.",
        "blocks_action": False,
        "blocks_movement": True,
    },
    Condition.INCAPACITATED: {
        "summary": "Can't take actions or reactions.",
        "blocks_action": True,
        "blocks_movement": False,
    },
    Condition.INVISIBLE: {
        "summary": "Unseen; attacks against you have disadvantage; your attacks have advantage.",
        "blocks_action": False,
        "blocks_movement": False,
    },
    Condition.PARALYZED: {
        "summary": "Incapacitated; can't move or speak; auto-fail Str/Dex saves; attacks have advantage; hits within 5ft are crits.",
        "blocks_action": True,
        "blocks_movement": True,
    },
    Condition.PETRIFIED: {
        "summary": "Transformed to stone; incapacitated; resistant to all damage; immune to poison/disease.",
        "blocks_action": True,
        "blocks_movement": True,
    },
    Condition.POISONED: {
        "summary": "Disadvantage on attack rolls and ability checks.",
        "blocks_action": False,
        "blocks_movement": False,
    },
    Condition.PRONE: {
        "summary": "Disadvantage on attacks; attacks from >5ft have disadvantage against you; attacks from ≤5ft have advantage against you.",
        "blocks_action": False,
        "blocks_movement": False,
    },
    Condition.RESTRAINED: {
        "summary": "Speed 0; attack rolls against you have advantage; your attack rolls have disadvantage; disadvantage on Dex saves.",
        "blocks_action": False,
        "blocks_movement": True,
    },
    Condition.STUNNED: {
        "summary": "Incapacitated; can't move; can only speak falteringly; auto-fail Str/Dex saves; attacks against you have advantage.",
        "blocks_action": True,
        "blocks_movement": True,
    },
    Condition.UNCONSCIOUS: {
        "summary": "Incapacitated; can't move or speak; unaware of surroundings; auto-fail Str/Dex saves; attacks have advantage; hits within 5ft are crits.",
        "blocks_action": True,
        "blocks_movement": True,
    },
}

# Conditions that imply INCAPACITATED (can't take actions/reactions)
INCAPACITATING_CONDITIONS = frozenset({
    Condition.INCAPACITATED,
    Condition.PARALYZED,
    Condition.PETRIFIED,
    Condition.STUNNED,
    Condition.UNCONSCIOUS,
})


@dataclass
class ConditionEntry:
    condition: Condition
    source: str = ""          # what caused it ("goblin shaman", "Banishment spell")
    duration_rounds: int = -1  # -1 = indefinite
    rounds_remaining: int = -1


class ConditionTracker:
    """
    Per-avatar condition tracker.

    Usage:
        tracker = ConditionTracker(avatar_id=1)
        tracker.add(Condition.POISONED, source="spider bite", duration_rounds=3)
        tracker.tick()   # called each round
        active = tracker.active_conditions
    """

    def __init__(self, avatar_id: int):
        self.avatar_id = avatar_id
        self._conditions: dict[Condition, ConditionEntry] = {}
        self._exhaustion_level: int = 0

    # ── Mutation ───────────────────────────────────────────────────────────

    def add(
        self,
        condition: Condition,
        source: str = "",
        duration_rounds: int = -1,
    ) -> None:
        """Add a condition. Idempotent — re-adding refreshes the duration."""
        entry = ConditionEntry(
            condition=condition,
            source=source,
            duration_rounds=duration_rounds,
            rounds_remaining=duration_rounds,
        )
        self._conditions[condition] = entry

    def remove(self, condition: Condition) -> bool:
        """Remove a condition. Returns True if it was present."""
        if condition in self._conditions:
            del self._conditions[condition]
            return True
        return False

    def add_exhaustion(self, levels: int = 1) -> int:
        """Add exhaustion levels. Returns new level (max 6)."""
        self._exhaustion_level = min(6, self._exhaustion_level + levels)
        if self._exhaustion_level >= 6:
            # Level 6 = death — set unconscious
            self.add(Condition.UNCONSCIOUS, source="exhaustion level 6")
        return self._exhaustion_level

    def remove_exhaustion(self, levels: int = 1) -> int:
        """Remove exhaustion levels. Returns new level."""
        self._exhaustion_level = max(0, self._exhaustion_level - levels)
        return self._exhaustion_level

    def tick(self) -> list[Condition]:
        """
        Advance one round. Remove expired timed conditions.
        Returns list of conditions that expired.
        """
        expired = []
        for cond, entry in list(self._conditions.items()):
            if entry.rounds_remaining > 0:
                entry.rounds_remaining -= 1
                if entry.rounds_remaining == 0:
                    del self._conditions[cond]
                    expired.append(cond)
        return expired

    def clear_all(self) -> None:
        """Remove all conditions and reset exhaustion."""
        self._conditions.clear()
        self._exhaustion_level = 0

    # ── State query ────────────────────────────────────────────────────────

    def has(self, condition: Condition) -> bool:
        return condition in self._conditions

    @property
    def is_incapacitated(self) -> bool:
        return bool(self._conditions.keys() & INCAPACITATING_CONDITIONS)

    @property
    def can_move(self) -> bool:
        for cond, effects in CONDITION_EFFECTS.items():
            if cond in self._conditions and effects.get("blocks_movement"):
                return False
        return True

    @property
    def active_conditions(self) -> list[str]:
        """Return condition names as strings, suitable for AvatarContext."""
        names = [c.value for c in self._conditions]
        if self._exhaustion_level > 0:
            names.append(f"exhaustion (level {self._exhaustion_level})")
        return names

    @property
    def exhaustion_level(self) -> int:
        return self._exhaustion_level

    def to_dict(self) -> dict:
        return {
            "conditions": [
                {
                    "name": e.condition.value,
                    "source": e.source,
                    "rounds_remaining": e.rounds_remaining,
                }
                for e in self._conditions.values()
            ],
            "exhaustion_level": self._exhaustion_level,
        }
