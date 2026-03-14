"""
Ambient Reactions — Holding Phrases.

When the context engine decides an avatar should respond but the LLM hasn't
finished generating yet, a short holding phrase plays to fill the dead air
and signal the avatar is "thinking".

The full LLM response follows 1–3 seconds later.

Phrases are loaded from backend/prompts/holding_phrases.yaml via the prompt
loader. Edit that file and POST /api/prompts/reload to change them at runtime.
"""

from __future__ import annotations

import random

from app.prompts.loader import prompt_loader

# ── Contexts where a holding phrase is always appropriate (when chance > 0) ──
HIGH_IMPORTANCE_CONTEXTS = frozenset({
    "direct_question",
    "emotional_beat",
    "backstory_call",
    "moral_dilemma",
})


# Compatibility shim for code/tests that import AMBIENT_REACTIONS directly.
# The live data lives in backend/prompts/holding_phrases.yaml.
AMBIENT_REACTIONS: dict[str, list[str]] = prompt_loader.holding_phrases


def get_holding_phrase(context_type: str) -> str:
    """
    Return a random holding phrase for the given context type.
    Falls back to 'default' if context_type is not recognised.
    Phrases are loaded from holding_phrases.yaml.
    """
    return prompt_loader.get_holding_phrase(context_type)


def should_play_holding_phrase(context_type: str, avatar_chance: float) -> bool:
    """
    Return True if the avatar should play a holding phrase before responding.

    High-importance contexts (direct_question, emotional_beat, backstory_call,
    moral_dilemma) always play when avatar_chance > 0.

    All other contexts use avatar_chance as a probability roll (0.0 = never,
    1.0 = always).
    """
    if avatar_chance <= 0.0:
        return False
    if context_type in HIGH_IMPORTANCE_CONTEXTS:
        return True
    return random.random() < avatar_chance


def strip_holding_emotion(phrase: str) -> tuple[str, str]:
    """
    Extract emotion tag from a holding phrase if present.

    Returns (clean_text, emotion).
    e.g. "[tense] Give me a moment..." → ("Give me a moment...", "tense")
    """
    import re
    m = re.match(r"^\[(\w+)\]\s*", phrase)
    if m:
        emotion = m.group(1).lower()
        text = phrase[m.end():]
        return text, emotion
    return phrase, "default"
