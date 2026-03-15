"""
Seed script: assign Edge-TTS voice_id to all active avatars that lack one.

Run from the repo root:
    cd backend && .venv/Scripts/python ../scripts/seed_avatar_voices.py [--dry-run]

Strategy:
  1. For each active avatar with voice_id=None, call Ollama to pick the best
     fitting voice via generate_personality_data().
  2. If Ollama is unavailable, fall back to round-robin assignment across the
     voice catalogue so every avatar at least gets a distinct voice.
  3. Also ensures tts_engine_preference is set to 'auto' (the correct default
     for Edge-TTS fallback when no XTTS embedding is present).

Flags:
  --dry-run   Show what would change without writing to the database.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import os

# Allow running from scripts/ or from backend/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.db.database import AsyncSessionLocal
from app.models.avatar import Avatar
from app.llm.avatar_generator import (
    generate_personality_data,
    VOICE_CATALOGUE,
    _fallback_voice,
)
from sqlalchemy import select
import structlog

log = structlog.get_logger()

# Ordered list for deterministic round-robin fallback
_VOICE_POOL = list(VOICE_CATALOGUE["en"].keys())


def _round_robin_voice(index: int) -> str:
    return _VOICE_POOL[index % len(_VOICE_POOL)]


async def seed(dry_run: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Avatar).where(
                Avatar.is_active == True,  # noqa: E712
                Avatar.voice_id == None,   # noqa: E711
            )
        )
        avatars = list(result.scalars().all())

    if not avatars:
        print("All active avatars already have a voice_id — nothing to do.")
        return

    print(f"Found {len(avatars)} avatar(s) with no voice_id assigned.")

    # Check Ollama availability once
    ollama_ok = _check_ollama()
    if not ollama_ok:
        print(
            "WARNING: Ollama unavailable — falling back to round-robin voice assignment.\n"
            "Run this script again after Ollama is running to get LLM-matched voices."
        )

    assignments: list[tuple[Avatar, str]] = []
    used_voices: set[str] = set()

    # Voices already assigned to avatars not in this batch (so we don't collide with them either)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Avatar.voice_id).where(
                Avatar.is_active == True,  # noqa: E712
                Avatar.voice_id != None,   # noqa: E711
            )
        )
        for (existing_voice,) in result.all():
            if existing_voice:
                used_voices.add(existing_voice)

    for i, av in enumerate(avatars):
        if ollama_ok:
            avatar_data = {
                "name": av.name,
                "race": av.race,
                "char_class": av.char_class,
                "alignment": av.alignment or "",
                "personality_traits": av.personality_traits or "",
                "ideals": av.ideals or "",
                "bonds": av.bonds or "",
                "flaws": av.flaws or "",
                "backstory": av.backstory or "",
                "sentence_style": av.sentence_style or "",
                "verbal_tics": av.verbal_tics or "",
            }
            try:
                personality = generate_personality_data(avatar_data)
                voice = personality.get("voice_id") or _round_robin_voice(i)
            except Exception as exc:
                print(f"  [{av.name}] LLM failed ({exc}), using round-robin fallback")
                voice = _round_robin_voice(i)
        else:
            voice = _round_robin_voice(i)

        # If the LLM picked a voice already taken, find the next available one
        if voice in used_voices:
            original = voice
            rr_index = 0
            while voice in used_voices and rr_index < len(_VOICE_POOL):
                voice = _round_robin_voice(rr_index)
                rr_index += 1
            print(f"  [{av.name}] Voice collision on {original!r}, reassigned to {voice!r}")

        used_voices.add(voice)
        assignments.append((av, voice))
        label = VOICE_CATALOGUE["en"].get(voice, {}).get("label", voice)
        print(f"  {'[DRY RUN] ' if dry_run else ''}id={av.id} {av.name!r:30s} -> {voice} ({label})")

    if dry_run:
        print("\nDry run complete — no changes written.")
        return

    async with AsyncSessionLocal() as db:
        for av, voice in assignments:
            av_db = await db.get(Avatar, av.id)
            if av_db is None:
                continue
            av_db.voice_id = voice
            # Ensure preference is 'auto' so Edge-TTS is used when no XTTS embedding exists
            if not av_db.tts_engine_preference or av_db.tts_engine_preference == "auto":
                av_db.tts_engine_preference = "auto"
        await db.commit()

    print(f"\nDone — assigned voices to {len(assignments)} avatar(s).")


def _check_ollama() -> bool:
    """Quick check whether Ollama is reachable."""
    try:
        import httpx
        from app.config import get_settings
        settings = get_settings()
        r = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Edge-TTS voice_id for all active avatars.")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without saving")
    args = parser.parse_args()

    asyncio.run(seed(dry_run=args.dry_run))
