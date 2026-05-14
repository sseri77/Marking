from pydantic import BaseModel
from typing import Optional


class NoticeBase(BaseModel):
    title: str
    content: str = ""
    is_pinned: str = "N"


class NoticeCreate(NoticeBase):
    pass


class NoticeUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    is_pinned: Optional[str] = None


class Notice(NoticeBase):
    notice_id: str
    author: str
    created_at: str
    updated_at: str
