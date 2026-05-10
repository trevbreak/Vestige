"""
Memory API Router — Phase 5.

Endpoints:
  POST /api/memory/sessions/{session_id}/summarise
      Generate a post-session summary via Claude. Creates/overwrites SessionSummary.

  GET  /api/memory/sessions/{session_id}/summary
      Return the stored SessionSummary for a session.

  POST /api/memory/sessions/{session_id}/approve
      DM approves the summary; triggers embedding + MemoryChunk storage.

  GET  /api/memory/avatars/{avatar_id}/chunks
      List all MemoryChunks for an avatar.

  DELETE /api/memory/chunks/{chunk_id}
      Soft-delete a MemoryChunk.

  POST /api/memory/sessions/{session_id}/rolling-summary
      Generate a rolling mid-session summary from recent transcript lines.
"""

from __future__ import annotations

import asyncio
import structlog
from datetime import datetime, timezone
from typing import Any

log = structlog.get_logger()

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db

router = APIRouter(prefix="/memory", tags=["memory"])


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class SummariseRequest(BaseModel):
    avatar_ids: list[int] | None = None   # to look up avatar names; optional


class SummariseResponse(BaseModel):
    session_id: int
    summary_id: int
    summary_text: str
    event_count: int
    npc_count: int
    item_count: int
    relationship_count: int
    avatar_update_count: int
    model: str
    latency_ms: float
    error: str = ""


class SummaryDetailResponse(BaseModel):
    id: int
    session_id: int
    summary_text: str | None
    summary_json: dict[str, Any] | None
    is_approved: bool
    rolling_summaries: list[Any]


class ApproveResponse(BaseModel):
    session_id: int
    chunks_created: int


class ChunkResponse(BaseModel):
    id: int
    avatar_id: int
    session_id: int | None
    text: str
    chunk_type: str
    importance: float
    is_active: bool
    created_at: str


class RollingSummaryRequest(BaseModel):
    transcript_lines: list[str]


