from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.models.transcript import Transcript
from app.schemas.transcript import TranscriptCreate, TranscriptResponse

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


@router.get("/session/{session_id}", response_model=list[TranscriptResponse])
async def get_session_transcripts(
    session_id: int,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Transcript)
        .where(Transcript.session_id == session_id)
        .order_by(Transcript.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=TranscriptResponse)
async def create_transcript(
    entry: TranscriptCreate,
    db: AsyncSession = Depends(get_db),
):
    transcript = Transcript(**entry.model_dump())
    db.add(transcript)
    await db.commit()
    await db.refresh(transcript)
    return transcript
