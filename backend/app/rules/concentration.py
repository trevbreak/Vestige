"""
D&D 5e Concentration Tracker.

Rules (PHB p.203):
  - Only one concentration spell active at a time.
  - Starting a new concentration spell ends the previous one.
  - Taking damage requires a Constitution saving throw (DC = max(10, damage/2)).
  - Incapacitation or death ends concentration automatically.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConcentrationSpell:
    spell_name: str
    caster_avatar_id: int
    duration_rounds: int = -1       # -1 = indefinite
    rounds_remaining: int = -1
    save_dc: int = 10               # DC for concentration checks


class ConcentrationTracker:
    """
    Per-avatar concentration tracker.

    Usage:
        tracker = ConcentrationTracker(avatar_id=1)
        tracker.start("Bless", duration_rounds=10)
        broken = tracker.take_damage(18)   # rolls implied — returns whether broken
        tracker.tick()
        tracker.end()
    """

    def __init__(self, avatar_id: int):
        self.avatar_id = avatar_id
        self._active: ConcentrationSpell | None = None

    # ── State changes ──────────────────────────────────────────────────────

    def start(
        self,
        spell_name: str,
        duration_rounds: int = -1,
    ) -> str | None:
        """
        Begin concentrating on a spell.
        If another spell was active, it ends — returns its name.
        Returns None if no prior spell.
        """
        prior = self._active.spell_name if self._active else None
        self._active = ConcentrationSpell(
            spell_name=spell_name,
            caster_avatar_id=self.avatar_id,
            duration_rounds=duration_rounds,
            rounds_remaining=duration_rounds,
        )
        return prior

    def end(self) -> str | None:
        """Voluntarily end concentration. Returns spell name or None."""
        if self._active is None:
            return None
        name = self._active.spell_name
        self._active = None
        return name

    def break_on_incapacitation(self) -> bool:
        """Call when avatar becomes incapacitated/unconscious. Breaks concentration."""
        if self._active:
            self._active = None
            return True
        return False

    def check_concentration(self, damage_taken: int, constitution_modifier: int = 0) -> bool:
        """
        Simulate a concentration check after taking damage.
        DC = max(10, damage / 2).
        Returns True if concentration holds (i.e., would need to roll ≥ DC).

        NOTE: This does NOT roll dice — it returns the DC so the caller/LLM
        knows what check is required. The combat log should narrate the roll.
        Returns the DC as an integer attribute instead; use get_concentration_dc().
        """
        if self._active is None:
            return True  # nothing to break
        dc = max(10, damage_taken // 2)
        self._active.save_dc = dc
        # We do NOT auto-break here — the caller decides based on the roll outcome
        return True

    def force_break(self) -> str | None:
        """Unconditionally break concentration (e.g. failed save). Returns spell name."""
        return self.end()

    def tick(self) -> bool:
        """
        Advance one round. Returns True if spell expired naturally.
        """
        if self._active is None:
            return False
        if self._active.rounds_remaining > 0:
            self._active.rounds_remaining -= 1
            if self._active.rounds_remaining == 0:
                self._active = None
                return True
        return False

    # ── Query ──────────────────────────────────────────────────────────────

    @property
    def is_concentrating(self) -> bool:
        return self._active is not None

    @property
    def current_spell(self) -> str | None:
        return self._active.spell_name if self._active else None

    @property
    def rounds_remaining(self) -> int:
        if self._active is None:
            return 0
        return self._active.rounds_remaining

    def get_concentration_dc(self) -> int:
        """Return the last computed concentration check DC."""
        if self._active is None:
            return 0
        return self._active.save_dc

    def to_dict(self) -> dict:
        if self._active is None:
            return {"concentrating": False}
        return {
            "concentrating": True,
            "spell": self._active.spell_name,
            "rounds_remaining": self._active.rounds_remaining,
            "save_dc": self._active.save_dc,
        }
