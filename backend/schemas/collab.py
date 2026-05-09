from pydantic import BaseModel
from typing import Optional


class CollabBase(BaseModel):
    club_id: str
    collab_name: str
    status: str = "활성"


class CollabCreate(CollabBase):
    pass


class CollabUpdate(BaseModel):
    club_id: Optional[str] = None
    collab_name: Optional[str] = None
    status: Optional[str] = None


class Collab(CollabBase):
    collab_id: str
    created_at: str
    updated_at: str
