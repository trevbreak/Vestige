"""
Session Summariser.

Two modes:
  1. post_session()  — full session summary → structured JSON + prose
                       Called once when a session ends (or manually from the API).
                       Result stored in SessionSummary; requires DM approval before
                       memory chunks are committed.

  2. rolling_summary() — mid-session context compression
                         Called every ~60 minutes of session time to condense the
                         oldest transcript lines. Returns plain prose stored in
                         SessionSummary.rolling_summaries.

Both call Claude synchronously (designed for asyncio thread pool).
Degrades gracefully when API key is absent: returns stub summaries.
"""

from __future__ import annotations

import json
import time
import structlog
from dataclasses import dataclass, field
from typing import Any

log = structlog.get_logger()

# ── Schemas ────────────────────────────────────────────────────────────────────

@dataclass
class AvatarUpdate:
    """State changes for a single avatar from the session."""
    avatar_id: int
    avatar_name: str
    hp_delta: int = 0              # net HP change during session
    spell_slots_used: dict[str, int] = field(default_factory=dict)  # level → used
    items_gained: list[str] = field(default_factory=list)
    items_lost: list[str] = field(default_factory=list)
    conditions_gained: list[str] = field(default_factory=list)
    conditions_cleared: list[str] = field(default_factory=list)
    xp_gained: int = 0
    notes: str = ""


@dataclass
class SummaryResult:
    """Result of a summarisation call."""
    # Structured data
    events: list[str] = field(default_factory=list)
    npcs: list[dict[str, str]] = field(default_factory=list)   # [{name, notes}]
    items: list[dict[str, str]] = field(default_factory=list)  # [{name, owner, notes}]
    relationship_deltas: list[dict[str, str]] = field(default_factory=list)
    # [{avatar, target, note}]
    avatar_updates: list[AvatarUpdate] = field(default_factory=list)

    # Prose summary
    summary_text: str = ""

    # Metadata
    model: str = "stub"
    latency_ms: float = 0.0
    error: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "events": self.events,
            "npcs": self.npcs,
            "items": self.items,
            "relationship_deltas": self.relationship_deltas,
            "avatar_updates": [
                {
                    "avatar_id": u.avatar_id,
                    "avatar_name": u.avatar_name,
                    "hp_delta": u.hp_delta,
                    "spell_slots_used": u.spell_slots_used,
                    "items_gained": u.items_gained,
                    "items_lost": u.items_lost,
                    "conditions_gained": u.conditions_gained,
                    "conditions_cleared": u.conditions_cleared,
                    "xp_gained": u.xp_gained,
                    "notes": u.notes,
                }
                for u in self.avatar_updates
            ],
        }


# ── Prompt templates ───────────────────────────────────────────────────────────

_POST_SESSION_SYSTEM = """You are a D&D session analyst. You will be given a full session transcript.

Extract the following information as valid JSON (no markdown, no backticks, just raw JSON):

{
  "events": ["Short description of major plot events, 1 per item, max 10"],
  "npcs": [{"name": "NPC name", "notes": "What happened / relationship to party"}],
  "items": [{"name": "Item name", "owner": "Character name", "notes": "How obtained/used"}],
  "relationship_deltas": [{"avatar": "Avatar name", "target": "Other character or NPC", "note": "How the relationship changed"}],
  "avatar_updates": [
    {
      "avatar_name": "Name",
      "hp_delta": 0,
      "spell_slots_used": {},
      "items_gained": [],
      "items_lost": [],
      "conditions_gained": [],
      "conditions_cleared": [],
      "xp_gained": 0,
      "notes": "Anything important for this character"
    }
  ],
  "summary_text": "2–4 sentence prose summary of the session suitable for a campaign log."
}

Respond with ONLY valid JSON. If you cannot determine a value, use null or empty list."""


_ROLLING_SUMMARY_SYSTEM = """You are a D&D session scribe. Condense the following transcript excerpt into a short, dense summary (3–5 sentences) suitable for inclusion in a future LLM context window. Focus on plot events, character decisions, and combat outcomes. Do NOT include mundane small-talk. Write in past tense."""


# ── Summariser class ───────────────────────────────────────────────────────────

