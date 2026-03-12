"""
Combat Turn Detector.

Analyses DM speech transcripts to detect:
  1. Combat start ("Roll for initiative", "Roll initiative", combat keywords)
  2. Turn prompts ("Aldric, it's your turn", "What do you do, Kaela?")
  3. Round boundaries ("Next round", "Top of the round")
  4. Combat end ("Combat is over", "The last enemy falls", etc.)

Returns structured detection results. Called from the audio pipeline
after each DM transcript segment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CombatSignal(str, Enum):
    NONE          = "none"
    START_COMBAT  = "start_combat"
    TURN_PROMPT   = "turn_prompt"      # DM addresses a specific combatant
    NEXT_ROUND    = "next_round"
    END_COMBAT    = "end_combat"
    DEATH_SAVE    = "death_save"       # "roll a death saving throw"
    DAMAGE        = "damage"           # "take X damage"


@dataclass
class DetectionResult:
    signal: CombatSignal
    addressed_name: str | None = None   # name from a turn prompt
    damage_amount: int | None = None    # parsed from damage phrases
    confidence: float = 1.0
    raw_text: str = ""


# ── Pattern sets ──────────────────────────────────────────────────────────────

_START_PATTERNS = [
    re.compile(r"\broll\s+(for\s+)?initiative\b", re.IGNORECASE),
    re.compile(r"\binititative\b", re.IGNORECASE),          # common typo variant
    re.compile(r"\bcombat\s+begins\b", re.IGNORECASE),
    re.compile(r"\broll\s+initiative\b", re.IGNORECASE),
    re.compile(r"\bsurprise\s+round\b", re.IGNORECASE),
]

_END_PATTERNS = [
    re.compile(r"\bcombat\s+(is\s+)?over\b", re.IGNORECASE),
    re.compile(r"\blast\s+enemy\s+(is\s+)?(dead|falls|drops)\b", re.IGNORECASE),
    re.compile(r"\bencounter\s+(is\s+)?over\b", re.IGNORECASE),
    re.compile(r"\b(all\s+)?enemies\s+(are\s+)?(dead|defeated|down)\b", re.IGNORECASE),
    re.compile(r"\byou\s+(win|won|have\s+won)\b", re.IGNORECASE),
    re.compile(r"\bfight\s+(is\s+)?over\b", re.IGNORECASE),
]

_NEXT_ROUND_PATTERNS = [
    re.compile(r"\bnext\s+round\b", re.IGNORECASE),
    re.compile(r"\btop\s+of\s+(the\s+)?round\b", re.IGNORECASE),
    re.compile(r"\bnew\s+round\b", re.IGNORECASE),
    re.compile(r"\bround\s+\d+\b", re.IGNORECASE),
]

_DEATH_SAVE_PATTERNS = [
    re.compile(r"\bdeath\s+saving\s+throw\b", re.IGNORECASE),
    re.compile(r"\bdeath\s+save\b", re.IGNORECASE),
    re.compile(r"\broll\s+to\s+stabilize\b", re.IGNORECASE),
]

_DAMAGE_PATTERN = re.compile(
    r"\btake[s]?\s+(\d+)\s+(points?\s+of\s+)?"
    r"(bludgeoning|piercing|slashing|fire|cold|lightning|thunder|acid|poison|necrotic|radiant|psychic|force|)?"
    r"\s*damage\b",
    re.IGNORECASE,
)

# Turn prompt: "Name, it's your turn" / "What does Name do?" / "Name, what do you do?"
_TURN_PROMPT_PATTERN = re.compile(
    r"(?:"
    r"([A-Z][a-zA-Z''\-]{1,30})[,\s]+(?:it'?s?\s+your\s+turn|your\s+turn)"
    r"|what\s+(?:do|does|would)\s+([A-Z][a-zA-Z''\-]{1,30})\s+do"
    r"|([A-Z][a-zA-Z''\-]{1,30})[,\s]+what\s+(?:do|will|are)\s+you"
    r"|([A-Z][a-zA-Z''\-]{1,30})[,?]\s*(?:go ahead|your\s+action|your\s+move)"
    r")"
)

# Common filler words that look like names but aren't
_NOT_NAMES = frozenset({
    "it", "its", "what", "ok", "okay", "now", "alright", "so",
    "next", "then", "the", "a", "an",
})


class CombatDetector:
    """
    Stateless detector — call detect(text) for each transcript segment.
    """

    def detect(self, text: str) -> DetectionResult:
        """
        Analyse a transcript segment and return the strongest combat signal.
        Priority: end > start > death_save > damage > next_round > turn_prompt > none
        """
        if not text or not text.strip():
            return DetectionResult(signal=CombatSignal.NONE, raw_text=text)

        # End combat
        for pat in _END_PATTERNS:
            if pat.search(text):
                return DetectionResult(
                    signal=CombatSignal.END_COMBAT,
                    raw_text=text,
                )

        # Start combat
        for pat in _START_PATTERNS:
            if pat.search(text):
                return DetectionResult(
                    signal=CombatSignal.START_COMBAT,
                    raw_text=text,
                )

        # Death save
        for pat in _DEATH_SAVE_PATTERNS:
            if pat.search(text):
                return DetectionResult(
                    signal=CombatSignal.DEATH_SAVE,
                    raw_text=text,
                )

        # Damage
        dm = _DAMAGE_PATTERN.search(text)
        if dm:
            try:
                amount = int(dm.group(1))
            except (ValueError, IndexError):
                amount = None
            return DetectionResult(
                signal=CombatSignal.DAMAGE,
                damage_amount=amount,
                raw_text=text,
            )

        # Next round
        for pat in _NEXT_ROUND_PATTERNS:
            if pat.search(text):
                return DetectionResult(
                    signal=CombatSignal.NEXT_ROUND,
                    raw_text=text,
                )

        # Turn prompt — extract addressed name
        m = _TURN_PROMPT_PATTERN.search(text)
        if m:
            name = next(
                (g for g in m.groups() if g and g.lower() not in _NOT_NAMES),
                None,
            )
            if name:
                return DetectionResult(
                    signal=CombatSignal.TURN_PROMPT,
                    addressed_name=name,
                    raw_text=text,
                )

        return DetectionResult(signal=CombatSignal.NONE, raw_text=text)

    def is_dm_speech(self, speaker: str) -> bool:
        """Return True if the speaker label indicates DM speech."""
        return speaker.strip().lower() in ("dm", "dungeon master", "gm", "game master")


# Module-level singleton
combat_detector = CombatDetector()
