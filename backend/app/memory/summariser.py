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

Phase 5 additions:
  - TraitDelta / RelationshipDelta: structured extraction of psychological events
  - Layered summary context: previous N summaries injected for continuity
  - summary_method: "facts" | "short" | "balanced" | "long" depth config
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
    hp_delta: int = 0
    spell_slots_used: dict[str, int] = field(default_factory=dict)
    items_gained: list[str] = field(default_factory=list)
    items_lost: list[str] = field(default_factory=list)
    conditions_gained: list[str] = field(default_factory=list)
    conditions_cleared: list[str] = field(default_factory=list)
    xp_gained: int = 0
    notes: str = ""


@dataclass
class TraitDelta:
    """A trait created, reinforced, or weakened by session events."""
    avatar_name: str
    trait_name: str
    description: str = ""
    strength_change: float = 0.5    # positive = new/strengthening; negative = weakening
    trigger_keywords: list[str] = field(default_factory=list)
    emotional_signature: str = ""   # "tense" | "frightened" | "wary" | "protective" etc.
    is_positive: bool = False       # gratitude/loyalty vs fear/distrust


@dataclass
class RelationshipDelta:
    """Quantified relationship shift between two characters."""
    avatar_name: str
    target_name: str
    trust_delta: float = 0.0       # -0.5=betrayal, +0.2=saved from death
    affection_delta: float = 0.0   # -0.3=conflict, +0.15=shared vulnerability
    respect_delta: float = 0.0     # +0.2=witnessed skill, -0.2=cowardice
    reason: str = ""


@dataclass
class SummaryResult:
    """Result of a summarisation call."""
    # Structured data
    events: list[str] = field(default_factory=list)
    npcs: list[dict[str, str]] = field(default_factory=list)
    items: list[dict[str, str]] = field(default_factory=list)
    relationship_deltas: list[dict[str, str]] = field(default_factory=list)
    avatar_updates: list[AvatarUpdate] = field(default_factory=list)

    # Phase 5: psychological / relationship evolution
    trait_deltas: list[TraitDelta] = field(default_factory=list)
    relationship_deltas_structured: list[RelationshipDelta] = field(default_factory=list)

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
            "trait_deltas": [
                {
                    "avatar_name": t.avatar_name,
                    "trait_name": t.trait_name,
                    "description": t.description,
                    "strength_change": t.strength_change,
                    "trigger_keywords": t.trigger_keywords,
                    "emotional_signature": t.emotional_signature,
                    "is_positive": t.is_positive,
                }
                for t in self.trait_deltas
            ],
            "relationship_deltas_structured": [
                {
                    "avatar_name": r.avatar_name,
                    "target_name": r.target_name,
                    "trust_delta": r.trust_delta,
                    "affection_delta": r.affection_delta,
                    "respect_delta": r.respect_delta,
                    "reason": r.reason,
                }
                for r in self.relationship_deltas_structured
            ],
        }


# ── Prompt templates ───────────────────────────────────────────────────────────

_SUMMARY_DEPTH_INSTRUCTIONS = {
    "facts": "Respond with ONLY bullet-point facts. Minimal prose. Dense, terse.",
    "short": "Write a 2–3 sentence prose summary.",
    "balanced": "Write a 4–6 sentence prose summary with emotional context. Default depth.",
    "long": "Write a full narrative paragraph with character voice and vivid detail.",
}


def _build_post_session_system(summary_method: str) -> str:
    depth_instr = _SUMMARY_DEPTH_INSTRUCTIONS.get(summary_method, _SUMMARY_DEPTH_INSTRUCTIONS["balanced"])
    return f"""You are a tabletop RPG session analyst. You will be given a full session transcript.

Extract the following information as valid JSON (no markdown, no backticks, just raw JSON):

{{
  "events": ["Short description of major plot events, 1 per item, max 10"],
  "npcs": [{{"name": "NPC name", "notes": "What happened / relationship to party"}}],
  "items": [{{"name": "Item name", "owner": "Character name", "notes": "How obtained/used"}}],
  "relationship_deltas": [{{"avatar": "Avatar name", "target": "Other character or NPC", "note": "How the relationship changed"}}],
  "avatar_updates": [
    {{
      "avatar_name": "Name",
      "hp_delta": 0,
      "spell_slots_used": {{}},
      "items_gained": [],
      "items_lost": [],
      "conditions_gained": [],
      "conditions_cleared": [],
      "xp_gained": 0,
      "notes": "Anything important for this character"
    }}
  ],
  "trait_deltas": [
    {{
      "avatar_name": "Name",
      "trait_name": "Short trait label (e.g. arachnophobia, trust_deficit_orik)",
      "description": "What happened and why this trait emerged",
      "strength_change": 0.6,
      "trigger_keywords": ["keyword1", "keyword2"],
      "emotional_signature": "tense",
      "is_positive": false
    }}
  ],
  "relationship_deltas_structured": [
    {{
      "avatar_name": "Name",
      "target_name": "Other character",
      "trust_delta": 0.0,
      "affection_delta": 0.0,
      "respect_delta": 0.0,
      "reason": "Brief explanation"
    }}
  ],
  "summary_text": "Session summary."
}}

For trait_deltas: only include genuine psychological impact from significant events
(near-death, betrayal, trauma, repeated failure). NOT routine combat. Be conservative
(0–2 per session). strength_change: +0.5 to +0.8 for new trait, -0.1 to -0.3 for
weakening. emotional_signature must be one of: tense, frightened, wary, distrustful,
protective, warmly, resolute, excited.

For relationship_deltas_structured: trust_delta: -0.5=betrayal, +0.2=saved from death,
+0.1=reliability. affection_delta: -0.3=conflict, +0.15=vulnerability. respect_delta:
+0.2=witnessed skill, -0.2=cowardice.

summary_text depth: {depth_instr}

Respond with ONLY valid JSON. If you cannot determine a value, use null or empty list."""


