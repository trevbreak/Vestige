"""
Character Traits and Relationship States API.

GET  /api/avatars/{id}/traits               — list active traits
PATCH /api/avatars/{id}/traits/{trait_id}   — DM edit (strength, resolved, description)
DELETE /api/avatars/{id}/traits/{trait_id}  — DM dismiss

GET  /api/avatars/{id}/relationships               — list relationship states
PATCH /api/avatars/{id}/relationships/{rel_id}     — DM edit axes
"""

from __future__ import annotations

from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.character_trait import CharacterTrait
from app.models.relationship_state import RelationshipState

router = APIRouter(tags=["traits"])


# ── Schemas ────────────────────────────────────────────────────────────────

class TraitResponse(BaseModel):
    id: int
    avatar_id: int
    trait_name: str
    description: Optional[str]
    current_strength: float
    manifestation_probability: float
    trigger_keywords: Optional[str]
    emotional_signature: Optional[str]
    onset_session_id: Optional[int]
    is_resolved: bool
    is_positive: bool

    model_config = {"from_attributes": True}


class TraitUpdate(BaseModel):
    current_strength: Optional[float] = None
    description: Optional[str] = None
    manifestation_probability: Optional[float] = None
    is_resolved: Optional[bool] = None
    trigger_keywords: Optional[str] = None
    emotional_signature: Optional[str] = None


class RelationshipResponse(BaseModel):
    id: int
    avatar_a_id: int
    avatar_b_id: Optional[int]
    target_name: Optional[str]
    trust: float
    affection: float
    respect: float
    key_moments: Optional[str]
    last_updated_session_id: Optional[int]

    model_config = {"from_attributes": True}


class RelationshipUpdate(BaseModel):
    trust: Optional[float] = None
    affection: Optional[float] = None
    respect: Optional[float] = None
    key_moments: Optional[str] = None


# ── Trait endpoints ────────────────────────────────────────────────────────

@router.get("/avatars/{avatar_id}/traits", response_model=list[TraitResponse])
async def list_traits(avatar_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CharacterTrait)
        .where(CharacterTrait.avatar_id == avatar_id)
        .order_by(CharacterTrait.current_strength.desc())
    )
    return result.scalars().all()


@router.patch("/avatars/{avatar_id}/traits/{trait_id}", response_model=TraitResponse)
async def update_trait(
    avatar_id: int,
    trait_id: int,
    body: TraitUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CharacterTrait).where(
            CharacterTrait.id == trait_id,
            CharacterTrait.avatar_id == avatar_id,
        )
    )
    trait = result.scalar_one_or_none()
    if trait is None:
        raise HTTPException(status_code=404, detail="Trait not found")

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(trait, field, val)

    await db.commit()
    await db.refresh(trait)
    return trait


@router.delete("/avatars/{avatar_id}/traits/{trait_id}", status_code=204)
async def delete_trait(
    avatar_id: int,
    trait_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CharacterTrait).where(
            CharacterTrait.id == trait_id,
            CharacterTrait.avatar_id == avatar_id,
        )
    )
    trait = result.scalar_one_or_none()
    if trait is None:
        raise HTTPException(status_code=404, detail="Trait not found")
    await db.delete(trait)
    await db.commit()


# ── Relationship endpoints ─────────────────────────────────────────────────

@router.get("/avatars/{avatar_id}/relationships", response_model=list[RelationshipResponse])
async def list_relationships(avatar_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RelationshipState).where(RelationshipState.avatar_a_id == avatar_id)
    )
    return result.scalars().all()


@router.patch("/avatars/{avatar_id}/relationships/{rel_id}", response_model=RelationshipResponse)
async def update_relationship(
    avatar_id: int,
    rel_id: int,
    body: RelationshipUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RelationshipState).where(
            RelationshipState.id == rel_id,
            RelationshipState.avatar_a_id == avatar_id,
        )
    )
    rel = result.scalar_one_or_none()
    if rel is None:
        raise HTTPException(status_code=404, detail="Relationship not found")

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(rel, field, val)

    await db.commit()
    await db.refresh(rel)
    return rel
