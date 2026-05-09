from pydantic import BaseModel, field_validator
from typing import Optional


class CuttingBase(BaseModel):
    work_order_no: str
    club_name: str
    collab_name: str
    player_name: str
    player_number: str
    input_qty: int
    success_qty: int
    defect_qty: int = 0
    loss_qty: int = 0
    status: str = "진행중"
    worker: str
    memo: str = ""

    @field_validator("success_qty")
    @classmethod
    def success_must_not_exceed_input(cls, v, info):
        data = info.data
        if "input_qty" in data and v > data["input_qty"]:
            raise ValueError("성공수량은 투입수량을 초과할 수 없습니다.")
        return v


class CuttingCreate(CuttingBase):
    pass


class CuttingUpdate(BaseModel):
    work_order_no: Optional[str] = None
    club_name: Optional[str] = None
    collab_name: Optional[str] = None
    player_name: Optional[str] = None
    player_number: Optional[str] = None
    input_qty: Optional[int] = None
    success_qty: Optional[int] = None
    defect_qty: Optional[int] = None
    loss_qty: Optional[int] = None
    status: Optional[str] = None
    worker: Optional[str] = None
    memo: Optional[str] = None


class Cutting(CuttingBase):
    process_id: str
    created_at: str
