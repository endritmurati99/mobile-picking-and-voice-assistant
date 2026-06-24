"""Cluster-/Batch-Picking-Endpoints (/api/cluster/*).

PoC-Hinweis: bewusst ohne den Idempotenz-Reservierungs-Flow der pickings-Routes.
Doppel-Submits entschaerft das Frontend per Button-Disable. Der Batch ist der
Owner (batch.user_id), ein Claim/Heartbeat pro Picking entfaellt im Cluster.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import get_cluster_service, get_required_picker_identity
from app.services.mobile_workflow import PickerIdentity

router = APIRouter()


class CreateBatchRequest(BaseModel):
    picking_ids: list[int]


class ClusterConfirmRequest(BaseModel):
    picking_id: int
    move_line_id: int
    scanned_barcode: str = ""
    quantity: float = 0
    serial_number: str = ""


@router.get("/cluster/suggestions")
async def cluster_suggestions(
    _identity: PickerIdentity = Depends(get_required_picker_identity),
    service=Depends(get_cluster_service),
):
    """Auto-Vorschlaege fuer Batches (offene Pickings nach Zone gruppiert)."""
    return await service.suggest_batches()


@router.post("/cluster/batches")
async def create_cluster_batch(
    body: CreateBatchRequest,
    identity: PickerIdentity = Depends(get_required_picker_identity),
    service=Depends(get_cluster_service),
):
    """Batch aus picking_ids anlegen (echter stock.picking.batch)."""
    if not body.picking_ids:
        raise HTTPException(status_code=400, detail="picking_ids darf nicht leer sein.")
    return await service.create_batch(body.picking_ids, picker_identity=identity)


@router.get("/cluster/batches/{batch_id}")
async def get_cluster_batch(
    batch_id: int,
    identity: PickerIdentity = Depends(get_required_picker_identity),
    service=Depends(get_cluster_service),
):
    """Sammelliste + Fortschritt eines Batches."""
    result = await service.get_batch(batch_id, picker_identity=identity)
    if result.get("forbidden"):
        raise HTTPException(status_code=403, detail=result["error"])
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/cluster/batches/{batch_id}/confirm-line")
async def confirm_cluster_line(
    batch_id: int,
    body: ClusterConfirmRequest,
    identity: PickerIdentity = Depends(get_required_picker_identity),
    service=Depends(get_cluster_service),
):
    """Position bestaetigen (Menge/Serial), ohne Picking-Validierung."""
    result = await service.confirm_cluster_line(
        batch_id, body.picking_id, body.move_line_id,
        scanned_barcode=body.scanned_barcode, quantity=body.quantity,
        serial_number=body.serial_number, picker_identity=identity,
    )
    if result.get("forbidden"):
        raise HTTPException(status_code=403, detail=result["message"])
    return result


@router.post("/cluster/batches/{batch_id}/validate")
async def validate_cluster_batch(
    batch_id: int,
    identity: PickerIdentity = Depends(get_required_picker_identity),
    service=Depends(get_cluster_service),
):
    """Ganzen Batch gesammelt abschliessen (action_done + n8n)."""
    result = await service.validate_batch(batch_id, picker_identity=identity)
    if result.get("forbidden"):
        raise HTTPException(status_code=403, detail=result["message"])
    return result
