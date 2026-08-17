"""Idempotency reservations, scoped to the authenticated principal.

An Idempotency-Key belongs to a PRINCIPAL, not to an endpoint. Before Task 12
the unique key was `(endpoint, key)`, so two different authenticated users
sending the same key to the same endpoint collided and the second one was
answered with the first one's reservation. The scope is supplied by the server
from the session and is never read from a request body or header.
"""

import json
from datetime import timedelta

import psycopg2
from psycopg2 import errorcodes

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# The default the pre-migration back-fills onto rows written before the scope
# existed. It is deliberately not a usable scope: a caller that supplies it is
# refused, so a legacy row can never be mistaken for a scoped reservation.
LEGACY_SCOPE = "legacy"


class PickingAssistantIdempotency(models.Model):
    _name = "picking.assistant.idempotency"
    _description = "Picking Assistant Idempotency Entry"
    _order = "create_date desc"

    endpoint = fields.Char(required=True, index=True)
    principal_scope = fields.Char(required=True, index=True, default=LEGACY_SCOPE)
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

    _endpoint_scope_key_unique = models.Constraint(
        "UNIQUE(endpoint, principal_scope, key)",
        "The idempotency key must be unique per operation and principal.",
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_api(self):
        self.env["picking.assistant.api.mixin"]._require_api_service()

    def _payload(self):
        self.ensure_one()
        payload = {
            "status": self.state,
            "entry_id": self.id,
            "status_code": self.status_code or 200,
        }
        if self.response_payload:
            payload["response_payload"] = json.loads(self.response_payload)
        return payload

    @api.model
    def _pending_answer(self, entry_id=None):
        """The honest answer when someone else holds this key right now."""
        answer = {
            "status": "pending",
            "status_code": 409,
            "response_payload": {"detail": "Request is already processing."},
        }
        if entry_id is not None:
            answer["entry_id"] = entry_id
        return answer

    @api.model
    def _scoped_entry(self, entry_id, principal_scope):
        entry = self.sudo().browse(int(entry_id)).exists()
        if not entry or entry.principal_scope != principal_scope:
            raise ValidationError("Idempotency reservation scope mismatch.")
        return entry

    # ------------------------------------------------------------------
    # Public API (API-service group only)
    # ------------------------------------------------------------------

    @api.model
    def api_reserve_request(
        self,
        endpoint,
        key,
        request_fingerprint,
        principal_scope,
        picking_id=False,
        picker_user_id=False,
        device_id=False,
        ttl_seconds=86400,
    ):
        self._require_api()
        if not principal_scope or principal_scope == LEGACY_SCOPE:
            raise ValidationError("A non-legacy principal scope is required.")

        now = fields.Datetime.now()
        # 40001-Wahl: TRANSPARENTER RETRY. Ein verlorener Lock hier ist noch
        # keine Entscheidung -- der Gewinner kann reservieren, abbrechen oder
        # finalisieren, und erst danach steht fest, was dieser Aufrufer zu
        # hoeren bekommt. Odoos `retrying()` faehrt die RPC mit frischem
        # Snapshot neu und liefert dann eine benannte Antwort; eine
        # Klassifizierung hier wuerde raten muessen.
        self.env.cr.execute(
            """
            SELECT id
              FROM picking_assistant_idempotency
             WHERE endpoint = %s
               AND principal_scope = %s
               AND key = %s
             FOR UPDATE
            """,
            (endpoint, principal_scope, key),
        )
        row = self.env.cr.fetchone()
        existing = self.sudo().browse(row[0]) if row else self.sudo().browse()

        # picking_id ist reine Metadaten (ondelete="set null"). Ein Reserve fuer
        # eine nicht (mehr) existente Kommissionierung -- getippte/veraltete ID --
        # schrieb bisher eine baumelnde FK und liess PostgreSQL den INSERT mit
        # einer Fremdschluesselverletzung abbrechen; die Odoo-Meldung ("Another
        # model is using the record you are trying to delete") kam als roher 500
        # beim Aufrufer an (2026-08-17 live belegt: claim auf pick 99999). Die
        # Existenz einmal pruefen und sonst False speichern: die Reservierung
        # gelingt, und der nachgelagerte claim/heartbeat meldet sauber "missing".
        picking_ref = int(picking_id) if picking_id else False
        if picking_ref and not self.env["stock.picking"].sudo().browse(picking_ref).exists():
            picking_ref = False

        values = {
            "endpoint": endpoint,
            "principal_scope": principal_scope,
            "key": key,
            "request_fingerprint": request_fingerprint,
            "picking_id": picking_ref,
            "picker_user_id": int(picker_user_id) if picker_user_id else False,
            "device_id": device_id or False,
            "expires_at": now + timedelta(seconds=int(ttl_seconds or 86400)),
            "state": "pending",
            "response_payload": False,
            "status_code": 200,
            "processed_at": False,
        }

        if existing:
            if existing.expires_at and existing.expires_at <= now:
                # Reuse the row rather than delete-then-insert: the row is
                # already locked, so the reuse cannot race, and every field of
                # the previous reservation -- including its recorded response
                # -- is overwritten, never inherited.
                existing.write(values)
                return {
                    "status": "reserved",
                    "entry_id": existing.id,
                    "status_code": 200,
                }
            if existing.request_fingerprint != request_fingerprint:
                return {
                    "status": "conflict",
                    "entry_id": existing.id,
                    "status_code": 409,
                    "response_payload": {
                        "detail": "Idempotency-Key conflicts with another request."
                    },
                }
            if existing.state == "completed":
                replay = existing._payload()
                replay["status"] = "replay"
                return replay
            return self._pending_answer(existing.id)

        try:
            with self.env.cr.savepoint():
                created = self.sudo().create(values)
                created.flush_recordset()
        except psycopg2.IntegrityError as exc:
            # A concurrent transaction committed this exact reservation after
            # our snapshot was taken. DO NOT re-SELECT and DO NOT recurse:
            # Odoo runs REPEATABLE READ, so that row is invisible to this
            # transaction and the retry would insert again, collide again, and
            # recurse forever. The pre-Task-12 code escaped that only by
            # calling `cr.rollback()` -- which silently discarded every
            # unrelated write the caller had already made.
            #
            # Classified on the SQLSTATE plus the table rather than on a
            # constraint name, because this model carries exactly one unique
            # constraint and Odoo generates its name; "a unique violation on
            # this table" is therefore unambiguous and cannot drift when the
            # generator changes. Any other integrity error still flies.
            if (
                exc.pgcode == errorcodes.UNIQUE_VIOLATION
                and getattr(exc.diag, "table_name", None)
                == "picking_assistant_idempotency"
            ):
                return self._pending_answer()
            raise

        return {"status": "reserved", "entry_id": created.id, "status_code": 200}

    @api.model
    def api_finalize_request(
        self, entry_id, principal_scope, response_payload, status_code=200
    ):
        self._require_api()
        entry = self._scoped_entry(entry_id, principal_scope)
        entry.write(
            {
                "response_payload": json.dumps(
                    response_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "status_code": int(status_code or 200),
                "state": "completed",
                "processed_at": fields.Datetime.now(),
            }
        )
        return True

    @api.model
    def api_abort_request(self, entry_id, principal_scope):
        self._require_api()
        self._scoped_entry(entry_id, principal_scope).unlink()
        return True

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    @api.model
    def _cron_cleanup_expired(self, limit=1000):
        """Delete expired reservations and REPORT WHAT WAS LEFT BEHIND.

        A GC that truncates at its limit and reports only what it deleted
        reads as "nothing left to do". The remainder is what makes a backlog
        alertable.
        """
        now = fields.Datetime.now()
        records = self.sudo().search([("expires_at", "<=", now)], limit=int(limit))
        processed = len(records)
        records.unlink()
        remaining = self.sudo().search_count([("expires_at", "<=", now)])
        # Never `ir.cron._commit_progress` directly: it commits the cursor even
        # when called outside a cron run, which is forbidden on a test cursor.
        self.env["picking.assistant.integration.job"]._report_cron_progress(
            processed, remaining=remaining
        )
        return processed
