import json
from datetime import timedelta

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
        session = self.sudo().search([("session_id", "=", session_id)], limit=1)
        if not session:
            return False
        session.write(
            {
                "roles_json": json.dumps(sorted(set(roles))),
                "roles_checked_at": fields.Datetime.now(),
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
        self.env["ir.cron"]._commit_progress(len(stale), remaining=max(remaining, 0))
