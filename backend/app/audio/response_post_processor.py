"""
Response Post-Processor.

Every LLM output passes through this pipeline before being sent to TTS:

  1. Enforce first-person (never "{Name} does X")
  2. Strip markdown (**, *, _, #, bullets)
  3. Strip stage directions ((laughs), *sighs*, [narrator voice], etc.)
  4. Enforce length limit (context-type-based max sentence count)
  5. Extract emotion tag ([quietly], [urgently], etc.)
  6. Apply response jitter (random 1.5–4s delay)

The post-processor is pure/synchronous — no I/O, fully testable.
"""

from __future__ import annotations

import re
import random
from dataclasses import dataclass

from app.config import get_settings

settings = get_settings()

# ── Emotion tags allowed in LLM output ───────────────────────────────────────
VALID_EMOTIONS = frozenset({
    "quietly", "urgently", "laughing", "tense", "whispering", "default",
})

# ── Stage direction patterns to strip ────────────────────────────────────────
_STAGE_DIRECTION_RE = re.compile(
    r"(\([^)]*\))"          # (laughs), (sighs softly), (looks around)
    r"|(\*[^*]+\*)"         # *sighs*, *chuckles*
    r"|(^\[narrator[^\]]*\])",  # [narrator voice], [aside]
    re.IGNORECASE,
)

# ── Markdown patterns ─────────────────────────────────────────────────────────
_MARKDOWN_RE = re.compile(
    r"(\*\*|__)(.*?)\1"     # **bold** or __bold__
    r"|(\*|_)(.*?)\3"       # *italic* or _italic_
    r"|^#{1,6}\s+"          # ## Heading
    r"|^[-*+]\s+"           # bullet list
    r"|^\d+\.\s+",          # numbered list
    re.MULTILINE,
)

# ── Emotion tag at start of text ─────────────────────────────────────────────
_EMOTION_TAG_RE = re.compile(r"^\[(\w+)\]\s*", re.IGNORECASE)

# ── Context type → max sentence count ────────────────────────────────────────
MAX_SENTENCES: dict[str, int] = {
    "combat_turn":     2,
    "casual_roleplay": 2,
    "party_debate":    2,
    "direct_question": 3,
    "emotional_beat":  5,
    "backstory_call":  5,
    "npc_social":      4,
    "moral_dilemma":   4,
    "default":         3,
}


@dataclass
class ProcessedResponse:
    text: str           # cleaned plain text for TTS
    emotion: str        # one of VALID_EMOTIONS
    delay_seconds: float  # jitter delay before playback
    original: str       # raw LLM output (for logging)
    truncated: bool = False


class ResponsePostProcessor:
    """
    Stateless post-processor. Instantiate once and reuse.
    """

    def process(
        self,
        raw_text: str,
        context_type: str = "default",
        avatar_name: str = "",
    ) -> ProcessedResponse:
        """
        Full post-processing pipeline.

        Parameters
        ----------
        raw_text     : raw LLM response string
        context_type : one of CONTEXT_TYPES keys from context_engine
        avatar_name  : used for third-person detection
        """
        text = raw_text.strip()
        original = text

        # 1. Extract emotion tag (must be first, before other stripping)
        emotion = "default"
        m = _EMOTION_TAG_RE.match(text)
        if m:
            tag = m.group(1).lower()
            if tag in VALID_EMOTIONS:
                emotion = tag
            text = text[m.end():]

        # 2. Strip markdown
        text = self._strip_markdown(text)

        # 3. Strip stage directions
        text = self._strip_stage_directions(text)

        # 4. Enforce first-person
        if avatar_name:
            text = self._enforce_first_person(text, avatar_name)

        # 5. Normalise whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # 6. Enforce length
        text, truncated = self._enforce_length(text, context_type)

        # 7. Response jitter
        delay = random.uniform(settings.response_jitter_min, settings.response_jitter_max)

        return ProcessedResponse(
            text=text,
            emotion=emotion,
            delay_seconds=delay,
            original=original,
            truncated=truncated,
        )

    # ── Private helpers ───────────────────────────────────────────────────

    @staticmethod
    def _strip_markdown(text: str) -> str:
        # Replace bold/italic markers, keeping inner text
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"__(.*?)__", r"\1", text)
        text = re.sub(r"\*(.*?)\*", r"\1", text)
        text = re.sub(r"_(.*?)_", r"\1", text)
        # Remove headings, bullets, numbered lists
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
        return text

    @staticmethod
    def _strip_stage_directions(text: str) -> str:
        # Remove (laughs), *sighs*, [narrator ...]
        text = re.sub(r"\([^)]*\)", "", text)
        text = re.sub(r"\*[^*]+\*", "", text)
        text = re.sub(r"\[narrator[^\]]*\]", "", text, flags=re.IGNORECASE)
        # Remove [aside], [to DM], etc. but preserve valid emotion tags that already parsed
        text = re.sub(r"\[[^\]]{1,30}\]", "", text)
        return text

    @staticmethod
    def _enforce_first_person(text: str, avatar_name: str) -> str:
        """
        Replace "{Name} verb" with "I verb" for common patterns.
        LLMs occasionally slip into third-person narration.
        """
        name = re.escape(avatar_name)
        # "Aldric reaches for..." → "I reach for..."
        text = re.sub(
            rf"\b{name}\s+(reaches?|draws?|steps?|turns?|looks?|says?|asks?|replies?|nods?|shakes?|smiles?|frowns?)\b",
            lambda m: f"I {m.group(1)}",
            text,
            flags=re.IGNORECASE,
        )
        # "{Name}'s voice" → "My voice"  (possessive)
        text = re.sub(rf"\b{name}'s\b", "my", text, flags=re.IGNORECASE)
        return text

    @staticmethod
    def _enforce_length(text: str, context_type: str) -> tuple[str, bool]:
        max_s = MAX_SENTENCES.get(context_type, MAX_SENTENCES["default"])
        # Split on sentence-ending punctuation
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        if len(sentences) <= max_s:
            return text, False
        truncated = " ".join(sentences[:max_s])
        # Ensure it ends with punctuation
        if truncated and truncated[-1] not in ".!?":
            truncated += "."
        return truncated, True


# Module-level singleton
post_processor = ResponsePostProcessor()
