from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from pydantic import BaseModel
from app.db.database import get_db
from app.models.session import Session
from app.schemas.session import SessionCreate, SessionUpdate, SessionResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/", response_model=list[SessionResponse])
async def list_sessions(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Session)
    if active_only:
        stmt = stmt.where(Session.is_active == True)  # noqa: E712
    stmt = stmt.order_by(Session.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    session_in: SessionCreate,
    db: AsyncSession = Depends(get_db),
):
    session = Session(**session_in.model_dump())
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: int, db: AsyncSession = Depends(get_db)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: int,
    session_in: SessionUpdate,
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    update_data = session_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(session, field, value)

    await db.commit()
    await db.refresh(session)
    return session


@router.post("/{session_id}/end", response_model=SessionResponse)
async def end_session(session_id: int, db: AsyncSession = Depends(get_db)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.is_active = False
    session.ended_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(session)
    return session


# ── Phase 5: Speaker attribution ───────────────────────────────────────────────

class SpeakerAttributionRequest(BaseModel):
    """Map raw speaker labels ("Speaker 0") to player names or "DM"."""
    attributions: dict[str, str]   # {"Speaker 0": "Alice", "Speaker 1": "DM", ...}


class SpeakerAttributionResponse(BaseModel):
    session_id: int
    updated_count: int


@router.post("/{session_id}/speakers", response_model=SpeakerAttributionResponse)
async def attribute_speakers(
    session_id: int,
    body: SpeakerAttributionRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Relabel transcript entries whose speaker matches a key in body.attributions.
    Intended for post-session diarization review.

    Example: {"Speaker 0": "Alice", "Unknown": "Bob"}
    """
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    from app.models.transcript import Transcript
    result = await db.execute(
        select(Transcript).where(Transcript.session_id == session_id)
    )
    rows = result.scalars().all()

    updated = 0
    for row in rows:
        new_name = body.attributions.get(row.speaker)
        if new_name and new_name != row.speaker:
            row.speaker = new_name
            # Update speaker_type based on conventional labels
            lower = new_name.lower()
            if lower == "dm":
                row.speaker_type = "dm"
            else:
                row.speaker_type = "human"
            updated += 1

    await db.commit()
    return SpeakerAttributionResponse(session_id=session_id, updated_count=updated)
