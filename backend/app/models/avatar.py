from sqlalchemy import Column, Integer, String, Text, Float, Boolean, JSON, DateTime
from sqlalchemy.sql import func
from app.db.database import Base


class Avatar(Base):
    __tablename__ = "avatars"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Identity
    name = Column(String(100), nullable=False)
    player_name = Column(String(100), nullable=False)
    portrait_path = Column(String(500), nullable=True)

    # Character Sheet
    race = Column(String(50), nullable=False, default="Human")
    char_class = Column(String(50), nullable=False, default="Fighter")
    level = Column(Integer, nullable=False, default=1)
    background = Column(String(50), nullable=True)
    alignment = Column(String(20), nullable=True)

    # Ability scores
    strength = Column(Integer, nullable=False, default=10)
    dexterity = Column(Integer, nullable=False, default=10)
    constitution = Column(Integer, nullable=False, default=10)
    intelligence = Column(Integer, nullable=False, default=10)
    wisdom = Column(Integer, nullable=False, default=10)
    charisma = Column(Integer, nullable=False, default=10)

    # Combat stats
    hit_points_max = Column(Integer, nullable=False, default=10)
    hit_points_current = Column(Integer, nullable=False, default=10)
    armor_class = Column(Integer, nullable=False, default=10)
    speed = Column(Integer, nullable=False, default=30)
    proficiency_bonus = Column(Integer, nullable=False, default=2)

    # Personality
    backstory = Column(Text, nullable=True)
    personality_traits = Column(Text, nullable=True)
    ideals = Column(Text, nullable=True)
    bonds = Column(Text, nullable=True)
    flaws = Column(Text, nullable=True)

    # Voice / AI config
    sentence_style = Column(String(200), nullable=True)  # e.g. "short declarative bursts"
    verbal_tics = Column(Text, nullable=True)             # e.g. "often invokes their deity"
    never_say = Column(Text, nullable=True)               # newline-separated list
    voice_sample_path = Column(String(500), nullable=True)
    voice_embedding_path = Column(String(500), nullable=True)  # path to .npz speaker embedding

    # Phase 8: LLM-generated persona
    personality_prompt = Column(Text, nullable=True)           # rich first-person persona description
    verbosity = Column(Float, nullable=False, default=0.5)     # 0.0=silent, 1.0=talks constantly
    interrupts_often = Column(Boolean, nullable=False, default=False)
    personality_archetype = Column(String(20), nullable=False, default="extrovert")
    # valid: introvert | extrovert | reactive | stoic
    holding_phrase_chance = Column(Float, nullable=False, default=0.5)

    # Phase 8: Edge-TTS voice
    voice_id = Column(String(100), nullable=True)              # e.g. "en-GB-RyanNeural"
    tts_engine_preference = Column(String(20), nullable=False, default="auto")
    # auto | xtts | edge

    # ElevenLabs voice config (audio revamp)
    elevenlabs_voice_id = Column(String(100), nullable=True)   # ElevenLabs voice UUID
    elevenlabs_voice_params = Column(JSON, nullable=True)       # {stability, similarity_boost, style, use_speaker_boost}
    elevenlabs_model_preference = Column(String(30), nullable=False, default="eleven_v3")
    # eleven_v3 (emotional, audio tags) | eleven_flash_v2_5 (fast, no tags)

    # Skills (JSON list of proficient skills)
    skill_proficiencies = Column(JSON, nullable=True, default=list)

    # Spells (JSON)
    spells_known = Column(JSON, nullable=True, default=dict)
    spell_slots = Column(JSON, nullable=True, default=dict)

    # Equipment (JSON list)
    equipment = Column(JSON, nullable=True, default=list)

    # Session mode
    mode = Column(String(20), nullable=False, default="active")  # active | passive | absent

    # Party relationships (JSON dict: avatar_name -> relationship_note)
    relationships = Column(JSON, nullable=True, default=dict)

    # Active/archived
    is_active = Column(Boolean, nullable=False, default=True)
