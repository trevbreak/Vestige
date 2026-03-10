"""
Ambient Reactions — Holding Phrases.

When the context engine decides an avatar should respond but the LLM hasn't
finished generating yet, a short holding phrase plays to fill the dead air
and signal the avatar is "thinking".

The full LLM response follows 1–3 seconds later.
"""

from __future__ import annotations

import random

# Per-context holding phrase library
AMBIENT_REACTIONS: dict[str, list[str]] = {
    "combat_turn":     [
        "[tense] I'm working out my options...",
        "[tense] Give me a moment...",
        "[urgently] Hold on, let me think...",
    ],
    "casual_roleplay": [
        "[quietly] Give me a moment...",
        "Hmm...",
        "Let me think on that...",
    ],
    "direct_question": [
        "Hmm, let me think on that...",
        "That's... a good question.",
        "Give me a second...",
    ],
    "party_debate": [
        "Hmm.",
        "[quietly] I'm weighing this...",
        "There's something to that...",
    ],
    "emotional_beat": [
        "[quietly] ...",
        "[quietly] That's... a lot to take in.",
        "I need a moment.",
    ],
    "backstory_call": [
        "[quietly] That's not something I talk about lightly.",
        "...",
        "[quietly] Where do I even start...",
    ],
    "npc_social": [
        "Let me think about how to put this...",
        "Hmm.",
        "That's... interesting.",
    ],
    "moral_dilemma": [
        "[quietly] This isn't simple.",
        "Hmm. I'm not sure there's a right answer here.",
        "[tense] Give me a moment to think.",
    ],
    "default": [
        "Hmm.",
        "Right...",
        "...",
        "Let me think...",
    ],
}


def get_holding_phrase(context_type: str) -> str:
    """
    Return a random holding phrase for the given context type.
    Falls back to 'default' if context_type is not recognised.
    """
    options = AMBIENT_REACTIONS.get(context_type, AMBIENT_REACTIONS["default"])
    return random.choice(options)


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
