from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SessionCreate(BaseModel):
    name: str = Field("Unnamed Session", min_length=1, max_length=200)
    campaign_name: Optional[str] = None
    avatar_ids: list[int] = []
    avatar_modes: dict[str, str] = {}


class SessionUpdate(BaseModel):
    name: Optional[str] = None
    campaign_name: Optional[str] = None
    avatar_ids: Optional[list[int]] = None
    avatar_modes: Optional[dict[str, str]] = None
    summary: Optional[str] = None
    summary_approved: Optional[bool] = None
    is_active: Optional[bool] = None


class SessionResponse(BaseModel):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    name: str
    campaign_name: Optional[str] = None
    avatar_ids: list[int]
    avatar_modes: dict[str, str]
    summary: Optional[str] = None
    summary_approved: bool
    is_active: bool

    model_config = {"from_attributes": True}
