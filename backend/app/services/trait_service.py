"""
Character Trait Service — decay, manifestation, and reinforcement.

Traits develop from significant campaign events, strengthen when triggered,
and fade (decay) over time without reinforcement. They manifest probabilistically
when their trigger keywords appear in a transcript.
"""

from __future__ import annotations

import json
import math
import random
import structlog
from datetime import datetime, timezone

log = structlog.get_logger()


def decay_traits(avatar_id: int, db) -> None:
    """
    Apply weekly decay to all active traits for an avatar.

    Call at session start or after a significant time gap. Strength decays
    10% per week without reinforcement. Traits below 0.1 are marked resolved.
    """
    from app.models.character_trait import CharacterTrait
    from app.config import get_settings

    settings = get_settings()
    now = datetime.now(timezone.utc)
    traits = db.query(CharacterTrait).filter_by(avatar_id=avatar_id, is_resolved=False).all()

    for trait in traits:
        if trait.last_reinforced_at is None:
            continue
        last = trait.last_reinforced_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        days_elapsed = (now - last).total_seconds() / 86400
        weeks = days_elapsed / 7
        decay_factor = (1.0 - settings.trait_decay_weekly_pct) ** weeks
        trait.current_strength = max(0.0, trait.current_strength * decay_factor)
        if trait.current_strength < 0.1:
            trait.is_resolved = True
            log.info(
                "trait_service.resolved",
                avatar_id=avatar_id,
                trait=trait.trait_name,
            )

    db.commit()


def should_manifest(trait, base_probability_override: float | None = None) -> bool:
    """
    Stochastic check — returns True when the trait should visibly affect behaviour.

    Called when a trigger keyword appears in the transcript. Probability is
    (manifestation_probability * current_strength), clamped to [0, 1].
    """
    base = base_probability_override if base_probability_override is not None \
        else trait.manifestation_probability
    effective = min(1.0, base * trait.current_strength)
    return random.random() < effective


def reinforce_trait(trait, delta: float = 0.1) -> None:
    """
    Strengthen a trait when it manifests or is triggered by a campaign event.

    Updates current_strength and last_reinforced_at. Caller must commit.
    """
    trait.current_strength = min(1.0, trait.current_strength + delta)
    trait.last_reinforced_at = datetime.now(timezone.utc)


def check_trait_triggers(
    transcript: str,
    avatar_traits: list,
) -> list[str]:
    """
    Check transcript against trigger keywords for all active traits.

    Returns list of emotional_signature strings for traits that manifest.
    Calls reinforce_trait() on each manifesting trait (caller must commit).
    """
    emotions = []
    lower = transcript.lower()

    for trait in avatar_traits:
        if trait.is_resolved or not trait.trigger_keywords:
            continue
        try:
            keywords = json.loads(trait.trigger_keywords)
        except (json.JSONDecodeError, TypeError):
            continue
        if any(kw.lower() in lower for kw in keywords):
            if should_manifest(trait):
                if trait.emotional_signature:
                    emotions.append(trait.emotional_signature)
                reinforce_trait(trait)
                log.info(
                    "trait_service.manifested",
                    trait=trait.trait_name,
                    strength=round(trait.current_strength, 2),
                    emotion=trait.emotional_signature,
                )

    return emotions
