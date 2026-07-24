from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import api, fields, models

FAILURE_WINDOW = timedelta(minutes=15)
FAILURE_THRESHOLD = 5
ROW_TTL = timedelta(hours=24)


class PickingAssistantAuthThrottle(models.Model):
    _name = "picking.assistant.auth.throttle"
    _description = "Picking Assistant Login Throttle"

    login_key = fields.Char(required=True, index=True, readonly=True)
    source_ip_hmac = fields.Char(required=True, index=True, readonly=True)
    failure_count = fields.Integer(required=True, default=0)
    window_started_at = fields.Datetime()
    locked_until = fields.Datetime(index=True)
    last_attempt_at = fields.Datetime()
    expires_at = fields.Datetime(required=True, index=True)

    _login_key_source_ip_hmac_unique = models.Constraint(
        "UNIQUE(login_key, source_ip_hmac)",
        "Only one throttle row per login key and source IP hash.",
    )

    def _lock_or_create(self, login_key, source_ip_hmac, now):
        self.env.cr.execute(
            "SELECT id FROM picking_assistant_auth_throttle "
            "WHERE login_key = %s AND source_ip_hmac = %s FOR UPDATE",
            (login_key, source_ip_hmac),
        )
        row = self.env.cr.fetchone()
        if row:
            return self.browse(row[0])
        try:
            with self.env.cr.savepoint():
                record = self.create(
                    {
                        "login_key": login_key,
                        "source_ip_hmac": source_ip_hmac,
                        "failure_count": 0,
                        "expires_at": now + ROW_TTL,
                    }
                )
            return record
        except IntegrityError:
            self.env.cr.execute(
                "SELECT id FROM picking_assistant_auth_throttle "
                "WHERE login_key = %s AND source_ip_hmac = %s FOR UPDATE",
                (login_key, source_ip_hmac),
            )
            row = self.env.cr.fetchone()
            return self.browse(row[0])

    def _state_payload(self, record, now):
        locked_until = record.locked_until if record.locked_until and record.locked_until > now else False
        return {
            "allowed": not locked_until,
            "failure_count": record.failure_count,
            "locked_until": fields.Datetime.to_string(locked_until) if locked_until else False,
        }

    @api.model
    def api_check_login(self, login_key, source_ip_hmac):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        now = fields.Datetime.now()
        record = self.sudo().search(
            [
                ("login_key", "=", login_key),
                ("source_ip_hmac", "=", source_ip_hmac),
            ],
            limit=1,
        )
        if not record:
            return {"allowed": True, "failure_count": 0, "locked_until": False}
        return self._state_payload(record, now)

    @api.model
    def api_record_login_result(self, login_key, source_ip_hmac, succeeded):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        now = fields.Datetime.now()
        record = self.sudo()._lock_or_create(login_key, source_ip_hmac, now)
        if succeeded:
            record.write(
                {
                    "failure_count": 0,
                    "window_started_at": False,
                    "locked_until": False,
                    "last_attempt_at": now,
                    "expires_at": now + ROW_TTL,
                }
            )
        else:
            window_started_at = record.window_started_at
            if not window_started_at or (now - window_started_at) > FAILURE_WINDOW:
                window_started_at = now
                failure_count = 1
            else:
                failure_count = record.failure_count + 1
            locked_until = False
            if failure_count >= FAILURE_THRESHOLD:
                locked_until = window_started_at + FAILURE_WINDOW
            record.write(
                {
                    "failure_count": failure_count,
                    "window_started_at": window_started_at,
                    "locked_until": locked_until,
                    "last_attempt_at": now,
                    "expires_at": now + ROW_TTL,
                }
            )
        return self._state_payload(record, now)

    @api.model
    def _gc_expired_throttle(self, batch_size=500):
        now = fields.Datetime.now()
        domain = [("expires_at", "<=", now)]
        stale = self.sudo().search(domain, limit=batch_size)
        remaining = self.sudo().search_count(domain) - len(stale)
        if stale:
            stale.unlink()
        self.env["ir.cron"]._commit_progress(len(stale), remaining=max(remaining, 0))
