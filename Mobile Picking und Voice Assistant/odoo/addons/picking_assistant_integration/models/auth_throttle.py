import secrets
from datetime import timedelta

from odoo import api, fields, models

FAILURE_WINDOW = timedelta(minutes=15)
FAILURE_THRESHOLD = 5
ROW_TTL = timedelta(hours=24)

# In-flight-Reservierungen (siehe `api_begin_login_attempt`) zaehlen gegen
# dasselbe Limit wie gebuchte Fehlschlaege. Eine Reservierung, deren Backend
# nie zu `api_finish_login_attempt` zurueckkehrt (Absturz, Netzwerkfehler),
# muss verfallen -- sonst wuerde ein abgestuerztes Backend einen Account
# dauerhaft aussperren.
IN_FLIGHT_TTL = timedelta(seconds=30)


class PickingAssistantAuthThrottle(models.Model):
    _name = "picking.assistant.auth.throttle"
    _description = "Picking Assistant Login Throttle"

    login_key = fields.Char(required=True, index=True, readonly=True)
    source_ip_hmac = fields.Char(required=True, index=True, readonly=True)
    failure_count = fields.Integer(required=True, default=0)
    in_flight_count = fields.Integer(required=True, default=0)
    window_started_at = fields.Datetime()
    locked_until = fields.Datetime(index=True)
    last_attempt_at = fields.Datetime()
    expires_at = fields.Datetime(required=True, index=True)

    _login_key_source_ip_hmac_unique = models.Constraint(
        "UNIQUE(login_key, source_ip_hmac)",
        "Only one throttle row per login key and source IP hash.",
    )

    def _lock_or_create(self, login_key, source_ip_hmac, now):
        """Get-or-create under real concurrency (mandatory addition,
        escalated from Task 3's re-review of this method).

        The row-creation half used to be `create()` wrapped in
        `except IntegrityError`, and on a losing INSERT it re-SELECTed
        `FOR UPDATE` to hand back the winner's row. That re-SELECT is
        unheilbar falsch under Odoo's REPEATABLE READ, not just
        unreliable: this transaction's snapshot was taken BEFORE the
        winning transaction's commit, so the re-SELECT finds nothing on
        every attempt, and `browse(row[0])` on `row = None` raised a raw
        `TypeError: 'NoneType' object is not subscriptable` right on the
        login path.

        A first fix attempt replaced that with a Python-constructed
        `psycopg2.errors.SerializationFailure`, reasoning that it was "the
        class Odoo's `retrying()` wrapper retries". That reasoning was
        wrong: `retrying()` does not dispatch on exception CLASS, it reads
        `exc.pgcode`, and a Python-instantiated psycopg2 exception has
        `pgcode = None` (psycopg2's C layer only populates it from a real
        libpq result). `None` is never in the retried set, so the
        synthetic exception was re-raised on the first pass -- same two
        consequences as the original bug (a 500 where a 401 belongs, the
        losing attempt's failure not counted), just a different traceback.

        The actual fix asks Postgres to raise the real thing instead of
        synthesising it: `INSERT ... ON CONFLICT (login_key,
        source_ip_hmac) DO UPDATE ... RETURNING id`. Per the Postgres
        manual (`INSERT ... ON CONFLICT DO UPDATE`), the DO UPDATE clause
        forces an EvalPlanQual recheck against the most recently committed
        row; under REPEATABLE READ or SERIALIZABLE that recheck cannot
        silently use a newer row than the transaction's snapshot allows,
        so Postgres itself raises `SerializationFailure` with SQLSTATE
        `40001` -- a driver-populated `pgcode`, which `retrying()` DOES
        retry. The retry runs in a fresh transaction with a fresh
        snapshot and lands on the ordinary `if row:` branch above. No
        exception is synthesised anywhere in this method any more.
        """
        self.env.cr.execute(
            "SELECT id FROM picking_assistant_auth_throttle "
            "WHERE login_key = %s AND source_ip_hmac = %s FOR UPDATE",
            (login_key, source_ip_hmac),
        )
        row = self.env.cr.fetchone()
        if row:
            record = self.browse(row[0])
            record.invalidate_recordset()
            return record
        # No savepoint/except here on purpose, unlike the sibling lock
        # sites in `outbox.py:241-249` and `receipts.py:381-399`: those
        # wrap-and-classify a losing `FOR UPDATE` into a domain
        # `ValidationError` because the correct business response to
        # THEIR conflict is a clean rejection. Here the correct response
        # to a losing INSERT is a transparent retry with fresh state, and
        # that is exactly what letting the native `SerializationFailure`
        # propagate to Odoo's `retrying()` RPC wrapper gives us -- wrapping
        # it into a `ValidationError` would take that retry away.
        self.env.cr.execute(
            "INSERT INTO picking_assistant_auth_throttle "
            "(login_key, source_ip_hmac, failure_count, in_flight_count, "
            "expires_at, create_uid, write_uid, create_date, write_date) "
            "VALUES (%s, %s, 0, 0, %s, %s, %s, %s, %s) "
            "ON CONFLICT (login_key, source_ip_hmac) "
            "DO UPDATE SET login_key = EXCLUDED.login_key "
            "RETURNING id",
            (
                login_key,
                source_ip_hmac,
                now + ROW_TTL,
                self.env.uid,
                self.env.uid,
                now,
                now,
            ),
        )
        new_id = self.env.cr.fetchone()[0]
        record = self.browse(new_id)
        record.invalidate_recordset()
        return record

    def _expire_stale_in_flight(self, record, now):
        """Zero a reservation nobody finished within IN_FLIGHT_TTL.

        A crashed or hung backend leaks the reservation `api_begin_login_
        attempt` took, because `api_finish_login_attempt` then never runs.
        Without this the leaked reservation would count against the limit
        forever and lock the account out permanently.
        """
        if (
            record.in_flight_count
            and record.last_attempt_at
            and (now - record.last_attempt_at) > IN_FLIGHT_TTL
        ):
            record.write({"in_flight_count": 0})

    def _failure_values(self, record, now):
        """Failure bookkeeping shared by `api_record_login_result` (kept for
        backwards compatibility) and `api_finish_login_attempt`."""
        window_started_at = record.window_started_at
        if not window_started_at or (now - window_started_at) > FAILURE_WINDOW:
            window_started_at = now
            failure_count = 1
        else:
            failure_count = record.failure_count + 1
        locked_until = False
        if failure_count >= FAILURE_THRESHOLD:
            locked_until = window_started_at + FAILURE_WINDOW
        return {
            "failure_count": failure_count,
            "window_started_at": window_started_at,
            "locked_until": locked_until,
            "last_attempt_at": now,
            "expires_at": now + ROW_TTL,
        }

    def _state_payload(self, record, now):
        locked_until = record.locked_until if record.locked_until and record.locked_until > now else False
        return {
            "allowed": not locked_until,
            "failure_count": record.failure_count,
            "locked_until": fields.Datetime.to_string(locked_until) if locked_until else False,
        }

    @api.model
    def api_check_login(self, login_key, source_ip_hmac):
        """Kept for backwards compatibility. No longer called by the
        backend -- see `api_begin_login_attempt` (finding #10)."""
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
        """Kept for backwards compatibility. No longer called by the
        backend -- see `api_finish_login_attempt` (finding #10)."""
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
            record.write(self._failure_values(record, now))
        return self._state_payload(record, now)

    @api.model
    def api_begin_login_attempt(self, login_key, source_ip_hmac):
        """Reserviert einen Login-Versuch, BEVOR das teure Authentifizieren laeuft.

        Frueher pruefte der Backend-Login erst das Limit, authentifizierte dann
        und verbuchte den Fehlschlag zuletzt -- drei getrennte Transaktionen.
        Beliebig viele parallele Requests kamen deshalb alle durch, bevor der
        erste Fehlschlag ueberhaupt gebucht war: das Limit begrenzte Runden,
        nicht Versuche.

        In-flight-Reservierungen zaehlen gegen dasselbe Limit wie gebuchte
        Fehlschlaege. Eine Reservierung, die laenger als IN_FLIGHT_TTL keine
        Antwort bekommen hat, verfaellt -- sonst wuerde ein abgestuerztes
        Backend einen Account dauerhaft aussperren.
        """
        self.env["picking.assistant.api.mixin"]._require_api_service()
        now = fields.Datetime.now()
        record = self.sudo()._lock_or_create(login_key, source_ip_hmac, now)
        self._expire_stale_in_flight(record, now)
        if record.failure_count + record.in_flight_count >= FAILURE_THRESHOLD:
            return {"allowed": False, "attempt_token": ""}
        if record.locked_until and record.locked_until > now:
            return {"allowed": False, "attempt_token": ""}
        token = secrets.token_urlsafe(24)
        record.write(
            {
                "in_flight_count": record.in_flight_count + 1,
                "last_attempt_at": now,
            }
        )
        return {"allowed": True, "attempt_token": token}

    @api.model
    def api_finish_login_attempt(self, login_key, source_ip_hmac, attempt_token, succeeded):
        """Releases the reservation `api_begin_login_attempt` took and books
        the outcome. `attempt_token` is returned for tracing and to let the
        caller prove it is finishing its own attempt; the counter itself is
        per (login, ip) row rather than per token, so the token is not
        load-bearing for correctness. Do not let a later change make it
        load-bearing without persisting it.
        """
        self.env["picking.assistant.api.mixin"]._require_api_service()
        now = fields.Datetime.now()
        record = self.sudo()._lock_or_create(login_key, source_ip_hmac, now)
        values = {"in_flight_count": max(0, record.in_flight_count - 1)}
        if not succeeded:
            values.update(self._failure_values(record, now))
        else:
            # Deviation from the brief's literal values (authorised in fix
            # round 1 review): the brief's snippet only cleared
            # `failure_count` and `locked_until` here, leaving
            # `window_started_at` stale. That is a live bug, not a style
            # choice: `_failure_values` anchors `locked_until` at
            # `window_started_at + FAILURE_WINDOW`, so a stale window from
            # BEFORE this success silently shortens the next lockout --
            # e.g. failures at t=0, a success at t=1 that does not reset
            # the window, then five failures at t=14min would lock out
            # until t=15min: a one-minute lockout instead of a full
            # fifteen-minute `FAILURE_WINDOW`. The legacy
            # `api_record_login_result` success branch reset all four
            # fields for exactly this reason; the backend now calls only
            # this method, so the same reset belongs here.
            values.update(
                {
                    "failure_count": 0,
                    "window_started_at": False,
                    "locked_until": False,
                    "last_attempt_at": now,
                    "expires_at": now + ROW_TTL,
                }
            )
        record.write(values)
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
