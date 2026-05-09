from pydantic import BaseModel
from typing import Optional


class InventoryBase(BaseModel):
    category: str
    item_name: str
    spec: str = ""
    current_qty: int
    safe_qty: int
    unit: str = "개"


class InventoryCreate(InventoryBase):
    pass


class InventoryUpdate(BaseModel):
    category: Optional[str] = None
    item_name: Optional[str] = None
    spec: Optional[str] = None
    current_qty: Optional[int] = None
    safe_qty: Optional[int] = None
    unit: Optional[str] = None


class Inventory(InventoryBase):
    inventory_id: str
    updated_at: str

    @property
    def is_low_stock(self) -> bool:
        return self.current_qty <= self.safe_qty
