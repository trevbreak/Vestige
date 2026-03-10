"""
Backchannel Classifier.

Short listening sounds ("mm", "yeah", "right") are tagged as
'backchannel' — they are logged but do NOT trigger the context
engine or LLM response generation.
"""

import re

# Canonical backchannel tokens — match as substrings within short utterances.
BACKCHANNEL_TOKENS: frozenset[str] = frozenset({
    "yeah", "yep", "yup", "uh huh", "mm", "mmm", "hmm", "oh", "ah",
    "right", "okay", "ok", "sure", "got it", "i see", "go on",
    "wow", "really", "no way", "interesting", "huh", "makes sense",
    "nice", "cool", "and then", "wait", "uh", "um", "mhm",
})

# Maximum word count for an utterance to still be considered a backchannel
BACKCHANNEL_MAX_WORDS = 4


def classify_utterance(text: str) -> str:
    """
    Classify a transcript utterance.

    Returns
    -------
    'backchannel'
        Short listening sounds — do not trigger LLM.
    'statement'
        Substantive speech — pass to context engine.
    """
    cleaned = text.strip().lower()
    # Strip trailing punctuation for matching
    normalized = re.sub(r"[.,!?]+$", "", cleaned)
    words = normalized.split()

    if len(words) <= BACKCHANNEL_MAX_WORDS:
        for token in BACKCHANNEL_TOKENS:
            if token in normalized:
                return "backchannel"

    return "statement"


def is_inaudible(text: str) -> bool:
    """Return True if faster-whisper flagged the segment as inaudible noise."""
    lower = text.strip().lower()
    return lower in {"[inaudible]", "(inaudible)", "[noise]", "[music]", "[silence]", ""}
