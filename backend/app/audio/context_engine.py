"""
Context Engine.

Decides when and whether an avatar should respond to a transcript utterance.

Decision flow:
  1. Interrupt confidence scoring
  2. Additional trigger checks (recent name mention, combat, silence gap)
  3. Suppression checks (AEC, human speaking, avatar cooldown, DM hotword)
  4. Context type classification → routing hint
  5. Response queue priority assignment
"""

from __future__ import annotations

import time
import re
from dataclasses import dataclass, field
from app.config import get_settings
from app.prompts.loader import prompt_loader

# ── Context type → routing + max sentence length ─────────────────────────────
CONTEXT_TYPES: dict[str, dict] = {
    "combat_turn":     {"max_sentences": 2, "route": "gpt4o"},
    "casual_roleplay": {"max_sentences": 2, "route": "gpt4o"},
    "party_debate":    {"max_sentences": 2, "route": "gpt4o"},
    "direct_question": {"max_sentences": 3, "route": "gpt4o"},
    "emotional_beat":  {"max_sentences": 5, "route": "claude"},
    "backstory_call":  {"max_sentences": 5, "route": "claude"},
    "npc_social":      {"max_sentences": 4, "route": "claude"},
    "moral_dilemma":   {"max_sentences": 4, "route": "claude"},
}


@dataclass
class EngineDecision:
    should_respond: bool
    priority: int                      # 1 (highest) – 5 (lowest)
    context_type: str = "casual_roleplay"
    route: str = "gpt4o"               # "gpt4o" | "claude" | "template"
    interrupt_score: float = 0.0
    reason: str = ""                   # debug / logging


@dataclass
class AvatarState:
    """Per-avatar mutable state tracked by the engine."""
    avatar_id: int
    name: str
    mode: str = "active"               # active | passive | absent
    last_spoke_at: float = 0.0
    last_name_mentioned_at: float = 0.0
    last_responded_to_avatar_at: float = 0.0   # Phase 4: avatar-to-avatar cooldown
    # Phase 8: personality-driven response gating
    verbosity: float = 0.5             # 0.0=silent, 1.0=talks constantly
    interrupts_often: bool = False     # lowers interrupt confidence threshold
    personality_archetype: str = "extrovert"  # introvert | extrovert | reactive | stoic


