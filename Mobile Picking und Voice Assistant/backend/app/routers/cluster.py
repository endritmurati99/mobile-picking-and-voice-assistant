"""Cluster-/Batch-Picking-Endpoints (/api/cluster/*)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import (
    get_cluster_service,
    get_mobile_workflow_service,
    get_required_picker_identity,
    get_write_request_context,
)
from app.routers.pickings import (
    _finalize_error,
    _require_resolved_identity,
    _return_or_raise_replay,
)
from app.services.mobile_workflow import PickerIdentity, WriteRequestContext

router = APIRouter()


class CreateBatchRequest(BaseModel):
    picking_ids: list[int]


class ClusterConfirmRequest(BaseModel):
    picking_id: int
    move_line_id: int
    scanned_barcode: str = ""
    quantity: float = Field(default=0, ge=0, allow_inf_nan=False)
    serial_number: str = ""
    scanned_package: str = ""


@router.get("/cluster/suggestions")
async def cluster_suggestions(
    _identity: PickerIdentity = Depends(get_required_picker_identity),
    service=Depends(get_cluster_service),
):
    """Auto-Vorschlaege fuer Batches (offene Pickings nach Zone gruppiert)."""
    return await service.suggest_batches(picker_identity=_identity)


@router.post("/cluster/batches")
async def create_cluster_batch(
    body: CreateBatchRequest,
    service=Depends(get_cluster_service),
    workflow=Depends(get_mobile_workflow_service),
    context: WriteRequestContext = Depends(get_write_request_context),
):
    """Batch aus picking_ids anlegen (echter stock.picking.batch)."""
    if not body.picking_ids:
        raise HTTPException(status_code=400, detail="picking_ids darf nicht leer sein.")
    identity = await _require_resolved_identity(workflow, context)
    fingerprint = workflow.build_request_fingerprint({
        "action": "cluster-create",
        "picking_ids": sorted(set(body.picking_ids)),
        "picker_user_id": identity.user_id,
        "device_id": identity.device_id,
    })
    reservation = await workflow.begin_idempotent_request(
        "cluster.batches.create", context, fingerprint
    )
    replay = _return_or_raise_replay(reservation)
    if replay is not None:
        return replay
    try:
        result = await service.create_batch(body.picking_ids, picker_identity=identity)
    except Exception:
        await workflow.abort_idempotent_request(reservation)
        raise
    if result.get("forbidden"):
        await _finalize_error(workflow, reservation, 403, result.get("message") or result.get("error"))
        raise HTTPException(status_code=403, detail=result.get("message") or result.get("error"))
    if result.get("code") == "cluster_capacity":
        await _finalize_error(workflow, reservation, 422, result.get("message") or result.get("error"))
        raise HTTPException(status_code=422, detail=result.get("message") or result.get("error"))
    if result.get("code") == "stock_picking_batch_unavailable" or result.get("unavailable"):
        await _finalize_error(workflow, reservation, 503, result.get("message") or result.get("error"))
        raise HTTPException(status_code=503, detail=result.get("message") or result.get("error"))
    if result.get("error"):
        await _finalize_error(workflow, reservation, 409, result["error"])
        raise HTTPException(status_code=409, detail=result["error"])
    await workflow.finalize_idempotent_request(reservation, result, 200)
    return result


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
    service=Depends(get_cluster_service),
    workflow=Depends(get_mobile_workflow_service),
    context: WriteRequestContext = Depends(get_write_request_context),
):
    """Position bestaetigen (Menge/Serial), ohne Picking-Validierung."""
    identity = await _require_resolved_identity(workflow, context)
    fingerprint = workflow.build_request_fingerprint({
        "action": "cluster-confirm-line", "batch_id": batch_id,
        **body.model_dump(), "picker_user_id": identity.user_id, "device_id": identity.device_id,
    })
    reservation = await workflow.begin_idempotent_request(
        "cluster.batches.confirm-line", context, fingerprint
    )
    replay = _return_or_raise_replay(reservation)
    if replay is not None:
        return replay
    try:
        result = await service.confirm_cluster_line(
            batch_id, body.picking_id, body.move_line_id,
            scanned_barcode=body.scanned_barcode, quantity=body.quantity,
            serial_number=body.serial_number, scanned_package=body.scanned_package,
            picker_identity=identity,
        )
    except Exception:
        await workflow.abort_idempotent_request(reservation)
        raise
    if result.get("forbidden"):
        await _finalize_error(workflow, reservation, 403, result["message"])
        raise HTTPException(status_code=403, detail=result["message"])
    await workflow.finalize_idempotent_request(reservation, result, 200)
    return result


@router.post("/cluster/batches/{batch_id}/validate")
async def validate_cluster_batch(
    batch_id: int,
    service=Depends(get_cluster_service),
    workflow=Depends(get_mobile_workflow_service),
    context: WriteRequestContext = Depends(get_write_request_context),
):
    """Ganzen Batch gesammelt abschliessen (action_done + n8n)."""
    identity = await _require_resolved_identity(workflow, context)
    fingerprint = workflow.build_request_fingerprint({
        "action": "cluster-validate", "batch_id": batch_id,
        "picker_user_id": identity.user_id, "device_id": identity.device_id,
    })
    reservation = await workflow.begin_idempotent_request(
        "cluster.batches.validate", context, fingerprint
    )
    replay = _return_or_raise_replay(reservation)
    if replay is not None:
        return replay
    try:
        result = await service.validate_batch(batch_id, picker_identity=identity)
    except Exception:
        await workflow.abort_idempotent_request(reservation)
        raise
    if result.get("forbidden"):
        await _finalize_error(workflow, reservation, 403, result["message"])
        raise HTTPException(status_code=403, detail=result["message"])
    await workflow.finalize_idempotent_request(reservation, result, 200)
    return result
