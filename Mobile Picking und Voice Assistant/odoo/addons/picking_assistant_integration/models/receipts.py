import json
import logging
import secrets
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .integration_job import TERMINAL_STATES

_logger = logging.getLogger(__name__)

# Der EINE Text, den ein abgelehnter Lease-Zugriff nach aussen sieht. Ein
# eigener Text pro Grund waere ein Orakel: der Aufrufer koennte daran ablesen,
# ob er den Token erraten hat oder nur zu spaet kam.
LEASE_REFUSED_MESSAGE = "Processing lease mismatch."

# Replay-window retention for webhook nonces. The spec floor is 600 seconds;
# keep the stored window strictly above it.
MIN_NONCE_RETENTION_SECONDS = 600
NONCE_RETENTION_SECONDS = 900
assert NONCE_RETENTION_SECONDS >= MIN_NONCE_RETENTION_SECONDS

PROCESSING_LEASE_SECONDS = 300  # five-minute processing lease
CALLBACK_STATUSES = {
    "running",
    "succeeded",
    "review_required",
    "failed",
    "retry_scheduled",
}
NONCE_DIRECTIONS = ("backend_to_n8n", "n8n_to_backend")

# Der von Odoo vergebene Name der (direction, key_id, nonce)-Unique-Constraint.
# `_reserve` erkennt einen Replay daran, weil das die EINZIGE Information ist,
# die nicht vom Transaktions-Snapshot abhaengt. Ein Test haelt diesen Namen
# gegen den tatsaechlichen Namen in der Datenbank -- laeuft er weg, faellt die
# Klassifizierung still auf "roher Datenbankfehler nach aussen" zurueck.
NONCE_UNIQUE_CONSTRAINT = "picking_assistant_webhook_nonce_nonce_unique"

# Eine globale Sperr-Reihenfolge, ausnahmslos, in jedem Pfad. Zwei Pfade mit
# entgegengesetzter Reihenfolge sind ein Deadlock-Zyklus, und Postgres loest
# den mit 40P01 auf -- also mit einem 500er unter genau der Last, fuer die das
# System gebaut wurde.
#
# Die Nonce steht bewusst VORNE: schlaegt eine spaetere Validierung fehl, rollt
# die gesamte RPC-Transaktion inklusive Nonce-Reservierung zurueck, es wird
# also keine Nonce verbrannt.
LOCK_ORDER = ("nonce", "job", "receipt", "outbox")


