"""
Pipeline control API.

POST /api/pipeline/{session_id}/start  — start mic capture for a session
POST /api/pipeline/{session_id}/stop   — stop mic capture
GET  /api/pipeline/{session_id}/status — check if pipeline is running
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.models.session import Session
from app.models.avatar import Avatar
from app.services.pipeline_manager import pipeline_manager
from app.routers.websocket import manager as ws_manager

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/{session_id}/start")
async def start_pipeline(session_id: int, db: AsyncSession = Depends(get_db)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.is_active:
        raise HTTPException(status_code=400, detail="Session has ended")

    if pipeline_manager.is_running(session_id):
        return {"status": "already_running", "session_id": session_id}

    # Fetch avatar details
    avatar_ids = session.avatar_ids or []
    avatar_names: dict[int, str] = {}
    avatar_modes: dict[int, str] = {}

    avatar_embeddings: dict[int, str] = {}

    if avatar_ids:
        result = await db.execute(
            select(Avatar).where(Avatar.id.in_(avatar_ids))
        )
        for avatar in result.scalars().all():
            avatar_names[avatar.id] = avatar.name
            # Session overrides avatar's default mode if set
            mode = session.avatar_modes.get(str(avatar.id), avatar.mode)
            avatar_modes[avatar.id] = mode
            if avatar.voice_embedding_path:
                avatar_embeddings[avatar.id] = avatar.voice_embedding_path

    async def broadcast_entry(entry):
        """Broadcast a TranscriptEntry (from AudioPipeline)."""
        await ws_manager.broadcast_transcript(session_id, entry)

    async def broadcast_dict(msg: dict):
        """Broadcast a raw dict (from AudioOutputManager / PresenceLayer)."""
        await ws_manager.broadcast(msg)

    await pipeline_manager.start(
        session_id=session_id,
        avatar_ids=avatar_ids,
        avatar_names=avatar_names,
        avatar_modes=avatar_modes,
        broadcast_fn=broadcast_entry,
        broadcast_dict_fn=broadcast_dict,
        avatar_embeddings=avatar_embeddings,
    )

    await ws_manager.broadcast_pipeline_status(session_id, "started")
    return {"status": "started", "session_id": session_id}


@router.post("/{session_id}/stop")
async def stop_pipeline(session_id: int):
    if not pipeline_manager.is_running(session_id):
        return {"status": "not_running", "session_id": session_id}

    await pipeline_manager.stop(session_id)
    await ws_manager.broadcast_pipeline_status(session_id, "stopped")
    return {"status": "stopped", "session_id": session_id}


@router.get("/{session_id}/status")
async def pipeline_status(session_id: int):
    return {
        "session_id": session_id,
        "running": pipeline_manager.is_running(session_id),
    }
