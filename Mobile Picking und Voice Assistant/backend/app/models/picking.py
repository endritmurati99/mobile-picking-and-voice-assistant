"""Pydantic Models für Picking-Daten."""
from pydantic import BaseModel
from typing import Optional


class MoveLineResponse(BaseModel):
    id: int
    product_id: int
    product_name: str
    product_barcode: Optional[str] = None
    quantity_demand: float
    quantity_done: float
    location_src: str
    location_dest: str


class PickingResponse(BaseModel):
    id: int
    name: str
    state: str
    scheduled_date: Optional[str] = None
    move_lines: list[MoveLineResponse] = []


class ConfirmLineRequest(BaseModel):
    move_line_id: int
    scanned_barcode: str
    quantity: float = 0


class ConfirmLineResponse(BaseModel):
    success: bool
    message: str
    picking_complete: bool = False
