import json
from datetime import timedelta

import psycopg2

from odoo import api, fields, models
from odoo.exceptions import ValidationError

MAX_SESSION_SECONDS = 28800  # 8h, defense-in-depth cap on session lifetime


class PickingAssistantSession(models.Model):
    _name = "picking.assistant.session"
    _description = "Picking Assistant Session"
    _order = "create_date desc"

    session_id = fields.Char(required=True, index=True, readonly=True)
    token_hash = fields.Char(required=True, index=True, readonly=True)
    csrf_hash = fields.Char(required=True, readonly=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    device_id = fields.Char(required=True, readonly=True)
    roles_json = fields.Text(required=True, readonly=True)
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    expires_at = fields.Datetime(required=True, index=True, readonly=True)
    revoked_at = fields.Datetime(index=True, readonly=True)
    last_seen_at = fields.Datetime(readonly=True)
    roles_checked_at = fields.Datetime(required=True, default=fields.Datetime.now)

    _session_id_unique = models.Constraint(
        "UNIQUE(session_id)", "Session ID must be unique."
    )
    _token_hash_unique = models.Constraint(
        "UNIQUE(token_hash)", "Session token hash must be unique."
    )

    def _api_payload(self):
        self.ensure_one()
        return {
            "session_id": self.session_id,
            "picker_user_id": self.user_id.id,
            "picker_name": self.user_id.name,
            "device_id": self.device_id,
            "roles": json.loads(self.roles_json),
            "expires_at": fields.Datetime.to_string(self.expires_at),
            "revoked_at": fields.Datetime.to_string(self.revoked_at)
            if self.revoked_at
            else False,
            "last_seen_at": fields.Datetime.to_string(self.last_seen_at)
            if self.last_seen_at
            else False,
            "roles_checked_at": fields.Datetime.to_string(self.roles_checked_at),
        }

    @api.model
    def api_create_session(
        self,
        session_id,
        token_hash,
        csrf_hash,
        user_id,
        device_id,
        roles,
        expires_at,
    ):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        created_at = fields.Datetime.now()
        expires_at_dt = fields.Datetime.to_datetime(expires_at)
        if (expires_at_dt - created_at) > timedelta(seconds=MAX_SESSION_SECONDS):
            raise ValidationError("Session lifetime may not exceed 8 hours.")
        session = self.sudo().create(
            {
                "session_id": session_id,
                "token_hash": token_hash,
                "csrf_hash": csrf_hash,
                "user_id": int(user_id),
                "device_id": device_id,
                "roles_json": json.dumps(sorted(set(roles))),
                "created_at": created_at,
                "expires_at": expires_at_dt,
            }
        )
        return session._api_payload()

    @api.model
    def api_get_session(self, token_hash, touch=False):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        session = self.sudo().search([("token_hash", "=", token_hash)], limit=1)
        now = fields.Datetime.now()
        if (
            not session
            or session.revoked_at
            or not session.expires_at
            or session.expires_at <= now
        ):
            return False
        if touch:
            session.last_seen_at = now
        return session._api_payload()

    @api.model
    def api_rotate_csrf(self, session_id, csrf_hash):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        session = self.sudo().search(
            [("session_id", "=", session_id), ("revoked_at", "=", False)],
            limit=1,
        )
        if not session or session.expires_at <= fields.Datetime.now():
            return False
        session.write({"csrf_hash": csrf_hash, "last_seen_at": fields.Datetime.now()})
        return True

    @api.model
    def api_mark_roles_checked(self, session_id, roles):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        sessions = self.sudo()
        session = sessions.search([("session_id", "=", session_id)], limit=1)
        if not session:
            return False
        # Minor M1: re-check revocation/expiry under a row lock. The old
        # code wrote the new roles and handed the session back
        # unconditionally, with no revocation or expiry check at all --
        # a session revoked (or already expired) between resolution and
        # this call still got new roles written and a live payload
        # returned. Same SELECT ... FOR UPDATE + savepoint pattern as every
        # other lock site in this addon (outbox.py, receipts.py,
        # integration_job.py): under REPEATABLE READ, losing this lock to a
        # concurrent transaction that has ALREADY committed does not
        # block-then-return-the-new-tuple, it raises SerializationFailure
        # (SQLSTATE 40001) right at this statement. The savepoint contains
        # that failure to this one statement so it cannot swallow an
        # unrelated 40001 later in the transaction.
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "SELECT id FROM picking_assistant_session WHERE id = %s "
                    "FOR UPDATE",
                    (session.id,),
                )
                # Fetched INSIDE the savepoint: `RELEASE SAVEPOINT` on
                # `with`-exit would otherwise clobber this pending result.
                found = self.env.cr.fetchone()
        except psycopg2.errors.SerializationFailure as exc:
            raise ValidationError(
                "Session changed during role marking."
            ) from exc
        if not found:
            return False
        session.invalidate_recordset()
        now = fields.Datetime.now()
        if session.revoked_at or not session.expires_at or session.expires_at <= now:
            return False
        session.write(
            {
                "roles_json": json.dumps(sorted(set(roles))),
                "roles_checked_at": now,
            }
        )
        return session._api_payload()

    @api.model
    def api_validate_csrf(self, session_id, candidate_hash):
        import secrets

        self.env["picking.assistant.api.mixin"]._require_api_service()
        session = self.sudo().search(
            [("session_id", "=", session_id), ("revoked_at", "=", False)],
            limit=1,
        )
        return bool(
            session
            and session.expires_at > fields.Datetime.now()
            and secrets.compare_digest(session.csrf_hash, candidate_hash)
        )

    @api.model
    def api_revoke_session(self, session_id):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        sessions = self.sudo().search(
            [("session_id", "=", session_id), ("revoked_at", "=", False)]
        )
        sessions.write({"revoked_at": fields.Datetime.now()})
        return bool(sessions)

    @api.model
    def api_revoke_user_sessions(self, user_id):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        sessions = self.sudo().search(
            [("user_id", "=", int(user_id)), ("revoked_at", "=", False)]
        )
        sessions.write({"revoked_at": fields.Datetime.now()})
        return len(sessions)

    @api.model
    def _gc_expired_sessions(self, batch_size=500):
        cutoff = fields.Datetime.now() - timedelta(days=7)
        domain = [
            "|",
            "&",
            ("revoked_at", "!=", False),
            ("revoked_at", "<=", cutoff),
            "&",
            ("revoked_at", "=", False),
            ("expires_at", "<=", cutoff),
        ]
        stale = self.sudo().search(domain, limit=batch_size)
        remaining = self.sudo().search_count(domain) - len(stale)
        if stale:
            stale.unlink()
        # Durch den Guard, nicht daran vorbei (I2) -- siehe die identische
        # Begruendung in `auth_throttle._gc_expired_throttle`.
        # `ir.cron._commit_progress` committet den Cursor auch ausserhalb eines
        # Cron-Laufs; `_report_cron_progress` meldet nur im echten Cron.
        self.env["picking.assistant.integration.job"]._report_cron_progress(
            len(stale), remaining=max(remaining, 0)
        )