class PickingAssistantWebhookNonce(models.Model):
    _name = "picking.assistant.webhook.nonce"
    _description = "Picking Assistant Webhook Nonce"

    direction = fields.Selection(
        [("backend_to_n8n", "Backend to n8n"), ("n8n_to_backend", "n8n to Backend")],
        required=True,
        index=True,
    )
    key_id = fields.Char(required=True, index=True)
    nonce = fields.Char(required=True, index=True)
    event_id = fields.Char(index=True)
    received_at = fields.Datetime(required=True, default=fields.Datetime.now)
    expires_at = fields.Datetime(required=True, index=True)

    _nonce_unique = models.Constraint(
        "UNIQUE(direction, key_id, nonce)", "Webhook nonce must be unique."
    )

    @api.model
    def _reserve(self, direction, key_id, nonce, event_id=False):
        """Reserve a (direction, key_id, nonce) triple. A collision is never a
        deduplicated success: the race is contained in a savepoint and every
        reuse raises ValidationError -- auch dann, wenn der Gewinner in einer
        ANDEREN Transaktion sitzt (siehe Klassifizierung unten)."""
        if direction not in NONCE_DIRECTIONS:
            raise ValidationError("Unknown nonce direction.")
        if not key_id or not nonce:
            raise ValidationError("Nonce key and value are required.")
        now = fields.Datetime.now()
        try:
            with self.env.cr.savepoint():
                record = self.sudo().create(
                    {
                        "direction": direction,
                        "key_id": key_id,
                        "nonce": nonce,
                        "event_id": event_id or False,
                        "received_at": now,
                        "expires_at": now
                        + timedelta(seconds=NONCE_RETENTION_SECONDS),
                    }
                )
                record.flush_recordset()
            return record
        except IntegrityError as exc:
            # Klassifizieren, nie stillschweigend deduplizieren: ein Replay
            # wird abgelehnt, jede andere Constraint-Verletzung fliegt weiter.
            #
            # Der Constraint-Name kommt aus der Diagnose der Ausnahme SELBST.
            # Frueher stand hier ein SELECT, der nachsah, ob die Zeile
            # existiert -- und der ist unter echter Nebenlaeufigkeit falsch:
            # Odoo faehrt REPEATABLE READ, der Snapshot dieser Transaktion ist
            # aelter als der Commit des Gewinners, der SELECT fand also nichts
            # und das blanke `raise` liess eine ROHE psycopg2.UniqueViolation
            # nach aussen. Aus einer sauberen fachlichen Ablehnung wurde damit
            # ein 500. Sichtbar wurde das erst, als der Lock-Order-Test zwei
            # echte Transaktionen gegeneinander laufen liess; auf einem Cursor
            # sieht der SELECT die eigene, noch ungecommittete Zeile und der
            # Fehler existiert nicht.
            #
            # Der SELECT bleibt nur als Rueckfallebene, falls der Treiber
            # keinen Constraint-Namen liefert.
            if getattr(exc.diag, "constraint_name", None) == NONCE_UNIQUE_CONSTRAINT:
                raise ValidationError("Webhook nonce replay.") from exc
            self.env.cr.execute(
                "SELECT id FROM picking_assistant_webhook_nonce "
                "WHERE direction = %s AND key_id = %s AND nonce = %s",
                (direction, key_id, nonce),
            )
            if self.env.cr.fetchone():
                raise ValidationError("Webhook nonce replay.") from exc
            raise

    @api.model
    def api_reserve_request_nonce(self, direction, key_id, nonce, event_id=False):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        record = self._reserve(direction, key_id, nonce, event_id=event_id)
        return {
            "reserved": True,
            "expires_at": fields.Datetime.to_string(record.expires_at),
        }


