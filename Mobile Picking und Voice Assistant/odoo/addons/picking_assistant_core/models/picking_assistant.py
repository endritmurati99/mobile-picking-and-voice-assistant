import json
from datetime import timedelta

from odoo import api, fields, models
from psycopg2 import IntegrityError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    mobile_claim_user_id = fields.Many2one(
        "res.users",
        string="Mobile Claim User",
        ondelete="set null",
        copy=False,
    )
    mobile_claim_device_id = fields.Char(string="Mobile Claim Device", copy=False)
    mobile_claimed_at = fields.Datetime(string="Mobile Claimed At", copy=False)
    mobile_claim_expires_at = fields.Datetime(string="Mobile Claim Expires At", copy=False)

    def _claim_payload(self, success=True, status="claimed"):
        self.ensure_one()
        return {
            "success": success,
            "status": status,
            "picking_id": self.id,
            "claimed_by_user_id": self.mobile_claim_user_id.id or False,
            "claimed_by_name": self.mobile_claim_user_id.name or "",
            "device_id": self.mobile_claim_device_id or "",
            "claimed_at": fields.Datetime.to_string(self.mobile_claimed_at) if self.mobile_claimed_at else False,
            "claim_expires_at": fields.Datetime.to_string(self.mobile_claim_expires_at) if self.mobile_claim_expires_at else False,
        }

    def _clear_mobile_claim(self):
        self.ensure_one()
        self.write(
            {
                "mobile_claim_user_id": False,
                "mobile_claim_device_id": False,
                "mobile_claimed_at": False,
                "mobile_claim_expires_at": False,
            }
        )

    def _upsert_mobile_claim(self, picker_user_id, device_id, ttl_seconds):
        self.ensure_one()
        now = fields.Datetime.now()
        expires_at = now + timedelta(seconds=int(ttl_seconds or 120))
        self.write(
            {
                "mobile_claim_user_id": picker_user_id,
                "mobile_claim_device_id": device_id,
                "mobile_claimed_at": now,
                "mobile_claim_expires_at": expires_at,
            }
        )
        return self._claim_payload(success=True, status="claimed")

    def _active_claim_conflict(self, picker_user_id, device_id):
        self.ensure_one()
        now = fields.Datetime.now()
        expires_at = self.mobile_claim_expires_at
        has_active_claim = bool(expires_at and expires_at > now and self.mobile_claim_user_id)
        is_same_owner = (
            self.mobile_claim_user_id.id == picker_user_id
            and (self.mobile_claim_device_id or "") == (device_id or "")
        )
        if has_active_claim and not is_same_owner:
            payload = self._claim_payload(success=False, status="conflict")
            payload["conflict"] = True
            return payload
        return None

    def _find_internal_replenishment_type(self):
        self.ensure_one()
        picking_type_model = self.env["stock.picking.type"].sudo()
        warehouse = self.picking_type_id.warehouse_id
        company = self.company_id

        candidates = []
        if warehouse:
            candidates.append([("code", "=", "internal"), ("warehouse_id", "=", warehouse.id)])
        if company:
            candidates.append([("code", "=", "internal"), ("company_id", "=", company.id)])
        candidates.append([("code", "=", "internal")])

        for domain in candidates:
            picking_type = picking_type_model.search(domain, limit=1)
            if picking_type:
                return picking_type
        return False

    @api.model
    def api_claim_mobile(self, picking_id, picker_user_id, device_id, ttl_seconds=120):
        picking = self.sudo().browse(int(picking_id)).exists()
        if not picking:
            return {"success": False, "status": "missing", "message": "Picking nicht gefunden"}

        conflict = picking._active_claim_conflict(int(picker_user_id), device_id)
        if conflict:
            return conflict

        return picking._upsert_mobile_claim(int(picker_user_id), device_id, ttl_seconds)

    @api.model
    def api_heartbeat_mobile(self, picking_id, picker_user_id, device_id, ttl_seconds=120):
        picking = self.sudo().browse(int(picking_id)).exists()
        if not picking:
            return {"success": False, "status": "missing", "message": "Picking nicht gefunden"}

        conflict = picking._active_claim_conflict(int(picker_user_id), device_id)
        if conflict:
            return conflict

        return picking._upsert_mobile_claim(int(picker_user_id), device_id, ttl_seconds)

    @api.model
    def api_release_mobile(self, picking_id, picker_user_id, device_id):
        picking = self.sudo().browse(int(picking_id)).exists()
        if not picking:
            return {"success": True, "status": "released"}

        now = fields.Datetime.now()
        expires_at = picking.mobile_claim_expires_at
        is_expired = bool(expires_at and expires_at <= now)
        is_same_owner = (
            picking.mobile_claim_user_id.id == int(picker_user_id)
            and (picking.mobile_claim_device_id or "") == (device_id or "")
        )

        if not picking.mobile_claim_user_id or is_expired or is_same_owner:
            picking._clear_mobile_claim()
            return {"success": True, "status": "released", "picking_id": picking.id}

        payload = picking._claim_payload(success=False, status="conflict")
        payload["conflict"] = True
        return payload

    @api.model
    def api_create_replenishment_transfer(
        self,
        picking_id,
        product_id,
        source_location_id,
        destination_location_id,
        quantity=1.0,
        reason=False,
        correlation_id=False,
        requested_by_user_id=False,
        requested_by_name=False,
    ):
        picking = self.sudo().browse(int(picking_id)).exists()
        if not picking:
            return {"success": False, "message": "Picking nicht gefunden."}

        if not product_id or not source_location_id or not destination_location_id:
            return {"success": False, "message": "Produkt, Quellort und Zielort sind erforderlich."}

        source_location_id = int(source_location_id)
        destination_location_id = int(destination_location_id)
        if source_location_id == destination_location_id:
            return {"success": False, "message": "Quellort und Zielort muessen unterschiedlich sein."}

        product = self.env["product.product"].sudo().browse(int(product_id)).exists()
        source_location = self.env["stock.location"].sudo().browse(source_location_id).exists()
        destination_location = self.env["stock.location"].sudo().browse(destination_location_id).exists()
        if not product or not source_location or not destination_location:
            return {"success": False, "message": "Produkt oder Lagerorte konnten nicht aufgeloest werden."}

        picking_type = picking._find_internal_replenishment_type()
        if not picking_type:
            return {"success": False, "message": "Kein interner Picking-Typ fuer Nachschub gefunden."}

        move_qty = float(quantity or 1.0)
        if move_qty <= 0:
            move_qty = 1.0

        origin = "AI Replenishment fuer %s" % (picking.name or picking.origin or "Picking")
        if correlation_id:
            origin = "%s [%s]" % (origin, correlation_id)

        transfer_values = {
            "picking_type_id": picking_type.id,
            "location_id": source_location.id,
            "location_dest_id": destination_location.id,
            "origin": origin,
            "note": reason or False,
            "company_id": picking.company_id.id if picking.company_id else False,
        }
        transfer = self.sudo().create(transfer_values)

        self.env["stock.move"].sudo().create(
            {
                "name": "AI Replenishment %s" % (product.display_name or product.name),
                "product_id": product.id,
                "product_uom_qty": move_qty,
                "product_uom": product.uom_id.id,
                "picking_id": transfer.id,
                "location_id": source_location.id,
                "location_dest_id": destination_location.id,
                "company_id": transfer.company_id.id if transfer.company_id else False,
            }
        )

        transfer.action_confirm()
        transfer.action_assign()

        requested_by = ""
        if requested_by_user_id:
            user = self.env["res.users"].sudo().browse(int(requested_by_user_id)).exists()
            requested_by = user.name or requested_by_name or ""
        elif requested_by_name:
            requested_by = requested_by_name

        audit_parts = [
            "AI-Nachschub angelegt: %s" % transfer.name,
            "Produkt: %s" % (product.display_name or product.name),
            "Von: %s" % source_location.display_name,
            "Nach: %s" % destination_location.display_name,
            "Menge: %s" % move_qty,
        ]
        if requested_by:
            audit_parts.append("Ausgeloest fuer: %s" % requested_by)
        if reason:
            audit_parts.append("Grund: %s" % reason)
        audit_message = "<br/>".join(audit_parts)

        transfer.message_post(
            body=audit_message,
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )
        picking.message_post(
            body=audit_message,
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )

        return {
            "success": True,
            "replenishment_picking_id": transfer.id,
            "replenishment_name": transfer.name,
            "state": transfer.state,
            "source_location_id": source_location.id,
            "source_location_name": source_location.display_name,
            "destination_location_id": destination_location.id,
            "destination_location_name": destination_location.display_name,
            "quantity": move_qty,
        }


