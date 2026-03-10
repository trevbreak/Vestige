from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


class AvatarBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    player_name: str = Field(..., min_length=1, max_length=100)
    race: str = "Human"
    char_class: str = "Fighter"
    level: int = Field(1, ge=1, le=20)
    background: Optional[str] = None
    alignment: Optional[str] = None

    strength: int = Field(10, ge=1, le=30)
    dexterity: int = Field(10, ge=1, le=30)
    constitution: int = Field(10, ge=1, le=30)
    intelligence: int = Field(10, ge=1, le=30)
    wisdom: int = Field(10, ge=1, le=30)
    charisma: int = Field(10, ge=1, le=30)

    hit_points_max: int = Field(10, ge=1)
    hit_points_current: int = Field(10, ge=0)
    armor_class: int = Field(10, ge=1)
    speed: int = Field(30, ge=0)
    proficiency_bonus: int = Field(2, ge=2, le=6)

    backstory: Optional[str] = None
    personality_traits: Optional[str] = None
    ideals: Optional[str] = None
    bonds: Optional[str] = None
    flaws: Optional[str] = None

    sentence_style: Optional[str] = None
    verbal_tics: Optional[str] = None
    never_say: Optional[str] = None

    skill_proficiencies: Optional[list[str]] = []
    spells_known: Optional[dict[str, Any]] = {}
    spell_slots: Optional[dict[str, Any]] = {}
    equipment: Optional[list[str]] = []

    mode: str = "active"
    relationships: Optional[dict[str, str]] = {}


class AvatarCreate(AvatarBase):
    pass


class AvatarUpdate(BaseModel):
    """All fields optional for partial updates."""
    name: Optional[str] = None
    player_name: Optional[str] = None
    race: Optional[str] = None
    char_class: Optional[str] = None
    level: Optional[int] = None
    background: Optional[str] = None
    alignment: Optional[str] = None

    strength: Optional[int] = None
    dexterity: Optional[int] = None
    constitution: Optional[int] = None
    intelligence: Optional[int] = None
    wisdom: Optional[int] = None
    charisma: Optional[int] = None

    hit_points_max: Optional[int] = None
    hit_points_current: Optional[int] = None
    armor_class: Optional[int] = None
    speed: Optional[int] = None
    proficiency_bonus: Optional[int] = None

    backstory: Optional[str] = None
    personality_traits: Optional[str] = None
    ideals: Optional[str] = None
    bonds: Optional[str] = None
    flaws: Optional[str] = None

    sentence_style: Optional[str] = None
    verbal_tics: Optional[str] = None
    never_say: Optional[str] = None
    voice_embedding_path: Optional[str] = None

    skill_proficiencies: Optional[list[str]] = None
    spells_known: Optional[dict[str, Any]] = None
    spell_slots: Optional[dict[str, Any]] = None
    equipment: Optional[list[str]] = None

    mode: Optional[str] = None
    relationships: Optional[dict[str, str]] = None
    is_active: Optional[bool] = None


class AvatarResponse(AvatarBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    portrait_path: Optional[str] = None
    voice_sample_path: Optional[str] = None
    voice_embedding_path: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}
