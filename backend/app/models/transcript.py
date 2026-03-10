from sqlalchemy import Column, Integer, String, Text, Float, ForeignKey, DateTime, JSON
from sqlalchemy.sql import func
from app.db.database import Base


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)

    # Speaker identification
    speaker = Column(String(100), nullable=False)   # "DM", avatar name, or "Unknown"
    speaker_type = Column(String(20), nullable=False, default="human")  # human | avatar | dm

    # Content
    text = Column(Text, nullable=False)

    # Metadata
    utterance_type = Column(String(30), nullable=False, default="speech")
    # speech | backchannel | holding_phrase | overlap | inaudible

    confidence = Column(Float, nullable=True)
    audio_start_ms = Column(Integer, nullable=True)
    audio_end_ms = Column(Integer, nullable=True)

    # LLM context (for avatar utterances)
    llm_model = Column(String(50), nullable=True)    # ollama | claude
    context_type = Column(String(50), nullable=True) # combat | roleplay | emotional | etc.
    interrupt_score = Column(Float, nullable=True)

    # Extra metadata
    meta = Column(JSON, nullable=True, default=dict)
