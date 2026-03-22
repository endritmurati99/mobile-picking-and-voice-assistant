"""
Quality-Alert-Endpoints.
Erstellt quality.alert.custom Records in Odoo 18 mit optionalem Foto-Attachment.
Löst anschließend n8n-Workflow (fire-and-forget) aus.
"""
import base64
import logging
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from typing import Optional

from app.dependencies import get_odoo_client, get_n8n_client
from app.services.odoo_client import OdooClient, OdooAPIError
from app.services.n8n_webhook import N8NWebhookClient

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/quality-alerts")
async def create_quality_alert(
    description: str = Form(...),
    picking_id: Optional[int] = Form(None),
    product_id: Optional[int] = Form(None),
    location_id: Optional[int] = Form(None),
    priority: str = Form("0"),
    photo: Optional[UploadFile] = File(None),
    odoo: OdooClient = Depends(get_odoo_client),
    n8n: N8NWebhookClient = Depends(get_n8n_client),
):
    """
    Quality Alert mit optionalem Foto erstellen.

    Ruft quality.alert.custom.api_create_alert() auf — eine atomare Methode
    im Custom-Odoo-Modul, die Alert + Foto-Attachment in einer Transaktion erstellt.

    ir.attachment.datas erwartet Base64-String (nicht Bytes).
    """
    # Foto lesen und in Base64 konvertieren
    photo_b64: str | None = None
    photo_filename: str | None = None
    if photo and photo.filename:
        photo_bytes = await photo.read()
        if photo_bytes:
            photo_b64 = base64.b64encode(photo_bytes).decode("utf-8")
            photo_filename = photo.filename

    # Payload für Odoo
    vals: dict = {"description": description, "priority": priority}
    if picking_id:
        vals["picking_id"] = picking_id
    if product_id:
        vals["product_id"] = product_id
    if location_id:
        vals["location_id"] = location_id
    if photo_b64 and photo_filename:
        vals["photo_base64"] = photo_b64
        vals["photo_filename"] = photo_filename

    try:
        result = await odoo.call_method(
            "quality.alert.custom",
            "api_create_alert",
            [],          # keine record-IDs — @api.model Methode
            args=[vals],
        )
    except OdooAPIError as e:
        logger.error(f"Odoo Quality Alert Fehler: {e.message}")
        raise HTTPException(status_code=502, detail=f"Odoo-Fehler: {e.message}")

    alert_id = result.get("alert_id") if isinstance(result, dict) else None
    name = result.get("name", "") if isinstance(result, dict) else ""

    # n8n fire-and-forget (Fehler werden nur geloggt)
    await n8n.fire("quality-alert-created", {
        "alert_id": alert_id,
        "name": name,
        "picking_id": picking_id,
        "priority": priority,
    })

    return {"alert_id": alert_id, "name": name}
