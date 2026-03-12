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
from datetime import datetime, timezone
from typing import Any

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

    result_obj = SummaryResult(
        events=sj.get("events", []) or [],
        npcs=sj.get("npcs", []) or [],
        items=sj.get("items", []) or [],
        relationship_deltas=sj.get("relationship_deltas", []) or [],
        avatar_updates=avatar_updates,
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

    # Mark as approved
    summary_row.is_approved = True
    summary_row.reviewed_at = datetime.now(timezone.utc)
    await db.commit()

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
