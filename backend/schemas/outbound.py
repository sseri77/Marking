from pydantic import BaseModel, field_validator
from typing import Optional


class OutboundBase(BaseModel):
    store_name: str
    club_name: str
    collab_name: str
    player_name: str
    player_number: str
    qty: int
    invoice_no: str
    shipping_date: str
    manager: str
    memo: str = ""

    @field_validator("qty")
    @classmethod
    def qty_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("출고 수량은 0보다 커야 합니다.")
        return v


class OutboundCreate(OutboundBase):
    pass


class OutboundUpdate(BaseModel):
    store_name: Optional[str] = None
    club_name: Optional[str] = None
    collab_name: Optional[str] = None
    player_name: Optional[str] = None
    player_number: Optional[str] = None
    qty: Optional[int] = None
    invoice_no: Optional[str] = None
    shipping_date: Optional[str] = None
    manager: Optional[str] = None
    memo: Optional[str] = None


class Outbound(OutboundBase):
    outbound_id: str
    created_at: str
