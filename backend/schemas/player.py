from pydantic import BaseModel
from typing import Optional


class PlayerBase(BaseModel):
    club_name: str
    collab_name: str
    player_name: str
    player_number: str
    status: str = "활성"


class PlayerCreate(PlayerBase):
    pass


class PlayerUpdate(BaseModel):
    club_name: Optional[str] = None
    collab_name: Optional[str] = None
    player_name: Optional[str] = None
    player_number: Optional[str] = None
    status: Optional[str] = None


class Player(PlayerBase):
    player_id: str
    created_at: str
    updated_at: str
