"""
Cross-Avatar Reference Injector — Phase 7.

Maintains a rolling buffer of recent avatar speech per session.
When an avatar is about to respond, there is a configurable probability
(default 25%) that a reference to another avatar's recent speech is
injected into the LLM prompt as `cross_avatar_note`.

The note is brief and character-neutral — it reminds the avatar of what
their party member just said so they can react naturally without forcing it.

Example output:
  "Kaela just said: 'I don't trust the innkeeper.'"
  "Aldric recently spoke: 'We press on at dawn.'"

Usage:
    ref = CrossAvatarReferencer()
    ref.record_speech(avatar_id=1, name="Aldric", text="We press on at dawn.")
    note = ref.get_reference_note(
        requesting_avatar_id=2,
        requesting_avatar_name="Kaela",
    )
    # note → "Aldric just said: 'We press on at dawn.'" (25% chance)
    # note → ""  (75% chance, or if no other avatar has spoken)
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass


# Probability that a cross-avatar note is injected on any given response
_INJECTION_PROBABILITY = 0.25

# Maximum age (seconds) of a quote to still be considered "recent"
_MAX_AGE_SECONDS = 120.0

# Maximum number of recent avatar quotes to keep in the buffer
_BUFFER_SIZE = 10


@dataclass
class AvatarQuote:
    avatar_id: int
    name: str
    text: str
    timestamp: float


class CrossAvatarReferencer:
    """
    Session-scoped rolling buffer of recent avatar speech.
    One instance per session (held on AudioPipeline).
    """

    def __init__(
        self,
        injection_probability: float = _INJECTION_PROBABILITY,
        max_age_seconds: float = _MAX_AGE_SECONDS,
    ):
        self._probability = injection_probability
        self._max_age = max_age_seconds
        self._buffer: list[AvatarQuote] = []

    # ── Recording ─────────────────────────────────────────────────────────

    def record_speech(self, avatar_id: int, name: str, text: str) -> None:
        """Record an avatar's spoken text. Called after each avatar response."""
        # Strip very short utterances (backchannels, single words)
        if not text or len(text.split()) < 4:
            return
        self._buffer.append(AvatarQuote(
            avatar_id=avatar_id,
            name=name,
            text=text.strip(),
            timestamp=time.monotonic(),
        ))
        # Keep buffer bounded
        if len(self._buffer) > _BUFFER_SIZE:
            self._buffer = self._buffer[-_BUFFER_SIZE:]

    # ── Retrieval ─────────────────────────────────────────────────────────

    def get_reference_note(
        self,
        requesting_avatar_id: int,
        requesting_avatar_name: str,
        rng: random.Random | None = None,
    ) -> str:
        """
        With `_probability`, return a short note about a recent party member quote.
        Returns empty string if:
          - Random roll fails (75% of the time by default)
          - No recent quotes from other avatars exist
          - The only recent quotes are from the requesting avatar
        """
        _rng = rng or random
        if _rng.random() > self._probability:
            return ""

        now = time.monotonic()
        candidates = [
            q for q in self._buffer
            if q.avatar_id != requesting_avatar_id
            and (now - q.timestamp) <= self._max_age
        ]

        if not candidates:
            return ""

        # Pick the most recent eligible quote
        quote = candidates[-1]
        # Truncate very long quotes
        text = quote.text
        if len(text) > 120:
            text = text[:117].rstrip() + "…"

        return f"{quote.name} just said: \"{text}\""

    def clear(self) -> None:
        self._buffer.clear()

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)
