"""
D&D 5e Spell Slot Tracker.

Tracks available spell slots per level (1-9).
Supports:
  - Use a slot (any level)
  - Short rest recovery (Warlock pact slots, if applicable)
  - Long rest recovery (all slots)
  - Slot upcast (use higher level than minimum)

Slot data stored as dict: {"1": {"max": N, "used": M}, ...}
Compatible with Avatar.spell_slots JSON field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SlotLevel:
    level: int
    max_slots: int
    used_slots: int

    @property
    def remaining(self) -> int:
        return max(0, self.max_slots - self.used_slots)

    @property
    def is_exhausted(self) -> bool:
        return self.remaining == 0


class SpellSlotTracker:
    """
    Spell slot manager for one avatar.

    Usage:
        tracker = SpellSlotTracker.from_dict(avatar.spell_slots)
        ok = tracker.use(level=3)
        tracker.long_rest()
        data = tracker.to_dict()   # save back to avatar.spell_slots
    """

    def __init__(self, slots: dict[int, SlotLevel] | None = None):
        self._slots: dict[int, SlotLevel] = slots or {}

    # ── Factory ────────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SpellSlotTracker":
        """
        Build from Avatar.spell_slots JSON.
        Accepts both:
          {"1": {"max": 4, "used": 1}, "2": {"max": 3, "used": 0}}
          {"1": 4, "2": 3}  (legacy — treats value as max, 0 used)
        """
        if not data:
            return cls()
        slots: dict[int, SlotLevel] = {}
        for key, value in data.items():
            try:
                level = int(key)
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict):
                max_s = int(value.get("max", 0))
                used_s = int(value.get("used", 0))
            elif isinstance(value, int):
                max_s = value
                used_s = 0
            else:
                continue
            if max_s > 0:
                slots[level] = SlotLevel(level=level, max_slots=max_s, used_slots=used_s)
        return cls(slots)

    @classmethod
    def from_class_level(cls, char_class: str, level: int) -> "SpellSlotTracker":
        """
        Build a fresh tracker from standard 5e slot progression for common classes.
        Covers full casters (Wizard, Sorcerer, Cleric, Druid, Bard) and
        half-casters (Paladin, Ranger at level 2+).
        """
        table = _FULL_CASTER_SLOTS if char_class.lower() in _FULL_CASTERS else \
                _HALF_CASTER_SLOTS if char_class.lower() in _HALF_CASTERS else {}
        slot_counts = table.get(min(level, 20), {})
        slots = {
            lvl: SlotLevel(level=lvl, max_slots=count, used_slots=0)
            for lvl, count in slot_counts.items()
            if count > 0
        }
        return cls(slots)

    # ── Slot use ───────────────────────────────────────────────────────────

    def use(self, level: int) -> bool:
        """
        Expend one spell slot of the given level.
        Returns True if successful, False if no slots remain at that level.
        """
        slot = self._slots.get(level)
        if slot is None or slot.remaining == 0:
            return False
        slot.used_slots += 1
        return True

    def use_lowest_available(self, minimum_level: int = 1) -> int | None:
        """
        Expend the lowest available slot at or above minimum_level.
        Returns the level used, or None if none available.
        """
        for lvl in sorted(self._slots.keys()):
            if lvl >= minimum_level and self._slots[lvl].remaining > 0:
                self._slots[lvl].used_slots += 1
                return lvl
        return None

    # ── Rest recovery ──────────────────────────────────────────────────────

    def long_rest(self) -> None:
        """Full recovery — all slots restored."""
        for slot in self._slots.values():
            slot.used_slots = 0

    def short_rest(self, warlock_slots: int = 0) -> None:
        """
        Short rest recovery.
        Warlocks recover all pact slots on a short rest.
        Pass warlock_slots > 0 to indicate how many pact slot levels to restore.
        (Standard casters recover nothing on a short rest.)
        """
        if warlock_slots > 0:
            # Warlock pact slots are all at the same level — restore them
            for slot in self._slots.values():
                slot.used_slots = max(0, slot.used_slots - warlock_slots)

    # ── State query ────────────────────────────────────────────────────────

    def remaining(self, level: int) -> int:
        slot = self._slots.get(level)
        return slot.remaining if slot else 0

    def has_any(self, minimum_level: int = 1) -> bool:
        return any(
            s.remaining > 0 for lvl, s in self._slots.items() if lvl >= minimum_level
        )

    def summary_string(self) -> str:
        """Human-readable summary for LLM prompt injection."""
        parts = []
        for lvl in sorted(self._slots.keys()):
            s = self._slots[lvl]
            if s.max_slots > 0:
                parts.append(f"L{lvl}: {s.remaining}/{s.max_slots}")
        return ", ".join(parts) if parts else "none"

    def to_dict(self) -> dict[str, dict[str, int]]:
        """Serialise back to Avatar.spell_slots format."""
        return {
            str(lvl): {"max": s.max_slots, "used": s.used_slots}
            for lvl, s in sorted(self._slots.items())
        }

    def all_levels(self) -> list[SlotLevel]:
        return [self._slots[lvl] for lvl in sorted(self._slots.keys())]


# ── Standard slot progression tables ──────────────────────────────────────────

_FULL_CASTERS = {"wizard", "sorcerer", "cleric", "druid", "bard"}
_HALF_CASTERS = {"paladin", "ranger"}

# {character_level: {slot_level: count}}
_FULL_CASTER_SLOTS: dict[int, dict[int, int]] = {
    1:  {1: 2},
    2:  {1: 3},
    3:  {1: 4, 2: 2},
    4:  {1: 4, 2: 3},
    5:  {1: 4, 2: 3, 3: 2},
    6:  {1: 4, 2: 3, 3: 3},
    7:  {1: 4, 2: 3, 3: 3, 4: 1},
    8:  {1: 4, 2: 3, 3: 3, 4: 2},
    9:  {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},
    10: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},
    11: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
    12: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
    13: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
    14: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
    15: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},
    16: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},
    17: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1, 9: 1},
    18: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1},
    19: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 1, 8: 1, 9: 1},
    20: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1},
}

_HALF_CASTER_SLOTS: dict[int, dict[int, int]] = {
    1:  {},
    2:  {1: 2},
    3:  {1: 3},
    4:  {1: 3},
    5:  {1: 4, 2: 2},
    6:  {1: 4, 2: 2},
    7:  {1: 4, 2: 3},
    8:  {1: 4, 2: 3},
    9:  {1: 4, 2: 3, 3: 2},
    10: {1: 4, 2: 3, 3: 2},
    11: {1: 4, 2: 3, 3: 3},
    12: {1: 4, 2: 3, 3: 3},
    13: {1: 4, 2: 3, 3: 3, 4: 1},
    14: {1: 4, 2: 3, 3: 3, 4: 1},
    15: {1: 4, 2: 3, 3: 3, 4: 2},
    16: {1: 4, 2: 3, 3: 3, 4: 2},
    17: {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},
    18: {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},
    19: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},
    20: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},
}
