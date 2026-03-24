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


class RouteStopResponse(BaseModel):
    sequence: int
    move_line_id: int
    product_name: str
    location_src: str
    estimated_steps_from_previous: int


class RoutePlanResponse(BaseModel):
    strategy: str
    total_stops: int
    completed_stops: int
    remaining_stops: int
    estimated_travel_steps: int
    next_move_line_id: Optional[int] = None
    next_location_src: Optional[str] = None
    next_product_name: Optional[str] = None
    zone_sequence: list[str] = []
    stops: list[RouteStopResponse] = []


class PickingResponse(BaseModel):
    id: int
    name: str
    state: str
    scheduled_date: Optional[str] = None
    move_lines: list[MoveLineResponse] = []
    route_plan: Optional[RoutePlanResponse] = None


class ConfirmLineRequest(BaseModel):
    move_line_id: int
    scanned_barcode: str
    quantity: float = 0


class ConfirmLineResponse(BaseModel):
    success: bool
    message: str
    picking_complete: bool = False
