from pydantic import BaseModel
from typing import Optional


class PrinterBase(BaseModel):
    printer_name: str
    contact: str = ""
    phone: str = ""
    memo: str = ""
    status: str = "활성"


class PrinterCreate(PrinterBase):
    pass


class PrinterUpdate(BaseModel):
    printer_name: Optional[str] = None
    contact: Optional[str] = None
    phone: Optional[str] = None
    memo: Optional[str] = None
    status: Optional[str] = None


class Printer(PrinterBase):
    printer_id: str
    created_at: str
    updated_at: str
