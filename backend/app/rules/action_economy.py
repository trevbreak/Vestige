"""
D&D 5e Action Economy Tracker.

Tracks per-turn resource usage for a single avatar:
  Action, Bonus Action, Reaction, Movement (feet)

Reset on start of each new turn.
Reaction resets at start of the avatar's NEXT turn (not immediately).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ActionBudget:
    """Snapshot of remaining actions for one combatant in one turn."""
    action: bool = True           # standard action available
    bonus_action: bool = True     # bonus action available
    reaction: bool = True         # reaction available
    movement_remaining: int = 30  # feet remaining this turn
    movement_total: int = 30      # base speed (from avatar)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "bonus_action": self.bonus_action,
            "reaction": self.reaction,
            "movement_remaining": self.movement_remaining,
            "movement_total": self.movement_total,
        }


class ActionEconomyTracker:
    """
    Per-combatant action economy manager.

    Usage:
        tracker = ActionEconomyTracker(avatar_id=1, speed=30)
        tracker.start_turn()           # reset action + bonus + movement
        tracker.use_action()
        tracker.use_bonus_action()
        tracker.move(15)
        budget = tracker.get_budget()
        tracker.end_turn()             # marks reaction as refreshed next turn
    """

    def __init__(self, avatar_id: int, speed: int = 30):
        self.avatar_id = avatar_id
        self._speed = speed
        self._action = True
        self._bonus_action = True
        self._reaction = True
        self._movement_remaining = speed
        self._reaction_pending_refresh = False

    # ── Turn lifecycle ─────────────────────────────────────────────────────

    def start_turn(self) -> None:
        """Called at the start of this avatar's combat turn."""
        self._action = True
        self._bonus_action = True
        self._movement_remaining = self._speed
        # Reaction refreshes at start of own turn
        if self._reaction_pending_refresh:
            self._reaction = True
            self._reaction_pending_refresh = False
        else:
            self._reaction = True  # also reset if not pending

    def end_turn(self) -> None:
        """Called at the end of this avatar's combat turn."""
        # Mark reaction to refresh next turn (already reset in start_turn)
        pass  # reaction resets at start_turn — nothing needed here

    # ── Resource consumption ───────────────────────────────────────────────

    def use_action(self) -> bool:
        """Consume the standard action. Returns True if successful."""
        if not self._action:
            return False
        self._action = False
        return True

    def use_bonus_action(self) -> bool:
        """Consume the bonus action. Returns True if successful."""
        if not self._bonus_action:
            return False
        self._bonus_action = False
        return True

    def use_reaction(self) -> bool:
        """Consume the reaction. Returns True if successful."""
        if not self._reaction:
            return False
        self._reaction = False
        return True

    def move(self, feet: int) -> int:
        """
        Consume movement. Returns feet actually moved (capped at remaining).
        """
        actual = min(feet, self._movement_remaining)
        self._movement_remaining -= actual
        return actual

    def set_speed(self, speed: int) -> None:
        """Update base speed (e.g. after Haste or Slow)."""
        self._speed = max(0, speed)

    # ── State query ────────────────────────────────────────────────────────

    def get_budget(self) -> ActionBudget:
        return ActionBudget(
            action=self._action,
            bonus_action=self._bonus_action,
            reaction=self._reaction,
            movement_remaining=self._movement_remaining,
            movement_total=self._speed,
        )

    @property
    def can_act(self) -> bool:
        """False if avatar cannot take actions (incapacitated, etc.)."""
        return self._action
