"""Pydantic Models für Quality Alerts."""
from pydantic import BaseModel
from typing import Optional


class CreateAlertRequest(BaseModel):
    description: str
    picking_id: Optional[int] = None
    product_id: Optional[int] = None
    location_id: Optional[int] = None
    priority: str = "0"


class AlertResponse(BaseModel):
    alert_id: int
    name: str
    message: str = "Quality Alert erstellt"
