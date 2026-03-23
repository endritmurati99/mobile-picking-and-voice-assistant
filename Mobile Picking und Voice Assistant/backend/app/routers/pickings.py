"""
Picking-Endpoints.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.dependencies import get_picking_service, get_odoo_client
from app.services.odoo_client import OdooClient

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


@router.get("/pickings/{picking_id}/route-plan")
async def get_route_plan(picking_id: int, service=Depends(get_picking_service)):
    """Optimierte Reihenfolge fuer verbleibende Picking-Positionen."""
    return await service.get_picking_route_plan(picking_id)


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


@router.get("/pickings/{picking_id}/stock")
async def get_stock_for_line(
    picking_id: int,  # noqa: ARG001 — kept for URL consistency
    product_id: int,
    location_id: int,
    odoo: OdooClient = Depends(get_odoo_client),
):
    """
    Gibt den aktuellen Lagerbestand für ein Produkt an einem Standort zurück.
    Wird von der PWA aufgerufen wenn der Picker fragt 'Wie viele noch da?'
    """
    domain = [("product_id", "=", product_id)]
    if location_id > 0:
        domain.append(("location_id", "=", location_id))
    quants = await odoo.search_read(
        "stock.quant",
        domain,
        ["quantity", "reserved_quantity"],
    )
    available = sum(q.get("quantity", 0) - q.get("reserved_quantity", 0) for q in quants)
    total = sum(q.get("quantity", 0) for q in quants)
    return {
        "product_id": product_id,
        "location_id": location_id,
        "quantity_available": round(available, 2),
        "quantity_total": round(total, 2),
    }
