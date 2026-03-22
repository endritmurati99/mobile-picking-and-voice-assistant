"""
Picking-Endpoints.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.dependencies import get_picking_service

router = APIRouter()


class ConfirmLineRequest(BaseModel):
    move_line_id: int
    scanned_barcode: str = ""
    quantity: float = 0


@router.get("/pickings")
async def list_pickings(service=Depends(get_picking_service)):
    """Offene Pickings mit Move-Lines abrufen."""
    return await service.get_open_pickings()


@router.get("/pickings/{picking_id}")
async def get_picking(picking_id: int, service=Depends(get_picking_service)):
    """Einzelnes Picking mit Details."""
    return await service.get_picking_detail(picking_id)


@router.post("/pickings/{picking_id}/confirm-line")
async def confirm_line(
    picking_id: int,
    body: ConfirmLineRequest,
    service=Depends(get_picking_service),
):
    """Pick-Zeile per Scan bestätigen."""
    return await service.confirm_pick_line(
        picking_id, body.move_line_id, body.scanned_barcode, body.quantity
    )
