"""
Available Actions Builder.

Assembles a structured JSON description of what a specific avatar CAN do
on their current combat turn, fed directly into the LLM system prompt.

This tells the avatar (via the LLM):
  - Whether they have their Action / Bonus Action / Reaction
  - How much movement they have left
  - Which spell slots are available
  - Whether they are concentrating on something
  - Which conditions affect them
  - General action options (Attack, Cast a Spell, Dash, Disengage, Dodge, Help, Hide, Ready, Search, Use Object)

The output is a plain-text block rather than raw JSON so it reads naturally in a prompt.
"""

from __future__ import annotations

from typing import Any

from app.rules.action_economy import ActionBudget
from app.rules.conditions import ConditionTracker, INCAPACITATING_CONDITIONS
from app.rules.concentration import ConcentrationTracker
from app.rules.spell_slots import SpellSlotTracker


# Standard actions available to any 5e character (PHB p.192)
STANDARD_ACTIONS = [
    "Attack (weapon or unarmed)",
    "Cast a Spell",
    "Dash (double movement)",
    "Disengage (movement doesn't provoke opportunity attacks)",
    "Dodge (attacks against you have disadvantage; advantage on Dex saves)",
    "Help (give ally advantage on next check or attack)",
    "Hide",
    "Ready (prepare a reaction to a trigger)",
    "Search",
    "Use an Object / Item",
]

BONUS_ACTIONS_GENERIC = [
    "Offhand Attack (if wielding a light weapon in off-hand)",
    "Use a class feature that requires a Bonus Action",
    "Cast a spell with a Bonus Action casting time",
    "Disengage or Dash (Rogue: Cunning Action)",
]

REACTIONS_GENERIC = [
    "Opportunity Attack (enemy leaves your reach)",
    "Cast a spell with a Reaction casting time",
    "Use a class feature that triggers as a Reaction",
]


class AvailableActionsBuilder:
    """
    Builds a plain-text actions block for a single combatant on their turn.
    """

    def build(
        self,
        *,
        avatar_name: str,
        budget: ActionBudget,
        conditions: ConditionTracker,
        concentration: ConcentrationTracker,
        spell_slots: SpellSlotTracker,
        spells_known: list[str] | None = None,
        equipment: list[str] | None = None,
    ) -> str:
        """
        Returns a formatted text block describing available actions.
        Returns a short "incapacitated" notice if the avatar cannot act.
        """
        if conditions.is_incapacitated:
            active = conditions.active_conditions
            return (
                f"== {avatar_name.upper()}'S TURN ==\n"
                f"INCAPACITATED — cannot take actions or reactions.\n"
                f"Active conditions: {', '.join(active)}"
            )

        lines = [f"== {avatar_name.upper()}'S AVAILABLE ACTIONS =="]

        # Action economy
        lines.append(f"\nRESOURCES:")
        lines.append(f"  Action:       {'✓ available' if budget.action else '✗ used'}")
        lines.append(f"  Bonus Action: {'✓ available' if budget.bonus_action else '✗ used'}")
        lines.append(f"  Reaction:     {'✓ available' if budget.reaction else '✗ used'}")
        lines.append(f"  Movement:     {budget.movement_remaining}/{budget.movement_total} ft remaining")

        # Spell slots
        slot_summary = spell_slots.summary_string()
        if slot_summary != "none":
            lines.append(f"  Spell Slots:  {slot_summary}")

        # Concentration
        if concentration.is_concentrating:
            lines.append(f"  Concentrating on: {concentration.current_spell}")

        # Conditions
        active_conds = conditions.active_conditions
        if active_conds:
            lines.append(f"\nACTIVE CONDITIONS: {', '.join(active_conds)}")

        # Actions available
        if budget.action:
            lines.append("\nACTIONS (choose one):")
            for a in STANDARD_ACTIONS:
                lines.append(f"  • {a}")
            # Add known spells if any
            if spells_known:
                lines.append(f"  • Specific spells available: {', '.join(spells_known[:10])}")

        # Bonus actions
        if budget.bonus_action:
            lines.append("\nBONUS ACTION OPTIONS:")
            for b in BONUS_ACTIONS_GENERIC:
                lines.append(f"  • {b}")

        # Reactions
        if budget.reaction:
            lines.append("\nREACTION OPTIONS:")
            for r in REACTIONS_GENERIC:
                lines.append(f"  • {r}")

        # Equipment hint
        if equipment:
            lines.append(f"\nEQUIPMENT: {', '.join(equipment[:8])}")

        lines.append("\nDecide your action, then speak it in character.")
        return "\n".join(lines)

    def build_compact(
        self,
        *,
        budget: ActionBudget,
        conditions: ConditionTracker,
        concentration: ConcentrationTracker,
        spell_slots: SpellSlotTracker,
    ) -> dict[str, Any]:
        """
        Returns a compact dict for programmatic use (API responses, tests).
        """
        return {
            "incapacitated": conditions.is_incapacitated,
            "action": budget.action,
            "bonus_action": budget.bonus_action,
            "reaction": budget.reaction,
            "movement_remaining": budget.movement_remaining,
            "movement_total": budget.movement_total,
            "spell_slots": spell_slots.to_dict(),
            "concentrating": concentration.is_concentrating,
            "concentration_spell": concentration.current_spell,
            "conditions": conditions.active_conditions,
        }


# Module-level singleton
available_actions_builder = AvailableActionsBuilder()
