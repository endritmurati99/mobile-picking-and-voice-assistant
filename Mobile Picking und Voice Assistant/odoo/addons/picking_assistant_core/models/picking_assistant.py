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
