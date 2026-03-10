from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
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
