from sqlalchemy import Column, Integer, String, Text, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.db.database import Base


class CharacterTrait(Base):
    """
    A psychological trait an avatar has developed from campaign events.

    Traits emerge from significant experiences (trauma, betrayal, near-death),
    strengthen when reinforced, and fade if not triggered for several weeks.
    They manifest probabilistically — a frightened character doesn't always
    flinch at spiders, but sometimes does.
    """
    __tablename__ = "character_traits"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    avatar_id = Column(Integer, ForeignKey("avatars.id"), nullable=False, index=True)

    # Identity
    trait_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # Strength and decay
    current_strength = Column(Float, nullable=False, default=0.5)   # 0.0–1.0
    last_reinforced_at = Column(DateTime(timezone=True), server_default=func.now())

    # Manifestation
    manifestation_probability = Column(Float, nullable=False, default=0.3)
    trigger_keywords = Column(Text, nullable=True)   # JSON list: ["spider", "webbing"]
    emotional_signature = Column(String(50), nullable=True)  # "tense" | "frightened" | etc.

    # Provenance
    onset_session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True)

    # State
    is_resolved = Column(Boolean, nullable=False, default=False)   # strength < 0.1
    is_positive = Column(Boolean, nullable=False, default=False)   # gratitude vs fear
