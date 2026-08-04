"""Bau des v2-Ereignisses fuer einen Qualitaetsmangel.

Der Fingerprint ist die empfindlichste Stelle der ganzen Kette:
`picking.assistant.event.receipt.api_accept_event` vergleicht ihn BITGENAU mit
dem Wert, den n8n aus dem SHA-256 des empfangenen Rumpfes meldet. Der
Dispatcher uebertraegt `envelope_text` unveraendert als UTF-8, also muss der
Fingerprint ueber genau diese Bytes gebildet werden -- nicht ueber das
`payload`-Teilobjekt und nicht ueber ein zweites `json.dumps` mit anderen
Trennzeichen.
"""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from odoo import api, models

EVENT_NAME = "quality.assessment.requested.v1"
# Generationen steigen nur, wenn der Watchdog eine abgelaufene Lease
# einsammelt. Fuenf davon sind ein Betriebsfall, kein Zustellproblem; der
# Workflow scheitert danach bewusst geschlossen, statt still falsch zu
# schreiben. n8n kann in Set-Ausdruecken keine UUID erzeugen und Code-Knoten
# sind nach der Annahme verboten -- deshalb liefert die erzeugende Seite die
# Callback-IDs mit.
CALLBACK_ID_GENERATIONS = 5


class QualityAlertEventBuilder(models.AbstractModel):
    _name = "quality.alert.event.builder"
    _description = "Builder fuer quality.assessment.requested.v1"

    @api.model
    def _canonical(self, envelope):
        return json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    @api.model
    def build(self, alert):
        instance = self.env["picking.assistant.api.mixin"]._instance_name()
        event_id = str(uuid4())
        job_id = str(uuid4())
        correlation_id = str(uuid4())
        photo_count = self.env["ir.attachment"].sudo().search_count(
            [("res_model", "=", alert._name), ("res_id", "=", alert.id)]
        )
        envelope = {
            "schema_version": "v2",
            "event_name": EVENT_NAME,
            "event_id": event_id,
            "correlation_id": correlation_id,
            "causation_id": None,
            "occurred_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "source": {
                "service": "picking-assistant-api",
                "odoo_instance": instance,
            },
            "actor": {
                "type": "picker",
                "user_id": alert.user_id.id or None,
                "name": alert.user_id.name or None,
                "device_id": None,
            },
            "aggregate": {
                "model": alert._name,
                "id": alert.id,
                "revision": alert.integration_revision,
            },
            "payload": {
                "alert_id": alert.id,
                "name": alert.name or "",
                "description": alert.description or "",
                "priority": alert.priority or "0",
                "photo_count": photo_count,
                "product_id": alert.product_id.id or None,
                "location_id": alert.location_id.id or None,
                "picking_id": alert.picking_id.id or None,
                "job_id": job_id,
                "callback_ids_by_generation": {
                    str(generation): {"terminal": str(uuid4())}
                    for generation in range(1, CALLBACK_ID_GENERATIONS + 1)
                },
            },
        }
        envelope_text = self._canonical(envelope)
        return {
            "event_id": event_id,
            "job_id": job_id,
            "correlation_id": correlation_id,
            "envelope_text": envelope_text,
            "payload_fingerprint": hashlib.sha256(
                envelope_text.encode("utf-8")
            ).hexdigest(),
        }