class RollingSummaryResponse(BaseModel):
    session_id: int
    summary_text: str


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_session_or_404(session_id: int, db: AsyncSession):
    from app.models.session import Session
    sess = await db.get(Session, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    return sess


async def _fetch_transcript_lines(session_id: int, db: AsyncSession) -> list[str]:
    """Return all transcript lines for a session as 'Speaker: text' strings."""
    from sqlalchemy import select
    from app.models.transcript import Transcript
    result = await db.execute(
        select(Transcript)
        .where(Transcript.session_id == session_id)
        .order_by(Transcript.created_at)
    )
    rows = result.scalars().all()
    return [f"{r.speaker}: {r.text}" for r in rows if r.text]


async def _fetch_avatar_names(session_id: int, db: AsyncSession) -> list[str]:
    from app.models.session import Session
    from app.models.avatar import Avatar
    sess = await db.get(Session, session_id)
    if not sess or not sess.avatar_ids:
        return []
    names = []
    for aid in sess.avatar_ids:
        av = await db.get(Avatar, aid)
        if av:
            names.append(av.name)
    return names


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/summarise", response_model=SummariseResponse)
async def summarise_session(
    session_id: int,
    body: SummariseRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a post-session summary via Claude and store it as SessionSummary.
    Safe to call multiple times — overwrites previous unapproved summary.
    """
    await _get_session_or_404(session_id, db)

    transcript_lines = await _fetch_transcript_lines(session_id, db)
    avatar_names = await _fetch_avatar_names(session_id, db)

    # Run summariser in thread pool (blocking Claude call)
    from app.memory.summariser import get_summariser
    summariser = get_summariser()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: summariser.post_session(transcript_lines, avatar_names),
    )

    # Upsert SessionSummary
    from app.models.memory import SessionSummary
    from sqlalchemy import select as sa_select

    existing = await db.execute(
        sa_select(SessionSummary).where(SessionSummary.session_id == session_id)
    )
    summary_row = existing.scalar_one_or_none()

    if summary_row is None:
        summary_row = SessionSummary(session_id=session_id)
        db.add(summary_row)

    summary_row.summary_json = result.to_json()
    summary_row.summary_text = result.summary_text
    summary_row.is_approved = False  # reset on re-generate

    await db.commit()
    await db.refresh(summary_row)

    return SummariseResponse(
        session_id=session_id,
        summary_id=summary_row.id,
        summary_text=result.summary_text,
        event_count=len(result.events),
        npc_count=len(result.npcs),
        item_count=len(result.items),
        relationship_count=len(result.relationship_deltas),
        avatar_update_count=len(result.avatar_updates),
        model=result.model,
        latency_ms=result.latency_ms,
        error=result.error,
    )


@router.get("/sessions/{session_id}/summary", response_model=SummaryDetailResponse)
async def get_session_summary(
    session_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return the stored SessionSummary (pending DM review)."""
    await _get_session_or_404(session_id, db)

    from app.models.memory import SessionSummary
    result = await db.execute(
        select(SessionSummary).where(SessionSummary.session_id == session_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No summary found for this session")

    return SummaryDetailResponse(
        id=row.id,
        session_id=row.session_id,
        summary_text=row.summary_text,
        summary_json=row.summary_json,
        is_approved=row.is_approved,
        rolling_summaries=row.rolling_summaries or [],
    )


@router.post("/sessions/{session_id}/approve", response_model=ApproveResponse)
async def approve_summary(
    session_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    DM approves the session summary.
    Triggers embedding of all summary chunks and stores them as MemoryChunks.
    """
    await _get_session_or_404(session_id, db)

    from app.models.memory import SessionSummary
    result = await db.execute(
        select(SessionSummary).where(SessionSummary.session_id == session_id)
    )
    summary_row = result.scalar_one_or_none()
    if summary_row is None:
        raise HTTPException(status_code=404, detail="No summary to approve")
    if summary_row.is_approved:
        raise HTTPException(status_code=409, detail="Summary already approved")

    # Get session to find avatar IDs
    from app.models.session import Session
    from app.models.avatar import Avatar
    sess = await db.get(Session, session_id)
    avatar_id_map: dict[str, int] = {}
    if sess and sess.avatar_ids:
        for aid in sess.avatar_ids:
            av = await db.get(Avatar, int(aid))
            if av:
                avatar_id_map[av.name.lower()] = av.id

    # Reconstruct SummaryResult from stored JSON
    from app.memory.summariser import SummaryResult, AvatarUpdate, get_summariser
    sj = summary_row.summary_json or {}
    avatar_updates = []
    for u in sj.get("avatar_updates", []):
        au = AvatarUpdate(
            avatar_id=avatar_id_map.get((u.get("avatar_name") or "").lower(), 0),
            avatar_name=u.get("avatar_name", ""),
            hp_delta=u.get("hp_delta", 0) or 0,
            notes=u.get("notes", "") or "",
        )
        avatar_updates.append(au)

    from app.memory.summariser import TraitDelta, RelationshipDelta
    trait_deltas = []
    for t in sj.get("trait_deltas", []) or []:
        trait_deltas.append(TraitDelta(
            avatar_name=t.get("avatar_name", ""),
            trait_name=t.get("trait_name", ""),
            description=t.get("description", ""),
            strength_change=t.get("strength_change", 0.5),
            trigger_keywords=t.get("trigger_keywords", []),
            emotional_signature=t.get("emotional_signature", ""),
            is_positive=t.get("is_positive", False),
        ))
    rel_deltas_structured = []
    for r in sj.get("relationship_deltas_structured", []) or []:
        rel_deltas_structured.append(RelationshipDelta(
            avatar_name=r.get("avatar_name", ""),
            target_name=r.get("target_name", ""),
            trust_delta=r.get("trust_delta", 0.0),
            affection_delta=r.get("affection_delta", 0.0),
            respect_delta=r.get("respect_delta", 0.0),
            reason=r.get("reason", ""),
        ))

    result_obj = SummaryResult(
        events=sj.get("events", []) or [],
        npcs=sj.get("npcs", []) or [],
        items=sj.get("items", []) or [],
        relationship_deltas=sj.get("relationship_deltas", []) or [],
        avatar_updates=avatar_updates,
        trait_deltas=trait_deltas,
        relationship_deltas_structured=rel_deltas_structured,
        summary_text=summary_row.summary_text or "",
    )

    # Embed and store chunks for each avatar
    from app.memory.embedder import embedder
    from app.memory.store import MemoryStore
    store = MemoryStore()
    chunks_created = 0

    for avatar_id in (sess.avatar_ids or []):
        summariser = get_summariser()
        raw_chunks = summariser.chunks_from_result(result_obj, int(avatar_id), session_id)

        loop = asyncio.get_running_loop()
        texts = [t for t, _, _ in raw_chunks]
        importances = [imp for _, _, imp in raw_chunks]
        types = [ct for _, ct, _ in raw_chunks]

        # Embed in thread pool
        embeddings = await loop.run_in_executor(None, lambda: embedder.embed_batch(texts))

        for text, emb, chunk_type, importance in zip(texts, embeddings, types, importances):
            await store.upsert(
                db=db,
                avatar_id=int(avatar_id),
                text=text,
                embedding=emb,
                chunk_type=chunk_type,
                importance=importance,
                session_id=session_id,
            )
            chunks_created += 1

    # Apply trait deltas — create/update CharacterTrait records
    from app.models.character_trait import CharacterTrait
    from app.models.relationship_state import RelationshipState
    from datetime import datetime, timezone as _tz
    traits_applied = 0
    for td in result_obj.trait_deltas:
        a_id = avatar_id_map.get(td.avatar_name.lower())
        if not a_id:
            continue
        existing_trait = await db.execute(
            select(CharacterTrait).where(
                CharacterTrait.avatar_id == a_id,
                CharacterTrait.trait_name == td.trait_name,
            )
        )
        trait_row = existing_trait.scalar_one_or_none()
        if trait_row:
            trait_row.current_strength = max(0.0, min(1.0, trait_row.current_strength + td.strength_change))
            trait_row.last_reinforced_at = datetime.now(_tz.utc)
            if td.description and not trait_row.description:
                trait_row.description = td.description
        else:
            import json as _json
            trait_row = CharacterTrait(
                avatar_id=a_id,
                trait_name=td.trait_name,
                description=td.description,
                current_strength=max(0.0, min(1.0, td.strength_change)),
                last_reinforced_at=datetime.now(_tz.utc),
                manifestation_probability=0.3,
                trigger_keywords=_json.dumps(td.trigger_keywords) if td.trigger_keywords else None,
                emotional_signature=td.emotional_signature or None,
                onset_session_id=session_id,
                is_resolved=False,
                is_positive=td.is_positive,
            )
            db.add(trait_row)
        traits_applied += 1

    # Apply relationship deltas — create/update RelationshipState records
    rels_applied = 0
    for rd in result_obj.relationship_deltas_structured:
        a_id = avatar_id_map.get(rd.avatar_name.lower())
        if not a_id:
            continue
        b_id = avatar_id_map.get(rd.target_name.lower())
        existing_rel = await db.execute(
            select(RelationshipState).where(
                RelationshipState.avatar_a_id == a_id,
                RelationshipState.target_name == rd.target_name if not b_id
                else RelationshipState.avatar_b_id == b_id,
            )
        )
        rel_row = existing_rel.scalar_one_or_none()
        if rel_row:
            rel_row.trust = max(0.0, min(1.0, rel_row.trust + rd.trust_delta))
            rel_row.affection = max(-1.0, min(1.0, rel_row.affection + rd.affection_delta))
            rel_row.respect = max(0.0, min(1.0, rel_row.respect + rd.respect_delta))
            rel_row.last_updated_session_id = session_id
            if rd.reason:
                import json as _json2
                moments = _json2.loads(rel_row.key_moments or "[]")
                moments.append(rd.reason)
                rel_row.key_moments = _json2.dumps(moments[-10:])  # keep last 10
        else:
            import json as _json3
            rel_row = RelationshipState(
                avatar_a_id=a_id,
                avatar_b_id=b_id,
                target_name=rd.target_name,
                trust=max(0.0, min(1.0, 0.5 + rd.trust_delta)),
                affection=max(-1.0, min(1.0, 0.0 + rd.affection_delta)),
                respect=max(0.0, min(1.0, 0.5 + rd.respect_delta)),
                key_moments=_json3.dumps([rd.reason]) if rd.reason else None,
                last_updated_session_id=session_id,
            )
            db.add(rel_row)
        rels_applied += 1

    # Mark as approved
    summary_row.is_approved = True
    summary_row.reviewed_at = datetime.now(_tz.utc)
    await db.commit()

    log.info(
        "memory.approved",
        session_id=session_id,
        chunks=chunks_created,
        traits=traits_applied,
        relationships=rels_applied,
    )

    return ApproveResponse(session_id=session_id, chunks_created=chunks_created)


@router.get("/avatars/{avatar_id}/chunks", response_model=list[ChunkResponse])
async def list_chunks(
    avatar_id: int,
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """List all MemoryChunks for an avatar."""
    from app.models.avatar import Avatar
    av = await db.get(Avatar, avatar_id)
    if not av:
        raise HTTPException(status_code=404, detail="Avatar not found")

    from app.memory.store import MemoryStore
    store = MemoryStore()
    chunks = await store.list_chunks(db, avatar_id, include_inactive=include_inactive)

    return [
        ChunkResponse(
            id=c.id,
            avatar_id=c.avatar_id,
            session_id=c.session_id,
            text=c.text,
            chunk_type=c.chunk_type,
            importance=c.importance,
            is_active=c.is_active,
            created_at=c.created_at.isoformat() if c.created_at else "",
        )
        for c in chunks
    ]


@router.delete("/chunks/{chunk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chunk(
    chunk_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a MemoryChunk."""
    from app.memory.store import MemoryStore
    store = MemoryStore()
    deleted = await store.delete_chunk(db, chunk_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chunk not found")


@router.post("/sessions/{session_id}/rolling-summary", response_model=RollingSummaryResponse)
async def rolling_summary(
    session_id: int,
    body: RollingSummaryRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a rolling mid-session summary from the provided transcript lines.
    Appends the result to SessionSummary.rolling_summaries.
    Creates the SessionSummary row if it doesn't exist yet.
    """
    await _get_session_or_404(session_id, db)

    from app.memory.summariser import get_summariser
    summariser = get_summariser()
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(
        None,
        lambda: summariser.rolling_summary(body.transcript_lines),
    )

    # Append to rolling_summaries in DB
    from app.models.memory import SessionSummary
    result = await db.execute(
        select(SessionSummary).where(SessionSummary.session_id == session_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = SessionSummary(session_id=session_id, rolling_summaries=[])
        db.add(row)

    rolling = list(row.rolling_summaries or [])
    rolling.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "text": text,
    })
    row.rolling_summaries = rolling
    await db.commit()

    return RollingSummaryResponse(session_id=session_id, summary_text=text)
