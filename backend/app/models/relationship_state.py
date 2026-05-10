from sqlalchemy import Column, Integer, String, Text, Float, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.db.database import Base


class RelationshipState(Base):
    """
    Structured relationship axes between an avatar and a target (avatar or NPC).

    Replaces the freetext JSON relationships field with quantified values that
    can be updated by the summariser and read by the prompt builder.
    """
    __tablename__ = "relationship_states"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    avatar_a_id = Column(Integer, ForeignKey("avatars.id"), nullable=False, index=True)
    avatar_b_id = Column(Integer, ForeignKey("avatars.id"), nullable=True, index=True)
    target_name = Column(String(100), nullable=True)   # used when target is an NPC

    # Relationship axes (all 0.0–1.0 or -1.0–1.0)
    trust = Column(Float, nullable=False, default=0.5)        # 0=betrayed, 1=blind trust
    affection = Column(Float, nullable=False, default=0.0)    # -1=hostile, 0=neutral, 1=close bond
    respect = Column(Float, nullable=False, default=0.5)      # 0=contempt, 1=admiration

    # Key moments that shaped this relationship
    key_moments = Column(Text, nullable=True)   # JSON list of event strings

    last_updated_session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True)