class PickingAssistantEventReceipt(models.Model):
    _name = "picking.assistant.event.receipt"
    _description = "Picking Assistant Event Receipt"

    event_id = fields.Char(required=True, index=True)
    job_record_id = fields.Many2one(
        "picking.assistant.integration.job", required=True, ondelete="cascade"
    )
    payload_fingerprint = fields.Char(required=True)
    delivery_generation = fields.Integer(required=True)
    state = fields.Selection(
        [
            ("accepted", "Accepted"),
            ("processing", "Processing"),
            ("completed", "Completed"),
            ("retryable", "Retryable"),
        ],
        required=True,
    )
    processing_lease_token = fields.Char()
    processing_lease_expires_at = fields.Datetime(index=True)
    first_received_at = fields.Datetime(required=True, default=fields.Datetime.now)
    last_received_at = fields.Datetime(required=True, default=fields.Datetime.now)

    _event_receipt_unique = models.Constraint(
        "UNIQUE(event_id)", "Event receipt must be unique."
    )

    def _assert_active_lease(
        self, job, receipt, generation, supplied_token, now, require_token=True
    ):
        """Die einzige Stelle, die eine Processing-Lease fuer gueltig erklaert.

        MUSS unter gehaltenen Row-Locks und nach `invalidate_recordset()`
        aufgerufen werden -- ohne Lock liest sie einen Wert, der beim
        Zurueckkehren schon falsch sein kann.

        Geprueft wird ALLES, nicht eine Teilmenge: Zugehoerigkeit, Generation,
        Zustand, Token und Ablauf. Frueher pruefte `api_accept_event` den
        Ablauf und `api_apply_callback` nicht -- genau das Muster, das dieser
        Review-Durchgang wiederholt gefunden hat.

        `require_token=False` ist die EINE benannte, greppbare Ausnahme: die
        Ressourcenrouten (`_require_current_generation` in `resources.py`)
        bekommen ueber ihren RPC-Vertrag heute gar kein Lease-Token
        mitgeliefert, koennen also nur "dieser Job hat eine laufende Lease"
        fragen statt "du BIST der Lease-Inhaber". Das ist die zweite Haelfte
        von Review-Befund #5 und braucht eine Vertragsaenderung an der
        n8n-Schnittstelle; bis dahin laufen auch diese Aufrufer durch DIESE
        Funktion, damit Zustand und Ablauf nirgends zweitgemeint werden.

        REIHENFOLGE UND TEXT SIND SICHERHEITSRELEVANT (Fix-Runde 1, Befund 1).
        Der Ablauf wird VOR dem Token-Vergleich geprueft, und jeder Fehlschlag
        nach aussen traegt denselben Text. Stuende der Token-Vergleich vorn und
        haette der Ablauf einen eigenen Text, waere "abgelaufen" nur bei einem
        RICHTIGEN Token erreichbar -- also ein positives Signal auf einen
        geratenen Token. Der konkrete Grund bleibt serverseitig im
        Debug-Log, mit Receipt-ID und NIEMALS mit dem Token.
        """

        def refuse(reason):
            _logger.debug(
                "processing lease refused (%s) for receipt %s on job %s",
                reason,
                receipt.id,
                job.id,
            )
            raise ValidationError(LEASE_REFUSED_MESSAGE)

        if receipt.job_record_id.id != job.id:
            refuse("receipt does not belong to this job")
        if generation != job.delivery_generation:
            refuse("delivery generation mismatch")
        if receipt.state != "processing":
            refuse("receipt is not in state processing")
        if not receipt.processing_lease_token:
            refuse("receipt holds no lease token")
        # Ablauf zuerst, Token danach: siehe Docstring.
        if self._lease_has_expired(receipt, now):
            refuse("lease expired")
        if require_token:
            if not supplied_token:
                refuse("no lease token supplied")
            if not secrets.compare_digest(
                receipt.processing_lease_token, supplied_token
            ):
                refuse("lease token mismatch")

    def _lease_has_expired(self, receipt, now):
        """"Diese Lease existiert, ist aber abgelaufen" -- als EIN Ausdruck.

        `_assert_active_lease` benutzt diesen Ausdruck fuer seinen
        Ablauf-Schritt, `api_accept_event` fragt ihn danach, WARUM die Lease
        abgelehnt wurde (abgelaufen vs. gar keine). Damit gibt es weiterhin
        genau eine Definition von "abgelaufen"; sie kann nicht zwischen
        Dedup-Antwort und Callback-Antwort auseinanderlaufen.

        Das ist ausschliesslich eine SERVERSEITIGE Unterscheidung. Nach aussen
        traegt jede Ablehnung aus `_assert_active_lease` unveraendert
        LEASE_REFUSED_MESSAGE -- siehe dessen Docstring.
        """
        return bool(
            receipt.state == "processing"
            and receipt.processing_lease_token
            and (
                not receipt.processing_lease_expires_at
                or receipt.processing_lease_expires_at <= now
            )
        )

    def _lock_existing(self, event_id):
        """Lock the receipt for an event and re-read it from the locked row.

        Die `invalidate_recordset()` ist keine Kosmetik, auch wenn `browse()`
        auf eine frisch selektierte ID heute meist einen leeren Cache trifft:
        die Lane-Regel lautet "auf JEDES FOR UPDATE folgt ein
        `invalidate_recordset()`", und das hier war die einzige Ausnahme im
        Addon. Eine Regel mit einer Ausnahme ist keine Regel -- der naechste
        Aufrufer, der den Receipt vor dem Lock schon einmal angefasst hat,
        laese sonst den Vor-Lock-Zustand.
        """
        self.sudo().flush_model()
        self.env.cr.execute(
            "SELECT id FROM picking_assistant_event_receipt "
            "WHERE event_id = %s FOR UPDATE",
            (event_id,),
        )
        row = self.env.cr.fetchone()
        if not row:
            return self.sudo().browse()
        receipt = self.sudo().browse(row[0])
        receipt.invalidate_recordset()
        return receipt

    @api.model
    def api_accept_event(
        self,
        event_id,
        job_id,
        payload_fingerprint,
        ingress_key_id,
        ingress_nonce,
        delivery_generation,
        acceptance_key_id,
        acceptance_nonce,
    ):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        nonces = self.env["picking.assistant.webhook.nonce"]
        # 2. LOCK_ORDER[0] -- "nonce". Diese beiden Reservierungen standen
        # frueher HINTER der Job-Sperre, waehrend `api_apply_callback` sie vor
        # seiner Job-Sperre macht. Zwei Requests mit derselben Nonce hielten
        # damit je eine Haelfte eines Zyklus, und Postgres brach einen von
        # beiden mit 40P01 ab (Review-Befund #6).
        #
        # Dass eine spaetere Validierung hier nun eine Nonce "verbraucht" hat,
        # ist kein Verlust: der RPC-Dispatcher rollt bei ValidationError die
        # gesamte Transaktion zurueck, die Reservierung verschwindet mit ihr.
        # Ein Test, der `api_accept_event` direkt aufruft, muss diese
        # Transaktionsgrenze selbst nachbilden (siehe
        # test_wrong_job_id_causes_no_nonce_or_receipt_write).
        nonces._reserve(
            "n8n_to_backend", acceptance_key_id, acceptance_nonce, event_id=event_id
        )
        # Jede Wiederverwendung der Ingress-Nonce wird abgelehnt.
        nonces._reserve(
            "backend_to_n8n", ingress_key_id, ingress_nonce, event_id=event_id
        )
        outboxes = self.env["picking.assistant.outbox"].sudo()
        jobs = self.env["picking.assistant.integration.job"].sudo()
        # 3. resolve identifiers WITHOUT locks, then acquire the remaining
        # locks in LOCK_ORDER (multi-table FOR UPDATE OF implies no portable
        # acquisition order). The fingerprint/linkage check below is a
        # lock-free early reject; the authoritative recheck happens under the
        # outbox lock further down (readonly=True fields are not enforced
        # against privileged ORM writes, so the early read can go stale).
        outboxes.flush_model()
        jobs.flush_model()
        self.env.cr.execute(
            "SELECT id, job_record_id FROM picking_assistant_outbox "
            "WHERE event_id = %s",
            (event_id,),
        )
        row = self.env.cr.fetchone()
        if not row:
            raise ValidationError("Unknown outbox event.")
        outbox = outboxes.browse(row[0])
        job = jobs.browse(row[1])
        # 4. LOCK_ORDER[1] -- "job".
        self.env.cr.execute(
            "SELECT id FROM picking_assistant_integration_job "
            "WHERE id = %s FOR UPDATE",
            (job.id,),
        )
        # Re-read both records post-lock instead of trusting pre-lock cache.
        job.invalidate_recordset()
        outbox.invalidate_recordset()
        # 5. reject before any create/write when a supplied value differs.
        if job.job_id != job_id:
            raise ValidationError("Job ID mismatch.")
        if outbox.payload_fingerprint != payload_fingerprint:
            raise ValidationError("Payload fingerprint mismatch.")
        if int(delivery_generation) != job.delivery_generation:
            raise ValidationError("Delivery generation mismatch.")
        now = fields.Datetime.now()
        # 6. LOCK_ORDER[2] -- "receipt": create or lock the event receipt.
        receipt = self._lock_existing(event_id)
        if not receipt:
            try:
                with self.env.cr.savepoint():
                    receipt = self.sudo().create(
                        {
                            "event_id": event_id,
                            "job_record_id": job.id,
                            "payload_fingerprint": payload_fingerprint,
                            "delivery_generation": job.delivery_generation,
                            "state": "accepted",
                            "first_received_at": now,
                            "last_received_at": now,
                        }
                    )
                    receipt.flush_recordset()
            except IntegrityError:
                receipt = self._lock_existing(event_id)
        else:
            receipt.write({"last_received_at": now})
        # 6b. LOCK_ORDER[3] -- "outbox", then
        # revalidate the outbox from the row under lock: a concurrent
        # privileged write may have changed linkage or fingerprint since the
        # lock-free early check, and the acceptance decision rests on them.
        outboxes.flush_model()
        self.env.cr.execute(
            "SELECT id FROM picking_assistant_outbox "
            "WHERE id = %s FOR UPDATE",
            (outbox.id,),
        )
        if not self.env.cr.fetchone():
            raise ValidationError("Unknown outbox event.")
        outbox.invalidate_recordset()
        if (
            outbox.event_id != event_id
            or outbox.job_record_id.id != job.id
            or outbox.payload_fingerprint != payload_fingerprint
        ):
            raise ValidationError("Outbox event changed during acceptance.")
        # 7. deduplicate active processing and completed receipts. "Is there a
        # live lease" is asked of the ONE primitive, not re-derived here: the
        # dedup answer and the callback answer must never drift apart. The
        # primitive raises, so the boolean is its absence of a complaint.
        try:
            self._assert_active_lease(
                job,
                receipt,
                generation=job.delivery_generation,
                supplied_token=False,
                now=now,
                require_token=False,
            )
            lease_active = True
        except ValidationError:
            lease_active = False
        if lease_active or receipt.state == "completed":
            return {
                "accepted": True,
                "event_id": event_id,
                "job_id": job.job_id,
                "process": False,
                "processing_lease_token": False,
            }
        # 7b. Eine ABGELAUFENE Lease ist keine freie Bahn fuer ein neues Token
        # (Review-Befund #5, zweite Haelfte). Frueher lief genau dieser Fall in
        # Schritt 8 und bekam ein frisches Token unter DERSELBEN Generation:
        # das alte Token passte danach nicht mehr, aber jeder Consumer, der an
        # "Generation plus irgendeine aktive Lease" gebunden war statt an das
        # Token -- die Ressourcenrouten sind genau das --, arbeitete fuer den
        # alten Worker weiter. Der einzige Ausgang aus einer abgelaufenen Lease
        # ist `_recover_expired_lease`, und die erhoeht die Generation.
        if self._lease_has_expired(receipt, now):
            raise ValidationError("processing_lease_expired")
        # 8. hand out a fresh five-minute processing lease.
        token = secrets.token_urlsafe(32)
        lease_expires = now + timedelta(seconds=PROCESSING_LEASE_SECONDS)
        receipt.write(
            {
                "state": "processing",
                "processing_lease_token": token,
                "processing_lease_expires_at": lease_expires,
                "delivery_generation": job.delivery_generation,
                "last_received_at": now,
            }
        )
        job_values = {
            "processing_lease_token": token,
            "processing_lease_expires_at": lease_expires,
        }
        if int(delivery_generation) > 1:
            job_values["attempt"] = job.attempt + 1
        job.write(job_values)
        return {
            "accepted": True,
            "event_id": event_id,
            "job_id": job.job_id,
            "process": True,
            "processing_lease_token": token,
        }


