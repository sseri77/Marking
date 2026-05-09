from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ClubBase(BaseModel):
    club_name: str
    status: str = "활성"


class ClubCreate(ClubBase):
    pass


class ClubUpdate(BaseModel):
    club_name: Optional[str] = None
    status: Optional[str] = None


class Club(ClubBase):
    club_id: str
    created_at: str
    updated_at: str
