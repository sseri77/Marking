from pydantic import BaseModel
from typing import Optional


ROLE_CHOICES = [
    ("SUPER_ADMIN", "최고관리자"),
    ("ADMIN", "관리자"),
    ("MANAGER", "매니저"),
    ("STAFF", "직원"),
    ("VIEWER", "조회자"),
]

STATUS_CHOICES = ["활성", "비활성"]


class UserBase(BaseModel):
    username: str
    full_name: str = ""
    role: str = "STAFF"
    status: str = "활성"
    memo: str = ""


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    memo: Optional[str] = None
    password: Optional[str] = None


class User(UserBase):
    user_id: str
    permissions: str = ""
    last_login_at: str = ""
    created_at: str
    updated_at: str