class PickingAssistantIdempotency(models.Model):
    _name = "picking.assistant.idempotency"
    _description = "Picking Assistant Idempotency Entry"
    _order = "create_date desc"

    endpoint = fields.Char(required=True, index=True)
    key = fields.Char(required=True, index=True)
    request_fingerprint = fields.Char(required=True)
    response_payload = fields.Text()
    status_code = fields.Integer(default=200)
    state = fields.Selection(
        [("pending", "Pending"), ("completed", "Completed")],
        default="pending",
        required=True,
        index=True,
    )
    picker_user_id = fields.Many2one("res.users", string="Picker", ondelete="set null")
    device_id = fields.Char()
    picking_id = fields.Many2one("stock.picking", ondelete="set null")
    expires_at = fields.Datetime(required=True, index=True)
    processed_at = fields.Datetime()

    _sql_constraints = [
        (
            "picking_assistant_idempotency_key_unique",
            "unique(endpoint, key)",
            "The idempotency key must be unique per endpoint.",
        ),
    ]

    @api.model
    def _build_reservation_payload(self, entry):
        payload = {
            "status": entry.state,
            "entry_id": entry.id,
            "status_code": entry.status_code or 200,
        }
        if entry.response_payload:
            payload["response_payload"] = json.loads(entry.response_payload)
        return payload

    @api.model
    def api_reserve_request(
        self,
        endpoint,
        key,
        request_fingerprint,
        picking_id=False,
        picker_user_id=False,
        device_id=False,
        ttl_seconds=86400,
    ):
        now = fields.Datetime.now()
        existing = self.sudo().search([("endpoint", "=", endpoint), ("key", "=", key)], limit=1)
        if existing and existing.expires_at and existing.expires_at <= now:
            existing.unlink()
            existing = False

        if existing:
            if existing.request_fingerprint != request_fingerprint:
                return {
                    "status": "conflict",
                    "entry_id": existing.id,
                    "status_code": 409,
                    "response_payload": {"detail": "Idempotency-Key wird bereits fuer einen anderen Request verwendet."},
                }
            if existing.state == "completed" and existing.response_payload:
                replay = self._build_reservation_payload(existing)
                replay["status"] = "replay"
                return replay
            return {
                "status": "pending",
                "entry_id": existing.id,
                "status_code": 409,
                "response_payload": {"detail": "Request mit gleichem Idempotency-Key wird bereits verarbeitet."},
            }

        values = {
            "endpoint": endpoint,
            "key": key,
            "request_fingerprint": request_fingerprint,
            "picking_id": int(picking_id) if picking_id else False,
            "picker_user_id": int(picker_user_id) if picker_user_id else False,
            "device_id": device_id or False,
            "expires_at": now + timedelta(seconds=int(ttl_seconds or 86400)),
        }

        try:
            entry = self.sudo().create(values)
        except IntegrityError:
            self.env.cr.rollback()
            return self.api_reserve_request(
                endpoint,
                key,
                request_fingerprint,
                picking_id=picking_id,
                picker_user_id=picker_user_id,
                device_id=device_id,
                ttl_seconds=ttl_seconds,
            )

        return {"status": "reserved", "entry_id": entry.id, "status_code": 200}

    @api.model
    def api_finalize_request(self, entry_id, response_payload, status_code=200):
        entry = self.sudo().browse(int(entry_id)).exists()
        if not entry:
            return False
        entry.write(
            {
                "response_payload": json.dumps(response_payload, ensure_ascii=False, sort_keys=True),
                "status_code": int(status_code or 200),
                "state": "completed",
                "processed_at": fields.Datetime.now(),
            }
        )
        return True

    @api.model
    def api_abort_request(self, entry_id):
        entry = self.sudo().browse(int(entry_id)).exists()
        if not entry:
            return False
        entry.unlink()
        return True
