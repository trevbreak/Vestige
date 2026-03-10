from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


class TranscriptCreate(BaseModel):
    session_id: int
    speaker: str
    speaker_type: str = "human"
    text: str
    utterance_type: str = "speech"
    confidence: Optional[float] = None
    audio_start_ms: Optional[int] = None
    audio_end_ms: Optional[int] = None
    llm_model: Optional[str] = None
    context_type: Optional[str] = None
    interrupt_score: Optional[float] = None
    meta: Optional[dict[str, Any]] = {}


class TranscriptResponse(TranscriptCreate):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}
