"""Demo-only operational toggles."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import get_instance_registry, settings
from app.dependencies import get_demo_odoo_client, get_required_picker_identity, resolve_instance
from app.services.mobile_workflow import PickerIdentity
from app.services.demo_traceability import DEMO_MODES, DemoTraceabilityService
from app.services.odoo_client import OdooAPIError, OdooClient

router = APIRouter(prefix="/demo", tags=["demo"])


class TraceabilityModeRequest(BaseModel):
    mode: str


def _allowed_dbs() -> set[str]:
    return {
        value.strip()
        for value in (settings.demo_traceability_allowed_dbs or "").split(",")
        if value.strip()
    }


def _demo_guard(instance: str) -> tuple[bool, str]:
    if not settings.demo_traceability_enabled:
        return False, "Demo-Traceability ist deaktiviert."
    profile = get_instance_registry()[instance]
    allowed = _allowed_dbs()
    if not allowed:
        return False, "Demo-Traceability ist deaktiviert: keine Demo-DB erlaubt."
    if profile.db not in allowed:
        return False, f"Demo-Traceability ist fuer DB {profile.db} nicht erlaubt."
    return True, ""


@router.get("/traceability")
async def get_traceability_demo(
    instance: str = Depends(resolve_instance),
    odoo: OdooClient = Depends(get_demo_odoo_client),
):
    allowed, reason = _demo_guard(instance)
    if not allowed:
        return {
            "enabled": False,
            "reason": reason,
            "mode": "disabled",
            "modes": [{"name": name, **meta} for name, meta in DEMO_MODES.items()],
        }
    try:
        return await DemoTraceabilityService(odoo).get_status()
    except OdooAPIError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from exc


@router.post("/traceability")
async def set_traceability_demo(
    body: TraceabilityModeRequest,
    instance: str = Depends(resolve_instance),
    odoo: OdooClient = Depends(get_demo_odoo_client),
    _identity: PickerIdentity = Depends(get_required_picker_identity),
):
    allowed, reason = _demo_guard(instance)
    if not allowed:
        raise HTTPException(status_code=403, detail=reason)
    try:
        return await DemoTraceabilityService(odoo).apply_mode(body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OdooAPIError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from exc