class PickingAssistantCallbackReceipt(models.Model):
    _name = "picking.assistant.callback.receipt"
    _description = "Picking Assistant Callback Receipt"

    callback_id = fields.Char(required=True, index=True)
    source_event_id = fields.Char(required=True, index=True)
    job_record_id = fields.Many2one(
        "picking.assistant.integration.job", required=True, ondelete="cascade"
    )
    sequence = fields.Integer(required=True)
    fingerprint = fields.Char(required=True)
    response_status = fields.Integer(required=True)
    response_body = fields.Text(required=True)
    received_at = fields.Datetime(required=True, default=fields.Datetime.now)

    _callback_id_unique = models.Constraint(
        "UNIQUE(callback_id)", "Callback ID must be unique."
    )
    _job_sequence_unique = models.Constraint(
        "UNIQUE(job_record_id, sequence)", "Job callback sequence must be unique."
    )

    def _store_response(self, job, callback_id, source_event_id, sequence,
                        fingerprint, response):
        """Persist the deterministic response for the no-mutation
        (ignored_stale) path. A (job, sequence) collision means sequence
        reuse; applied callbacks store inside the mutation savepoint in
        api_apply_callback instead."""
        try:
            with self.env.cr.savepoint():
                record = self.sudo().create(
                    {
                        "callback_id": callback_id,
                        "source_event_id": source_event_id,
                        "job_record_id": job.id,
                        "sequence": int(sequence),
                        "fingerprint": fingerprint,
                        "response_status": 200,
                        "response_body": json.dumps(response, sort_keys=True),
                    }
                )
                record.flush_recordset()
            return record
        except IntegrityError:
            self.env.invalidate_all()
            existing = self.sudo().search(
                [("callback_id", "=", callback_id)], limit=1
            )
            if existing and existing.fingerprint == fingerprint:
                return existing
            raise ValidationError("Callback sequence conflict.")

    @api.model
    def api_apply_callback(self, callback, callback_fingerprint, key_id, nonce):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        if not isinstance(callback, dict):
            raise ValidationError("Callback must be an object.")
        callback_id = callback.get("callback_id")
        source_event_id = callback.get("source_event_id")
        job_id = callback.get("job_id")
        status = callback.get("status")
        if not callback_id or not source_event_id or not job_id:
            raise ValidationError("Callback identifiers are required.")
        if status not in CALLBACK_STATUSES:
            raise ValidationError("Unknown callback status.")
        try:
            sequence = int(callback.get("sequence"))
            generation = int(callback.get("delivery_generation"))
        except (TypeError, ValueError):
            raise ValidationError("Callback sequence and generation must be integers.")
        result = callback.get("result") or {}
        error = callback.get("error") or {}
        metrics = callback.get("metrics") or {}

        # Reserve the callback nonce, then lock job and event receipt.
        self.env["picking.assistant.webhook.nonce"]._reserve(
            "n8n_to_backend", key_id, nonce, event_id=source_event_id
        )
        jobs = self.env["picking.assistant.integration.job"].sudo()
        receipts = self.env["picking.assistant.event.receipt"].sudo()
        jobs.flush_model()
        receipts.flush_model()
        self.sudo().flush_model()
        self.env.cr.execute(
            "SELECT id FROM picking_assistant_integration_job "
            "WHERE job_id = %s FOR UPDATE",
            (job_id,),
        )
        row = self.env.cr.fetchone()
        if not row:
            raise ValidationError("Unknown job.")
        job = jobs.browse(row[0])
        job.invalidate_recordset()
        self.env.cr.execute(
            "SELECT id FROM picking_assistant_event_receipt "
            "WHERE event_id = %s FOR UPDATE",
            (source_event_id,),
        )
        row = self.env.cr.fetchone()
        if not row:
            raise ValidationError("Unknown event receipt.")
        receipt = receipts.browse(row[0])
        receipt.invalidate_recordset()
        if receipt.job_record_id.id != job.id:
            raise ValidationError("Callback event does not belong to this job.")

        # Same callback ID: replay returns the stored response, a different
        # fingerprint is a conflict.
        existing = self.sudo().search([("callback_id", "=", callback_id)], limit=1)
        if existing:
            if existing.fingerprint != callback_fingerprint:
                raise ValidationError("Callback fingerprint conflict.")
            return json.loads(existing.response_body)

        # Generation, ownership, state, token AND expiry must match the locked
        # job/receipt. Every one of those questions is answered by the single
        # primitive on the receipt model -- this call site used to answer four
        # of the five itself and silently skipped the expiry.
        now = fields.Datetime.now()
        receipts._assert_active_lease(
            job,
            receipt,
            generation=generation,
            supplied_token=callback.get("processing_lease_token") or "",
            now=now,
        )

        if sequence == job.sequence:
            raise ValidationError("Callback sequence conflict.")
        if sequence < job.sequence:
            response = {
                "status": "ignored_stale",
                "callback_id": callback_id,
                "job_id": job.job_id,
                "sequence": sequence,
                "job_state": job.state,
            }
            self._store_response(
                job, callback_id, source_event_id, sequence,
                callback_fingerprint, response,
            )
            return response

        if job.state in TERMINAL_STATES:
            raise ValidationError("Job is terminal and cannot reopen.")
        # The job mutation and the callback receipt insert share ONE
        # savepoint: if a concurrent callback wins the unique callback-id /
        # (job, sequence) race, the loser's job change rolls back with it
        # instead of surviving next to the winner's stored response.
        try:
            with self.env.cr.savepoint():
                if status == "running":
                    if job.state in ("queued", "retry_scheduled"):
                        job._transition(
                            "running",
                            sequence=sequence,
                            result=result,
                            error=error,
                            metrics=metrics,
                        )
                    else:  # already running: accept the higher sequence
                        job.write({"sequence": sequence})
                    lease_expires = now + timedelta(
                        seconds=PROCESSING_LEASE_SECONDS
                    )
                    receipt.write(
                        {
                            "processing_lease_expires_at": lease_expires,
                            "last_received_at": now,
                        }
                    )
                    job.write({"processing_lease_expires_at": lease_expires})
                elif status in TERMINAL_STATES:
                    if job.state in ("queued", "retry_scheduled"):
                        job._transition("running", sequence=sequence)
                    job._transition(
                        status,
                        sequence=sequence,
                        result=result,
                        error=error,
                        metrics=metrics,
                    )
                    job.write({"processing_lease_token": False})
                    receipt.write(
                        {
                            "state": "completed",
                            "processing_lease_token": False,
                            "processing_lease_expires_at": False,
                            "last_received_at": now,
                        }
                    )
                else:  # retry_scheduled
                    if job.state == "queued":
                        job._transition("running", sequence=sequence)
                    job._transition(
                        "retry_scheduled",
                        sequence=sequence,
                        result=result,
                        error=error,
                        metrics=metrics,
                    )
                    job.write(
                        {
                            "delivery_generation": job.delivery_generation + 1,
                            "processing_lease_token": False,
                            "processing_lease_expires_at": False,
                        }
                    )
                    receipt.write(
                        {
                            "state": "retryable",
                            "processing_lease_token": False,
                            "processing_lease_expires_at": False,
                            "delivery_generation": job.delivery_generation,
                            "last_received_at": now,
                        }
                    )
                    # Third lock in the global job -> receipt -> outbox order.
                    outboxes = self.env["picking.assistant.outbox"].sudo()
                    outboxes.flush_model()
                    self.env.cr.execute(
                        "SELECT id FROM picking_assistant_outbox "
                        "WHERE event_id = %s FOR UPDATE",
                        (source_event_id,),
                    )
                    outbox_row = self.env.cr.fetchone()
                    if outbox_row:
                        outbox = outboxes.browse(outbox_row[0])
                        outbox.invalidate_recordset()
                        # Same event returns to pending, envelope unchanged.
                        outbox.write(
                            {
                                "state": "pending",
                                "next_attempt_at": now,
                                "lease_owner": False,
                                "lease_expires_at": False,
                            }
                        )
                response = {
                    "status": "applied",
                    "callback_id": callback_id,
                    "job_id": job.job_id,
                    "sequence": sequence,
                    "job_state": job.state,
                }
                record = self.sudo().create(
                    {
                        "callback_id": callback_id,
                        "source_event_id": source_event_id,
                        "job_record_id": job.id,
                        "sequence": sequence,
                        "fingerprint": callback_fingerprint,
                        "response_status": 200,
                        "response_body": json.dumps(response, sort_keys=True),
                    }
                )
                record.flush_recordset()
        except IntegrityError:
            # Loser of the identity race: the savepoint rolled the job
            # mutation back. Drop rolled-back cache, then classify.
            self.env.invalidate_all()
            existing = self.sudo().search(
                [("callback_id", "=", callback_id)], limit=1
            )
            if existing:
                if existing.fingerprint != callback_fingerprint:
                    raise ValidationError("Callback fingerprint conflict.")
                return json.loads(existing.response_body)
            raise ValidationError("Callback sequence conflict.")
        return response