_ROLLING_SUMMARY_SYSTEM = """You are a tabletop RPG session scribe. Condense the following transcript excerpt into a short, dense summary (3–5 sentences) suitable for inclusion in a future LLM context window. Focus on plot events, character decisions, and combat outcomes. Do NOT include mundane small-talk. Write in past tense."""


# ── Summariser class ───────────────────────────────────────────────────────────

class SessionSummariser:
    """
    Calls Claude to summarise session transcripts.
    Synchronous — intended to run in an asyncio thread pool executor.
    """

    def __init__(self, model: str | None = None, max_tokens: int = 1500):
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
        previous_summaries: list[str] | None = None,   # Phase 5: layered context
        summary_method: str = "balanced",               # Phase 5: depth config
    ) -> SummaryResult:
        """
        Full post-session summary. Takes a list of "Speaker: text" strings.
        Returns a SummaryResult. If Claude is unavailable, returns a stub.

        previous_summaries: list of prior session summary_text strings (oldest first).
        Injected as context so the summariser can reference campaign history.
        """
        if not transcript_lines:
            return SummaryResult(
                summary_text="No transcript available.",
                error="empty_transcript",
            )

        # Phase 5: layered summary context — inject prior summaries for continuity
        history_context = ""
        if previous_summaries:
            history_context = "== PREVIOUS CAMPAIGN HISTORY (oldest to most recent) ==\n"
            history_context += "\n\n".join(previous_summaries)
            history_context += "\n\n"

        transcript_text = "\n".join(transcript_lines[-500:])  # cap at 500 lines
        avatars_note = ""
        if avatar_names:
            avatars_note = f"Avatars in this session: {', '.join(avatar_names)}\n\n"

        user_msg = f"{history_context}{avatars_note}== TRANSCRIPT ==\n{transcript_text}"

        system = _build_post_session_system(summary_method)
        raw, latency = self._call_claude(system, user_msg)

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
            import re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    data = {}
            else:
                data = {}

        # Parse avatar_updates
        avatar_updates = []
        for u in data.get("avatar_updates", []):
            if not isinstance(u, dict):
                continue
            avatar_updates.append(AvatarUpdate(
                avatar_id=0,
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

        # Phase 5: parse trait_deltas
        trait_deltas = []
        for t in data.get("trait_deltas", []) or []:
            if not isinstance(t, dict) or not t.get("avatar_name"):
                continue
            trait_deltas.append(TraitDelta(
                avatar_name=t.get("avatar_name", ""),
                trait_name=t.get("trait_name", ""),
                description=t.get("description", ""),
                strength_change=float(t.get("strength_change", 0.5)),
                trigger_keywords=t.get("trigger_keywords", []) or [],
                emotional_signature=t.get("emotional_signature", ""),
                is_positive=bool(t.get("is_positive", False)),
            ))

        # Phase 5: parse relationship_deltas_structured
        rel_deltas_structured = []
        for r in data.get("relationship_deltas_structured", []) or []:
            if not isinstance(r, dict) or not r.get("avatar_name"):
                continue
            rel_deltas_structured.append(RelationshipDelta(
                avatar_name=r.get("avatar_name", ""),
                target_name=r.get("target_name", ""),
                trust_delta=float(r.get("trust_delta", 0.0)),
                affection_delta=float(r.get("affection_delta", 0.0)),
                respect_delta=float(r.get("respect_delta", 0.0)),
                reason=r.get("reason", ""),
            ))

        return SummaryResult(
            events=data.get("events", []) or [],
            npcs=data.get("npcs", []) or [],
            items=data.get("items", []) or [],
            relationship_deltas=data.get("relationship_deltas", []) or [],
            avatar_updates=avatar_updates,
            trait_deltas=trait_deltas,
            relationship_deltas_structured=rel_deltas_structured,
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
        Convert a SummaryResult into (text, chunk_type, importance) tuples
        ready to be embedded and stored.
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

        for upd in result.avatar_updates:
            if upd.avatar_name and upd.notes:
                chunks.append((upd.notes, "event", 0.9))

        # Phase 5: trait summaries as memory
        for td in result.trait_deltas:
            if td.trait_name and td.description:
                text = f"{td.avatar_name} — trait: {td.trait_name}: {td.description}"
                chunks.append((text, "relationship", 0.85))

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
