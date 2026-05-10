from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel
from app.db.database import get_db
from app.models.avatar import Avatar
from app.schemas.avatar import AvatarCreate, AvatarUpdate, AvatarResponse
import shutil
import os
import json
import asyncio

import structlog
from app.llm.avatar_generator import generate_personality_data, VOICE_CATALOGUE

log = structlog.get_logger()

router = APIRouter(prefix="/avatars", tags=["avatars"])

UPLOAD_DIR = "data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.get("/", response_model=list[AvatarResponse])
async def list_avatars(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Avatar)
    if not include_inactive:
        stmt = stmt.where(Avatar.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    return result.scalars().all()


_RANDOMISE_SYSTEM = """You are a tabletop fantasy RPG character generator. Output ONLY a valid JSON object — no markdown, no explanation.

Rules:
- Level must be 1.
- Ability scores: roll 4d6 drop lowest for each, values between 3 and 18.
- Hit points: class hit die + CON modifier (minimum 1). Fighter d10, Barbarian d12, Paladin d10, Ranger d10, Cleric d8, Druid d8, Monk d8, Rogue d8, Bard d8, Warlock d8, Wizard d6, Sorcerer d6.
- Armor class: 10 + DEX modifier (unarmored), or class-appropriate starting AC.
- Speed: 30 ft (25 ft for Dwarf and Halfling).
- Proficiency bonus: 2 (always at level 1).
- Background must be a classic fantasy background (Acolyte, Criminal, Folk Hero, Noble, Outlander, Sage, Soldier, Charlatan, Entertainer, Guild Artisan, Hermit, Sailor, Urchin).
- Alignment must be one of: Lawful Good, Neutral Good, Chaotic Good, Lawful Neutral, True Neutral, Chaotic Neutral, Lawful Evil, Neutral Evil, Chaotic Evil.
- Race must be a classic fantasy race.
- Class must be a classic fantasy class.
- name: a fantasy name fitting the race.
- player_name: leave as "Randomised".
- personality_traits, ideals, bonds, flaws: short evocative sentences from the background table.
- backstory: 2-3 sentences of flavourful backstory.
- sentence_style: brief description of how this character speaks (e.g. "clipped military commands, never uses contractions").
- verbal_tics: one or two speech habits (e.g. "invokes Moradin, calls everyone 'friend'").
- never_say: comma-separated list of 3 words this character would never use.
- equipment: list of 3-5 starting items as strings.
- mode: "active".

Return this exact JSON shape and nothing else:
{
  "name": "...",
  "player_name": "Randomised",
  "race": "...",
  "char_class": "...",
  "level": 1,
  "background": "...",
  "alignment": "...",
  "strength": 0,
  "dexterity": 0,
  "constitution": 0,
  "intelligence": 0,
  "wisdom": 0,
  "charisma": 0,
  "hit_points_max": 0,
  "hit_points_current": 0,
  "armor_class": 0,
  "speed": 30,
  "proficiency_bonus": 2,
  "backstory": "...",
  "personality_traits": "...",
  "ideals": "...",
  "bonds": "...",
  "flaws": "...",
  "sentence_style": "...",
  "verbal_tics": "...",
  "never_say": "...",
  "equipment": [],
  "skill_proficiencies": [],
  "spells_known": {},
  "spell_slots": {},
  "relationships": {},
  "mode": "active"
}"""

_RANDOMISE_USER = "Generate a random tabletop fantasy RPG starting character. Output only the JSON."


@router.post("/randomise", response_model=AvatarCreate)
async def randomise_avatar():
    """
    Use GPT-4o to generate a random tabletop fantasy RPG starting character.
    Returns a populated AvatarCreate payload — does NOT save to the database.
    """
    from app.llm.router import call_gpt4o

    resp = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: call_gpt4o(
            system_prompt=_RANDOMISE_SYSTEM,
            user_message=_RANDOMISE_USER,
        ),
    )

    if resp.route == "stub" or not resp.text:
        raise HTTPException(
            status_code=503,
            detail=f"LLM unavailable or returned empty response: {resp.error}",
        )

    # Strip think-blocks emitted by reasoning models (e.g. deepseek-r1)
    raw = resp.text.strip()
    if "<think>" in raw:
        raw = raw.split("</think>", 1)[-1].strip()

    # Strip markdown fences (```json ... ``` or ``` ... ```)
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]           # drop the opening ```[lang] line
        raw = raw.rsplit("```", 1)[0]          # drop everything from the closing ``` onward

    # Extract the first JSON object in the response (in case of extra prose)
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise HTTPException(status_code=502, detail="Ollama response contained no JSON object")
    raw = raw[start:end]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Ollama returned invalid JSON: {exc}",
        )

    # Clamp / coerce values that Ollama occasionally gets wrong
    data["level"] = 1
    data["proficiency_bonus"] = 2
    for stat in ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"):
        data[stat] = max(3, min(int(data.get(stat, 10)), 18))
    data["hit_points_max"] = max(1, int(data.get("hit_points_max", 8)))
    data["hit_points_current"] = data["hit_points_max"]
    data["armor_class"] = max(1, int(data.get("armor_class", 10)))
    data["speed"] = max(0, int(data.get("speed", 30)))
    data.setdefault("equipment", [])
    data.setdefault("skill_proficiencies", [])
    data.setdefault("spells_known", {})
    data.setdefault("spell_slots", {})
    data.setdefault("relationships", {})
    data["mode"] = data.get("mode", "active")
    data["player_name"] = data.get("player_name") or "Randomised"

    # Phase 8: generate personality prompt + voice selection
    try:
        personality = await asyncio.get_event_loop().run_in_executor(
            None, lambda: generate_personality_data(data)
        )
        data.update(personality)
    except Exception as exc:
        log.warning("avatars.personality_gen_failed", error=str(exc))

    try:
        return AvatarCreate(**data)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Character validation failed: {exc}")


