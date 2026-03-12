from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel
from app.db.database import get_db
from app.models.avatar import Avatar
from app.schemas.avatar import AvatarCreate, AvatarUpdate, AvatarResponse
import shutil
import os

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


@router.post("/", response_model=AvatarResponse, status_code=status.HTTP_201_CREATED)
async def create_avatar(
    avatar_in: AvatarCreate,
    db: AsyncSession = Depends(get_db),
):
    avatar = Avatar(**avatar_in.model_dump())
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
