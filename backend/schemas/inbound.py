from pydantic import BaseModel
from typing import Optional


class InboundBase(BaseModel):
    date: str
    vendor: str
    material_name: str
    spec: str = ""
    lot_no: str
    qty: int
    unit: str = "m"
    manager: str
    memo: str = ""


class InboundCreate(InboundBase):
    pass


class InboundUpdate(BaseModel):
    date: Optional[str] = None
    vendor: Optional[str] = None
    material_name: Optional[str] = None
    spec: Optional[str] = None
    lot_no: Optional[str] = None
    qty: Optional[int] = None
    unit: Optional[str] = None
    manager: Optional[str] = None
    memo: Optional[str] = None


class Inbound(InboundBase):
    inbound_id: str
    created_at: str