@router.post("/", response_model=AvatarResponse, status_code=status.HTTP_201_CREATED)
async def create_avatar(
    avatar_in: AvatarCreate,
    db: AsyncSession = Depends(get_db),
):
    data = avatar_in.model_dump()

    # Phase 8: generate personality + voice if either is missing
    if not data.get("personality_prompt") or not data.get("voice_id"):
        try:
            personality = await asyncio.get_event_loop().run_in_executor(
                None, lambda: generate_personality_data(data)
            )
            for key, val in personality.items():
                # Never overwrite a value the caller explicitly provided
                if val is not None and not data.get(key):
                    data[key] = val
        except Exception as exc:
            log.warning("avatars.create_personality_gen_failed", error=str(exc))

    avatar = Avatar(**data)
    avatar.hit_points_current = avatar.hit_points_max
    db.add(avatar)
    await db.commit()
    await db.refresh(avatar)
    return avatar


@router.get("/{avatar_id}", response_model=AvatarResponse)
async def get_avatar(avatar_id: int, db: AsyncSession = Depends(get_db)):
    avatar = await db.get(Avatar, avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    return avatar


@router.patch("/{avatar_id}", response_model=AvatarResponse)
async def update_avatar(
    avatar_id: int,
    avatar_in: AvatarUpdate,
    db: AsyncSession = Depends(get_db),
):
    avatar = await db.get(Avatar, avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    update_data = avatar_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(avatar, field, value)

    await db.commit()
    await db.refresh(avatar)
    return avatar


@router.get("/voices")
def list_voices():
    """Return the available Edge-TTS voice catalogue for avatar voice selection."""
    return {
        "voices": [
            {"voice_id": vid, **info}
            for vid, info in VOICE_CATALOGUE["en"].items()
        ],
        "note": "Voice IDs are Edge-TTS neural voices. Set tts_engine_preference='edge' to use them.",
    }


@router.post("/generate-personality", status_code=status.HTTP_200_OK)
async def generate_personality_backfill(
    avatar_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Backfill personality_prompt and voice_id for existing avatars.

    If avatar_id is provided, regenerates only that avatar.
    Otherwise regenerates all active avatars missing personality_prompt.

    Returns a summary of how many avatars were updated.
    """
    if avatar_id is not None:
        avatars = []
        av = await db.get(Avatar, avatar_id)
        if not av:
            raise HTTPException(status_code=404, detail="Avatar not found")
        avatars = [av]
    else:
        stmt = select(Avatar).where(
            Avatar.is_active == True,  # noqa: E712
            Avatar.personality_prompt == None,  # noqa: E711
        )
        result = await db.execute(stmt)
        avatars = list(result.scalars().all())

    updated = 0
    for av in avatars:
        avatar_data = {
            "name": av.name,
            "race": av.race,
            "char_class": av.char_class,
            "alignment": av.alignment or "",
            "personality_traits": av.personality_traits or "",
            "ideals": av.ideals or "",
            "bonds": av.bonds or "",
            "flaws": av.flaws or "",
            "backstory": av.backstory or "",
            "sentence_style": av.sentence_style or "",
            "verbal_tics": av.verbal_tics or "",
        }
        try:
            personality = await asyncio.get_event_loop().run_in_executor(
                None, lambda d=avatar_data: generate_personality_data(d)
            )
            av.personality_prompt = personality.get("personality_prompt")
            av.personality_archetype = personality.get("personality_archetype", "extrovert")
            av.verbosity = personality.get("verbosity", 0.5)
            av.interrupts_often = personality.get("interrupts_often", False)
            if not av.voice_id:
                av.voice_id = personality.get("voice_id")
            updated += 1
            log.info("avatars.backfill_done", avatar_id=av.id, name=av.name)
        except Exception as exc:
            log.error("avatars.backfill_failed", avatar_id=av.id, error=str(exc))

    await db.commit()
    return {"updated": updated, "total": len(avatars)}


@router.delete("/{avatar_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_avatar(avatar_id: int, db: AsyncSession = Depends(get_db)):
    avatar = await db.get(Avatar, avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    avatar.is_active = False
    await db.commit()


@router.post("/{avatar_id}/portrait", response_model=AvatarResponse)
async def upload_portrait(
    avatar_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    avatar = await db.get(Avatar, avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, or WebP images allowed")

    ext = file.filename.rsplit(".", 1)[-1].lower()
    dest = f"{UPLOAD_DIR}/portrait_{avatar_id}.{ext}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    avatar.portrait_path = dest
    await db.commit()
    await db.refresh(avatar)
    return avatar


@router.patch("/{avatar_id}/mode", response_model=AvatarResponse)
async def set_avatar_mode(
    avatar_id: int,
    mode: str,
    db: AsyncSession = Depends(get_db),
):
    if mode not in ("active", "passive", "absent"):
        raise HTTPException(status_code=400, detail="Mode must be active, passive, or absent")
    avatar = await db.get(Avatar, avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    avatar.mode = mode
    await db.commit()
    await db.refresh(avatar)
    return avatar


# ── Phase 5: Character sheet auto-update ──────────────────────────────────────

class SheetUpdateRequest(BaseModel):
    """
    Apply session-derived state changes to an avatar's character sheet.
    All fields are optional — only provided fields are updated.
    """
    hp_delta: int | None = None              # net HP change (positive = heal, negative = damage)
    hp_set: int | None = None               # set hp_current to an absolute value
    spell_slots_used: dict[str, int] | None = None   # {"1": 2, "3": 1} slots expended
    spell_slots_restore: bool | None = None  # if True, restore all spell slots
    items_gained: list[str] | None = None   # add to equipment list
    items_lost: list[str] | None = None     # remove from equipment list
    level_up: bool | None = None            # increment level by 1
    xp_gained: int | None = None            # stored in meta for future use
    relationship_updates: dict[str, str] | None = None   # {name: note}
    conditions_add: list[str] | None = None
    conditions_remove: list[str] | None = None


class SheetUpdateResponse(BaseModel):
    avatar_id: int
    changes: list[str]


@router.post("/{avatar_id}/sheet-update", response_model=SheetUpdateResponse)
async def sheet_update(
    avatar_id: int,
    body: SheetUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Apply mechanical state changes to an avatar from a session summary.
    Called after DM approves the session summary (Phase 5).
    """
    avatar = await db.get(Avatar, avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    changes: list[str] = []

    # HP
    if body.hp_set is not None:
        new_hp = max(0, min(body.hp_set, avatar.hit_points_max))
        if new_hp != avatar.hit_points_current:
            changes.append(f"HP set to {new_hp} (was {avatar.hit_points_current})")
            avatar.hit_points_current = new_hp
    elif body.hp_delta is not None and body.hp_delta != 0:
        new_hp = max(0, min(avatar.hit_points_current + body.hp_delta, avatar.hit_points_max))
        changes.append(f"HP {body.hp_delta:+d} → {new_hp}")
        avatar.hit_points_current = new_hp

    # Spell slots
    if body.spell_slots_restore:
        # Reset to max (stored in avatar.spell_slots as {"1": {"max": N, "used": N}})
        slots = dict(avatar.spell_slots or {})
        for lvl, data in slots.items():
            if isinstance(data, dict) and "used" in data:
                data["used"] = 0
        avatar.spell_slots = slots
        changes.append("Spell slots restored")

    elif body.spell_slots_used:
        slots = dict(avatar.spell_slots or {})
        for lvl_str, used_count in body.spell_slots_used.items():
            if lvl_str in slots and isinstance(slots[lvl_str], dict):
                slots[lvl_str]["used"] = slots[lvl_str].get("used", 0) + used_count
                changes.append(f"Level {lvl_str} spell slots: -{used_count} used")
        avatar.spell_slots = slots

    # Equipment
    equip = list(avatar.equipment or [])
    if body.items_gained:
        for item in body.items_gained:
            if item and item not in equip:
                equip.append(item)
                changes.append(f"Item gained: {item}")
    if body.items_lost:
        before = len(equip)
        equip = [e for e in equip if e not in body.items_lost]
        removed = before - len(equip)
        if removed:
            changes.append(f"Items removed: {', '.join(body.items_lost)}")
    avatar.equipment = equip

    # Level
    if body.level_up:
        avatar.level += 1
        changes.append(f"Level up → {avatar.level}")

    # Relationships
    if body.relationship_updates:
        rels = dict(avatar.relationships or {})
        for name, note in body.relationship_updates.items():
            rels[name] = note
            changes.append(f"Relationship updated: {name}")
        avatar.relationships = rels

    # Conditions stored in meta
    meta = dict(avatar.meta) if hasattr(avatar, "meta") and avatar.meta else {}
    conditions = list(meta.get("active_conditions", []))
    if body.conditions_add:
        for c in body.conditions_add:
            if c not in conditions:
                conditions.append(c)
                changes.append(f"Condition added: {c}")
    if body.conditions_remove:
        conditions = [c for c in conditions if c not in body.conditions_remove]
        changes.append(f"Conditions cleared: {', '.join(body.conditions_remove)}")
    meta["active_conditions"] = conditions

    if not changes:
        return SheetUpdateResponse(avatar_id=avatar_id, changes=["No changes applied"])

    await db.commit()
    return SheetUpdateResponse(avatar_id=avatar_id, changes=changes)