class ContextEngine:
    """
    Stateful engine that evaluates each incoming transcript utterance
    against every active avatar and returns a decision.
    """

    def __init__(self):
        self._avatar_states: dict[int, AvatarState] = {}
        self._last_any_avatar_spoke: float = 0.0
        self._dm_hotword_at: float = 0.0
        self._human_speaking: bool = False
        self._aec_gate_closed: bool = False

    # ── State management ─────────────────────────────────────────────────

    def register_avatar(
        self,
        avatar_id: int,
        name: str,
        mode: str = "active",
        verbosity: float = 0.5,
        interrupts_often: bool = False,
        personality_archetype: str = "extrovert",
    ) -> None:
        self._avatar_states[avatar_id] = AvatarState(
            avatar_id=avatar_id,
            name=name,
            mode=mode,
            verbosity=verbosity,
            interrupts_often=interrupts_often,
            personality_archetype=personality_archetype,
        )

    def unregister_avatar(self, avatar_id: int) -> None:
        self._avatar_states.pop(avatar_id, None)

    def set_avatar_mode(self, avatar_id: int, mode: str) -> None:
        if avatar_id in self._avatar_states:
            self._avatar_states[avatar_id].mode = mode

    def on_human_speech_start(self) -> None:
        self._human_speaking = True

    def on_human_speech_end(self) -> None:
        self._human_speaking = False

    def on_avatar_spoke(self, avatar_id: int) -> None:
        now = time.monotonic()
        if avatar_id in self._avatar_states:
            self._avatar_states[avatar_id].last_spoke_at = now
        self._last_any_avatar_spoke = now

    def on_aec_gate_changed(self, closed: bool) -> None:
        self._aec_gate_closed = closed

    def on_dm_hotword(self) -> None:
        self._dm_hotword_at = time.monotonic()

    # ── Core evaluation ──────────────────────────────────────────────────

    def evaluate(
        self,
        transcript: str,
        avatar_id: int,
        is_combat: bool = False,
        silence_gap: float = 0.0,
        source: str = "human",          # "human" | "avatar_speech"
    ) -> EngineDecision:
        """
        Evaluate whether `avatar_id` should respond to `transcript`.

        Parameters
        ----------
        transcript   : raw text of the utterance
        avatar_id    : avatar to evaluate
        is_combat    : True if we're in an active combat round
        silence_gap  : seconds since last human speech
        source       : "human" for player speech; "avatar_speech" for chain reactions
        """
        state = self._avatar_states.get(avatar_id)
        if not state:
            return EngineDecision(False, 5, reason="avatar_not_registered")

        # ── 1. Suppression checks ─────────────────────────────────────
        now = time.monotonic()
        _settings = get_settings()

        if state.mode == "absent":
            return EngineDecision(False, 5, reason="mode_absent")

        if self._aec_gate_closed:
            return EngineDecision(False, 5, reason="aec_gate_closed")

        if self._human_speaking:
            return EngineDecision(False, 5, reason="human_speaking")

        dm_hotword_age = now - self._dm_hotword_at
        if dm_hotword_age < 30.0:
            return EngineDecision(False, 1, reason="dm_hotword_active")

        self_age = now - state.last_spoke_at
        if self_age < _settings.self_cooldown_seconds:
            return EngineDecision(False, 5, reason="self_cooldown")

        any_avatar_age = now - self._last_any_avatar_spoke
        if any_avatar_age < _settings.avatar_cooldown_seconds:
            return EngineDecision(False, 5, reason="avatar_cooldown")

        # ── Phase 4: avatar-speech-specific gates ─────────────────────
        if source == "avatar_speech":
            # Stoic avatars never react to other avatars unless named
            if state.personality_archetype == "stoic":
                return EngineDecision(False, 5, reason="stoic_ignores_avatar_speech")

            # Introvert: dedicated per-avatar cooldown (60s) for avatar speech reactions
            if state.personality_archetype == "introvert":
                introvert_age = now - state.last_responded_to_avatar_at
                if introvert_age < 60.0:
                    return EngineDecision(False, 5, reason="introvert_avatar_cooldown")

            # General avatar-speech cooldown (stricter than normal)
            avatar_speech_age = now - state.last_responded_to_avatar_at
            if avatar_speech_age < _settings.avatar_speech_cooldown_s:
                return EngineDecision(False, 5, reason="avatar_speech_cooldown")

        # ── 2. Interrupt confidence scoring ───────────────────────────
        score = _interrupt_confidence(transcript, state.name)

        # Phase 4: reduce score by 30% for avatar-speech — avatars respond less
        # readily to each other than to humans, preventing runaway chatter loops
        if source == "avatar_speech":
            score *= 0.7

        # ── 3. Additional triggers ────────────────────────────────────
        is_direct = score >= _settings.interrupt_confidence_threshold
        has_question = "?" in transcript
        combat_trigger = is_combat or _is_combat_trigger(transcript)
        silence_trigger = (
            state.mode == "active"
            and silence_gap >= _settings.silence_gap_trigger
        )
        name_recent = (now - state.last_name_mentioned_at) < 60.0
        if _name_in_text(transcript, state.name):
            state.last_name_mentioned_at = now
            name_recent = True

        # Passive mode: only respond when directly addressed
        if state.mode == "passive" and not is_direct and not name_recent:
            return EngineDecision(False, 5, reason="passive_not_addressed")

        # ── 3b. Personality archetype gate ───────────────────────────
        archetype = state.personality_archetype

        if archetype == "stoic":
            # Stoic: only speaks when named, directly addressed, or in combat
            if not is_direct and not name_recent and not combat_trigger:
                return EngineDecision(False, 5, reason="stoic_not_triggered")

        elif archetype == "introvert":
            # Introvert: only speaks when directly addressed or recently named
            if not is_direct and not name_recent:
                return EngineDecision(False, 5, reason="introvert_not_addressed")

        elif archetype == "reactive":
            # Reactive: engages with questions, debate, combat — not ambient silence
            if not is_direct and not name_recent and not has_question and not combat_trigger:
                return EngineDecision(False, 5, reason="reactive_not_triggered")
            if not is_direct and not name_recent:
                import random as _random
                if _random.random() > state.verbosity:
                    return EngineDecision(False, 5, reason="reactive_verbosity_roll")

        else:
            # extrovert (default): apply verbosity roll for ambient/casual triggers
            # silence_trigger is a passive engagement pathway — not subject to verbosity roll
            if not is_direct and not name_recent and not combat_trigger and not silence_trigger:
                import random as _random
                if _random.random() > state.verbosity:
                    return EngineDecision(False, 5, reason="extrovert_verbosity_roll")

        # interrupts_often: lower the effective threshold so they cut in more
        if state.interrupts_often:
            effective_threshold = _settings.interrupt_confidence_threshold * 0.7
            is_direct = score >= effective_threshold

        # ── 4. Context type & route ───────────────────────────────────
        context_type = _classify_context(transcript, is_combat=combat_trigger)
        route = CONTEXT_TYPES[context_type]["route"]

        # ── 5. Priority & final decision ─────────────────────────────
        if combat_trigger and is_direct:
            priority = 2
        elif is_direct:
            priority = 2
        elif has_question:
            priority = 3
        elif combat_trigger:
            priority = 4
        elif silence_trigger:
            priority = 5
        elif name_recent:
            priority = 3
        else:
            return EngineDecision(False, 5, interrupt_score=score, reason="below_threshold")

        # Phase 4: track when this avatar last responded to avatar speech
        if source == "avatar_speech":
            state.last_responded_to_avatar_at = now

        return EngineDecision(
            should_respond=True,
            priority=priority,
            context_type=context_type,
            route=route,
            interrupt_score=score,
            reason="ok",
        )


