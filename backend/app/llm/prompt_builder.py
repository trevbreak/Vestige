"""
Modular Prompt Builder.

Assembles the full system prompt for an avatar LLM call at runtime.
Each section is optional — missing data degrades gracefully.

Template structure (from plan.md §4.6):
  IDENTITY ANCHOR
  CHARACTER VOICE
  MECHANICAL STATE
  PARTY RELATIONSHIPS
  RELEVANT MEMORY       ← Phase 5 will fill this
  CURRENT SITUATION     ← last N transcript lines
  RESPONSE RULES

All sections are pure text manipulation — no I/O, fully testable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# ── Context-type → length instruction ────────────────────────────────────────

LENGTH_INSTRUCTIONS: dict[str, str] = {
    "combat_turn":     "1 sentence for your action, 1 optional flavour sentence. Be decisive.",
    "casual_roleplay": "1–2 sentences. Err short. React naturally.",
    "direct_question": "2–3 sentences. Answer directly, stay in character.",
    "party_debate":    "1–2 sentences. State your position briefly.",
    "emotional_beat":  "Up to 4 sentences if this moment truly warrants it. Otherwise stay brief.",
    "backstory_call":  "Up to 4 sentences. Speak carefully — this matters to your character.",
    "npc_social":      "2–3 sentences. Engage the NPC in character.",
    "moral_dilemma":   "2–3 sentences. Show the weight of the choice, don't resolve it easily.",
    "default":         "1–2 sentences. Err short.",
}


@dataclass
class AvatarContext:
    """
    All data the prompt builder needs to assemble one LLM call.

    Populate from the DB records + current pipeline state before
    calling PromptBuilder.build().
    """
    # Identity
    name: str
    race: str = "Human"
    char_class: str = "Fighter"
    level: int = 1
    alignment: str = ""
    background: str = ""
    player_name: str = ""

    # Personality
    personality_traits: str = ""
    ideals: str = ""
    bonds: str = ""
    flaws: str = ""

    # Voice config
    sentence_style: str = ""
    verbal_tics: str = ""
    never_say: str = ""

    # Mechanical state
    hit_points_current: int = 10
    hit_points_max: int = 10
    spell_slots: dict[str, Any] = field(default_factory=dict)
    equipment: list[str] = field(default_factory=list)
    active_conditions: list[str] = field(default_factory=list)

    # Relationships (avatar_name → short note)
    relationships: dict[str, str] = field(default_factory=dict)

    # Memory (retrieved Phase 5 chunks — plain strings)
    memory_chunks: list[str] = field(default_factory=list)

    # Recent transcript lines (list of "Speaker: text" strings)
    transcript_lines: list[str] = field(default_factory=list)

    # Call context
    context_type: str = "default"
    is_combat: bool = False

    # Phase 6: combat available actions block (plain text, injected during combat turns)
    available_actions_text: str = ""

    # Cross-avatar reference (25% chance injection — Phase 7)
    cross_avatar_note: str = ""


class PromptBuilder:
    """
    Stateless prompt assembler. Instantiate once, call build() per response.
    """

    def build(self, ctx: AvatarContext) -> tuple[str, str]:
        """
        Assemble the system prompt and user message for one LLM call.

        Returns (system_prompt, user_message).
        The user_message is the recent transcript with the final cue.
        """
        system = self._build_system(ctx)
        user = self._build_user(ctx)
        return system, user

    # ── System prompt sections ─────────────────────────────────────────────

    def _build_system(self, ctx: AvatarContext) -> str:
        sections = [
            self._identity_anchor(ctx),
            self._character_voice(ctx),
            self._mechanical_state(ctx),
            self._party_relationships(ctx),
            self._relevant_memory(ctx),
            self._available_actions(ctx),
            self._response_rules(ctx),
        ]
        return "\n\n".join(s for s in sections if s)

    def _identity_anchor(self, ctx: AvatarContext) -> str:
        lines = [
            f"You are {ctx.name}, a {ctx.race} {ctx.char_class} (Level {ctx.level}).",
            f"Your player ({ctx.player_name}) is absent tonight. Portray them faithfully.",
            "",
            "== IDENTITY ANCHOR ==",
        ]
        if ctx.alignment:
            lines.append(f"Alignment: {ctx.alignment}")
        if ctx.background:
            lines.append(f"Background: {ctx.background}")

        traits = []
        if ctx.personality_traits:
            traits.append(f"Personality: {ctx.personality_traits}")
        if ctx.ideals:
            traits.append(f"Ideals: {ctx.ideals}")
        if ctx.bonds:
            traits.append(f"Bonds: {ctx.bonds}")
        if ctx.flaws:
            traits.append(f"Flaws: {ctx.flaws}")
        lines.extend(traits)

        return "\n".join(lines)

    def _character_voice(self, ctx: AvatarContext) -> str:
        if not any([ctx.sentence_style, ctx.verbal_tics, ctx.never_say]):
            return ""
        lines = ["== CHARACTER VOICE =="]
        if ctx.sentence_style:
            lines.append(f"Sentence style: {ctx.sentence_style}")
        if ctx.verbal_tics:
            lines.append(f"Verbal habits: {ctx.verbal_tics}")
        if ctx.never_say:
            lines.append(f"Never say: {ctx.never_say}")
        return "\n".join(lines)

    def _mechanical_state(self, ctx: AvatarContext) -> str:
        lines = [
            "== MECHANICAL STATE ==",
            f"Current HP: {ctx.hit_points_current}/{ctx.hit_points_max}",
        ]
        if ctx.spell_slots:
            slot_str = ", ".join(
                f"Level {k}: {v}" for k, v in ctx.spell_slots.items() if v
            )
            if slot_str:
                lines.append(f"Spell slots remaining: {slot_str}")
        if ctx.active_conditions:
            lines.append(f"Active conditions: {', '.join(ctx.active_conditions)}")
        return "\n".join(lines)

    def _party_relationships(self, ctx: AvatarContext) -> str:
        if not ctx.relationships:
            return ""
        lines = ["== PARTY RELATIONSHIPS =="]
        for name, note in ctx.relationships.items():
            lines.append(f"{name}: {note}")
        if ctx.cross_avatar_note:
            lines.append(f"(recent) {ctx.cross_avatar_note}")
        return "\n".join(lines)

    def _relevant_memory(self, ctx: AvatarContext) -> str:
        if not ctx.memory_chunks:
            return ""
        lines = ["== RELEVANT MEMORY =="]
        for chunk in ctx.memory_chunks:
            lines.append(f"- {chunk}")
        return "\n".join(lines)

    def _available_actions(self, ctx: AvatarContext) -> str:
        """Phase 6: inject combat action block when in a combat turn."""
        if not ctx.available_actions_text:
            return ""
        return ctx.available_actions_text

    def _response_rules(self, ctx: AvatarContext) -> str:
        length_instr = LENGTH_INSTRUCTIONS.get(ctx.context_type, LENGTH_INSTRUCTIONS["default"])
        lines = [
            "== RESPONSE RULES (CRITICAL) ==",
            "Output ONLY your character's spoken words and/or one attempted action.",
            f"• Length: {length_instr}",
            "• Always first person: \"I reach for my sword\", NEVER \"" + ctx.name + " reaches...\"",
            "• No markdown. No asterisks. No parentheticals. Plain spoken text only.",
            "• No meta-game. Only know what your character would know.",
            "• NEVER narrate outcomes. That is the DM's job.",
            "• NEVER speak as another character or the DM.",
            "• Trailing off is allowed: \"I could try the door, or... hmm.\"",
            "• Reacting to a party member is allowed: \"—right, or we just burn it down.\"",
            "• Allowed emotion cues (prepend only, one max): [quietly] [urgently] [laughing] [tense] [whispering]",
            "",
            f"CONTEXT TYPE: {ctx.context_type}",
        ]
        return "\n".join(lines)

    # ── User message (the transcript cue) ─────────────────────────────────

    def _build_user(self, ctx: AvatarContext) -> str:
        if not ctx.transcript_lines:
            return f"[The table is quiet. Respond as {ctx.name} if appropriate.]"

        lines = ["== CURRENT SITUATION =="]
        lines.extend(ctx.transcript_lines[-30:])  # cap at 30 lines
        lines.append("")
        lines.append(f"[Respond now as {ctx.name}.]")
        return "\n".join(lines)


# Module-level singleton
prompt_builder = PromptBuilder()
