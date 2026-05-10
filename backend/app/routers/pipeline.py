"""
Pipeline control API.

POST /api/pipeline/{session_id}/start  — start mic capture for a session
POST /api/pipeline/{session_id}/stop   — stop mic capture
GET  /api/pipeline/{session_id}/status — check if pipeline is running
"""

import traceback
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.models.session import Session
from app.models.avatar import Avatar
from app.services.pipeline_manager import pipeline_manager
from app.routers.websocket import manager as ws_manager

log = structlog.get_logger()

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
    avatar_profiles: dict[int, dict] = {}

    if avatar_ids:
        result = await db.execute(
            select(Avatar).where(Avatar.id.in_(avatar_ids))
        )
        for avatar in result.scalars().all():
            avatar_names[avatar.id] = avatar.name
            mode = session.avatar_modes.get(str(avatar.id), avatar.mode)
            avatar_modes[avatar.id] = mode
            if avatar.voice_embedding_path:
                avatar_embeddings[avatar.id] = avatar.voice_embedding_path
            # Snapshot avatar fields for prompt building (avoids DB access in hot path)
            avatar_profiles[avatar.id] = {
                "name": avatar.name,
                "race": avatar.race,
                "char_class": avatar.char_class,
                "level": avatar.level,
                "alignment": avatar.alignment or "",
                "background": avatar.background or "",
                "player_name": avatar.player_name,
                "personality_traits": avatar.personality_traits or "",
                "ideals": avatar.ideals or "",
                "bonds": avatar.bonds or "",
                "flaws": avatar.flaws or "",
                "sentence_style": avatar.sentence_style or "",
                "verbal_tics": avatar.verbal_tics or "",
                "never_say": avatar.never_say or "",
                "hit_points_current": avatar.hit_points_current,
                "hit_points_max": avatar.hit_points_max,
                "spell_slots": avatar.spell_slots or {},
                "relationships": avatar.relationships or {},
                # Phase 8: personality + voice fields
                "personality_prompt": avatar.personality_prompt or "",
                "verbosity": avatar.verbosity if avatar.verbosity is not None else 0.5,
                "interrupts_often": avatar.interrupts_often or False,
                "personality_archetype": avatar.personality_archetype or "extrovert",
                "holding_phrase_chance": avatar.holding_phrase_chance if avatar.holding_phrase_chance is not None else 0.5,
                "voice_id": avatar.voice_id,
                "tts_engine_preference": avatar.tts_engine_preference or "auto",
                # Phase 9: ElevenLabs voice config
                "elevenlabs_voice_id": avatar.elevenlabs_voice_id or "",
                "elevenlabs_voice_params": avatar.elevenlabs_voice_params,
                "elevenlabs_model_preference": avatar.elevenlabs_model_preference or "eleven_v3",
            }

    async def broadcast_entry(entry):
        """Broadcast a TranscriptEntry (from AudioPipeline)."""
        await ws_manager.broadcast_transcript(session_id, entry)

    async def broadcast_dict(msg: dict):
        """Broadcast a raw dict (from AudioOutputManager / PresenceLayer)."""
        await ws_manager.broadcast(msg)

    try:
        await pipeline_manager.start(
            session_id=session_id,
            avatar_ids=avatar_ids,
            avatar_names=avatar_names,
            avatar_modes=avatar_modes,
            broadcast_fn=broadcast_entry,
            broadcast_dict_fn=broadcast_dict,
            avatar_embeddings=avatar_embeddings,
            avatar_profiles=avatar_profiles,
        )
    except Exception as e:
        log.error("pipeline.start_failed", session_id=session_id, error=str(e), traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Pipeline start failed: {e}")

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