class SessionSummariser:
    """
    Calls Claude to summarise session transcripts.
    Synchronous — intended to run in an asyncio thread pool executor.
    """

    def __init__(self, model: str | None = None, max_tokens: int = 1024):
        from app.config import get_settings
        settings = get_settings()
        self._api_key = settings.anthropic_api_key
        self._model = model or "claude-haiku-4-5-20251001"
        self._max_tokens = max_tokens

    # ── Internal Claude call ───────────────────────────────────────────────

    def _call_claude(self, system: str, user: str) -> tuple[str, float]:
        """
        Synchronous Claude call. Returns (text, latency_ms).
        Returns ("", latency_ms) on error or missing key.
        """
        if not self._api_key:
            log.warning("memory.summariser_no_api_key")
            return "", 0.0

        t0 = time.monotonic()
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)
            msg = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = msg.content[0].text.strip() if msg.content else ""
            latency = (time.monotonic() - t0) * 1000
            log.info("memory.summariser_call_ok", model=self._model, latency_ms=round(latency))
            return text, latency
        except Exception as e:
            latency = (time.monotonic() - t0) * 1000
            log.error("memory.summariser_call_failed", error=str(e))
            return "", latency

    # ── Public API ─────────────────────────────────────────────────────────

    def post_session(
        self,
        transcript_lines: list[str],
        avatar_names: list[str] | None = None,
    ) -> SummaryResult:
        """
        Full post-session summary. Takes a list of "Speaker: text" strings.
        Returns a SummaryResult. If Claude is unavailable, returns a stub.
        """
        if not transcript_lines:
            return SummaryResult(
                summary_text="No transcript available.",
                error="empty_transcript",
            )

        # Build user message
        transcript_text = "\n".join(transcript_lines[-500:])  # cap at 500 lines
        avatars_note = ""
        if avatar_names:
            avatars_note = f"\nAvatars in this session: {', '.join(avatar_names)}\n"
        user_msg = f"{avatars_note}\n== TRANSCRIPT ==\n{transcript_text}"

        t0 = time.monotonic()
        raw, latency = self._call_claude(_POST_SESSION_SYSTEM, user_msg)

        if not raw:
            return SummaryResult(
                summary_text="Summary unavailable (Claude not configured).",
                model="stub",
                latency_ms=latency,
                error="no_response",
            )

        # Parse JSON
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON block if surrounded by prose
            import re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    data = {}
            else:
                data = {}

        # Parse avatar_updates into dataclass objects
        avatar_updates = []
        for u in data.get("avatar_updates", []):
            if not isinstance(u, dict):
                continue
            # Find avatar_id if possible (caller can patch this)
            avatar_updates.append(AvatarUpdate(
                avatar_id=0,  # to be filled in by caller
                avatar_name=u.get("avatar_name", ""),
                hp_delta=u.get("hp_delta", 0) or 0,
                spell_slots_used=u.get("spell_slots_used", {}) or {},
                items_gained=u.get("items_gained", []) or [],
                items_lost=u.get("items_lost", []) or [],
                conditions_gained=u.get("conditions_gained", []) or [],
                conditions_cleared=u.get("conditions_cleared", []) or [],
                xp_gained=u.get("xp_gained", 0) or 0,
                notes=u.get("notes", "") or "",
            ))

        return SummaryResult(
            events=data.get("events", []) or [],
            npcs=data.get("npcs", []) or [],
            items=data.get("items", []) or [],
            relationship_deltas=data.get("relationship_deltas", []) or [],
            avatar_updates=avatar_updates,
            summary_text=data.get("summary_text", "") or "",
            model=self._model,
            latency_ms=latency,
        )

    def rolling_summary(self, transcript_lines: list[str]) -> str:
        """
        Condense a chunk of transcript into a short rolling summary.
        Returns the prose string (or a stub if Claude unavailable).
        """
        if not transcript_lines:
            return ""

        transcript_text = "\n".join(transcript_lines[-200:])
        raw, _ = self._call_claude(_ROLLING_SUMMARY_SYSTEM, transcript_text)
        if not raw:
            return "[Summary unavailable]"
        return raw

    def chunks_from_result(
        self,
        result: SummaryResult,
        avatar_id: int,
        session_id: int,
    ) -> list[tuple[str, str, float]]:
        """
        Convert a SummaryResult into a flat list of (text, chunk_type, importance)
        tuples ready to be embedded and stored.

        Importance heuristics:
          - events: 0.7
          - npcs: 0.6
          - items: 0.5
          - relationship_deltas: 0.8
          - avatar_updates notes: 0.9
          - session prose summary: 0.8
        """
        chunks: list[tuple[str, str, float]] = []

        for ev in result.events:
            if ev:
                chunks.append((ev, "event", 0.7))

        for npc in result.npcs:
            if isinstance(npc, dict) and npc.get("name"):
                text = f"{npc['name']}: {npc.get('notes', '')}"
                chunks.append((text, "npc", 0.6))

        for item in result.items:
            if isinstance(item, dict) and item.get("name"):
                text = f"{item['name']} ({item.get('owner', '?')}): {item.get('notes', '')}"
                chunks.append((text, "item", 0.5))

        for rel in result.relationship_deltas:
            if isinstance(rel, dict) and rel.get("avatar"):
                text = (
                    f"{rel.get('avatar', '')} → {rel.get('target', '')}: "
                    f"{rel.get('note', '')}"
                )
                chunks.append((text, "relationship", 0.8))

        # Find this avatar's update notes
        for upd in result.avatar_updates:
            if upd.avatar_name and upd.notes:
                chunks.append((upd.notes, "event", 0.9))

        if result.summary_text:
            chunks.append((result.summary_text, "session_summary", 0.8))

        return chunks


# Module-level singleton
_summariser_instance: SessionSummariser | None = None


def get_summariser() -> SessionSummariser:
    global _summariser_instance
    if _summariser_instance is None:
        _summariser_instance = SessionSummariser()
    return _summariser_instance
