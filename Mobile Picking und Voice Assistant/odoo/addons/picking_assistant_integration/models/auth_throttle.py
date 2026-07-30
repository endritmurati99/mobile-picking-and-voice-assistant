import secrets
from datetime import timedelta

import psycopg2
from psycopg2 import IntegrityError

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

# Der von Odoo vergebene Name der (login_key, source_ip_hmac)-Unique-
# Constraint. `_lock_or_create` klassifiziert einen INSERT-Konflikt daran,
# weil das die EINZIGE Information ist, die nicht vom REPEATABLE-READ-
# Snapshot dieser Transaktion abhaengt (siehe dort). Ein Test haelt diesen
# Namen gegen den tatsaechlichen Namen in der Datenbank -- laeuft er weg,
# faellt die Klassifizierung still auf eine rohe psycopg2-Ausnahme zurueck.
THROTTLE_UNIQUE_CONSTRAINT = (
    "picking_assistant_auth_throttle_login_key_source_ip_hmac_unique"
)


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
            record.invalidate_recordset()
            return record
        except IntegrityError as exc:
            # Klassifizieren wie `_reserve` (receipts.py): der Constraint-
            # Name aus der Diagnose der Ausnahme SELBST ist das einzige
            # Signal, das nicht vom Snapshot dieser Transaktion abhaengt.
            #
            # Anders als bei `_reserve` ist ein Treffer hier aber kein
            # abzulehnender Replay, sondern eine ANDERE Transaktion, die das
            # Rennen um genau die Zeile gewonnen hat, die WIR gerade
            # anlegen wollten. Frueher stand hier ein erneutes
            # `SELECT ... FOR UPDATE` -- und das ist unter Odoo's REPEATABLE
            # READ unheilbar falsch, nicht nur unzuverlaessig: der Snapshot
            # DIESER Transaktion wurde VOR dem Commit der Gewinner-
            # Transaktion gezogen, ein erneutes SELECT auf demselben Cursor
            # findet also in KEINEM Fall eine Zeile, egal wie oft man es
            # wiederholt. `browse(row[0])` auf `row = None` warf ein rohes
            # `TypeError: 'NoneType' object is not subscriptable` (im Review
            # von Task 3 eskalierter Fund) -- auf dem Login-Pfad, wo
            # `retrying()` (Odoo's RPC-Dispatch-Retry) einen `TypeError`
            # NICHT wiederholt, weil es kein Serialisierungs- oder
            # Deadlock-Fehler ist. Er surfaced also als 500 statt eines
            # sauberen 401, und der Fehlschlag der verlierenden Transaktion
            # wird nicht gebucht, weil ihre gesamte Transaktion zurueckrollt.
            #
            # Es gibt innerhalb DIESER Transaktion keinen snapshot-sicheren
            # Weg, die Zeile des Gewinners zurueckzugeben -- der einzige Ort
            # mit einem Snapshot, der den Gewinner-Commit sehen KANN, ist
            # eine neue Transaktion. Also erzwingen wir genau das: eine
            # `SerializationFailure` (SQLSTATE 40001) ist exakt die Klasse,
            # die `retrying()` wiederholt. Der Retry laeuft mit frischem
            # Snapshot erneut durch `_lock_or_create` und faellt dann auf den
            # normalen `if row:`-Zweig oben, der die inzwischen committete
            # Zeile sieht.
            if (
                getattr(exc.diag, "constraint_name", None)
                == THROTTLE_UNIQUE_CONSTRAINT
            ):
                raise psycopg2.errors.SerializationFailure(
                    "Login throttle row created concurrently."
                ) from exc
            raise

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
            values.update({"failure_count": 0, "locked_until": False})
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
