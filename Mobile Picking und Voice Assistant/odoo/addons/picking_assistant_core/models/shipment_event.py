"""Bau des v2-Ereignisses fuer einen fertig kommissionierten Lieferschein.

Fingerprint-Regel identisch zu quality.alert.event.builder: SHA-256 ueber
genau die Bytes von `envelope_text`. Der Dispatcher uebertraegt den Text
unveraendert, n8n meldet den SHA-256 des empfangenen Rumpfes zurueck.
"""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from odoo import api, models

EVENT_NAME = "shipment.parcel.ready.v1"
CALLBACK_ID_GENERATIONS = 5


class ShipmentEventBuilder(models.AbstractModel):
    _name = "shipment.event.builder"
    _description = "Builder fuer shipment.parcel.ready.v1"

    @api.model
    def _canonical(self, envelope):
        return json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    @api.model
    def _recipient(self, partner):
        if not partner:
            return {"name": "", "street": "", "street2": "", "zip": "", "city": "",
                    "country_code": ""}
        return {
            "name": partner.name or "",
            "street": partner.street or "",
            "street2": partner.street2 or "",
            "zip": partner.zip or "",
            "city": partner.city or "",
            "country_code": partner.country_id.code or "",
        }

    @api.model
    def _items(self, picking):
        items = []
        for move in picking.move_ids:
            qty = move.quantity or move.product_uom_qty
            weight = move.product_id.weight or 0.0
            items.append(
                {
                    "product_id": move.product_id.id,
                    "default_code": move.product_id.default_code or "",
                    "name": move.product_id.name or "",
                    "qty": float(qty),
                    "weight_kg": float(weight),
                }
            )
        return items

    @api.model
    def build(self, picking):
        picking.ensure_one()
        instance = self.env["picking.assistant.api.mixin"]._instance_name()
        event_id = str(uuid4())
        job_id = str(uuid4())
        correlation_id = str(uuid4())
        items = self._items(picking)
        total_weight = round(sum(i["qty"] * i["weight_kg"] for i in items), 6)
        user = self.env.user
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
                "type": "system",
                "user_id": user.id or None,
                "name": user.name or None,
                "device_id": None,
            },
            "aggregate": {
                "model": picking._name,
                "id": picking.id,
                "revision": picking.integration_revision,
            },
            "payload": {
                "picking_id": picking.id,
                "picking_name": picking.name or "",
                "origin": picking.origin or "",
                "warehouse": picking.picking_type_id.warehouse_id.name or "",
                "recipient": self._recipient(picking.partner_id),
                "items": items,
                "total_weight_kg": total_weight,
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
