from pydantic import BaseModel
from typing import Optional


class StoreBase(BaseModel):
    store_name: str
    contact: str = ""
    phone: str = ""
    address: str = ""
    memo: str = ""
    status: str = "활성"


class StoreCreate(StoreBase):
    pass


class StoreUpdate(BaseModel):
    store_name: Optional[str] = None
    contact: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    memo: Optional[str] = None
    status: Optional[str] = None


class Store(StoreBase):
    store_id: str
    created_at: str
    updated_at: str