# ── Pure helper functions (no state) ─────────────────────────────────────────

def _interrupt_confidence(transcript: str, avatar_name: str) -> float:
    directed_fragments = prompt_loader.get_context_keyword_set("directed_fragments")
    score = 0.0
    lower = transcript.lower()
    if avatar_name.lower() in lower:
        score += 0.8
    if "?" in transcript:
        score += 0.3
    if any(frag in lower for frag in directed_fragments):
        score += 0.4
    return min(score, 1.0)


def _name_in_text(text: str, name: str) -> bool:
    return name.lower() in text.lower()


def _is_combat_trigger(text: str) -> bool:
    combat_triggers = prompt_loader.get_context_keyword_set("combat_triggers")
    lower = text.lower()
    return any(t in lower for t in combat_triggers)


def _is_dm_hotword(text: str) -> bool:
    dm_hotwords = prompt_loader.get_context_keyword_set("dm_hotwords")
    lower = text.strip().lower()
    return any(hw in lower for hw in dm_hotwords)


def _classify_context(transcript: str, is_combat: bool = False) -> str:
    lower = transcript.lower()

    if is_combat or _is_combat_trigger(transcript):
        return "combat_turn"

    claude_keywords = prompt_loader.get_context_keyword_set("claude_keywords")
    moral_keywords = prompt_loader.get_context_keyword_set("moral_keywords")
    backstory_keywords = prompt_loader.get_context_keyword_set("backstory_keywords")
    npc_social_keywords = prompt_loader.get_context_keyword_set("npc_social_keywords")

    if any(kw in lower for kw in claude_keywords):
        if any(kw in lower for kw in moral_keywords):
            return "moral_dilemma"
        if any(kw in lower for kw in backstory_keywords):
            return "backstory_call"
        return "emotional_beat"

    if "?" in transcript:
        return "direct_question"

    if any(w in lower for w in npc_social_keywords):
        return "npc_social"

    return "casual_roleplay"
