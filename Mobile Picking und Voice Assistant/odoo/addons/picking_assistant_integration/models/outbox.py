from datetime import timedelta

import psycopg2

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL

BACKOFF_SECONDS = (10, 60, 300, 1800, 7200, 21600, 21600, 21600, 21600, 21600)


class PickingAssistantOutbox(models.Model):
    _name = "picking.assistant.outbox"
    _description = "Picking Assistant Outbox"
    _order = "next_attempt_at, id"

    event_id = fields.Char(required=True, index=True, readonly=True)
    job_record_id = fields.Many2one(
        "picking.assistant.integration.job",
        required=True,
        ondelete="cascade",
        index=True,
        readonly=True,
    )
    job_id = fields.Char(related="job_record_id.job_id", store=True, index=True)
    event_name = fields.Char(required=True, readonly=True)
    envelope_text = fields.Text(required=True, readonly=True)
    payload_fingerprint = fields.Char(required=True, readonly=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("leased", "Leased"),
            ("delivered", "Delivered"),
            ("dead", "Dead"),
        ],
        required=True,
        default="pending",
        index=True,
    )
    attempt_count = fields.Integer(required=True, default=0)
    next_attempt_at = fields.Datetime(required=True, index=True)
    lease_owner = fields.Char(index=True)
    lease_expires_at = fields.Datetime(index=True)
    last_error_code = fields.Char()
    last_error_message = fields.Char()
    delivered_at = fields.Datetime(index=True)

    _event_id_unique = models.Constraint(
        "UNIQUE(event_id)", "Event ID must be unique."
    )

    @api.model
    def api_lease_due(self, worker_id, limit=50, lease_seconds=60):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        size = max(1, min(int(limit), 200))
        now = fields.Datetime.now()
        # Pending ORM writes (e.g. an earlier lease in this transaction) must
        # hit the database before the raw SELECT filters on state/lease.
        self.sudo().flush_model()
        self.env.cr.execute(
            SQL(
                """
                SELECT id
                  FROM picking_assistant_outbox
                 WHERE (
                       (state = 'pending' AND next_attempt_at <= %(now)s)
                    OR (state = 'leased' AND lease_expires_at <= %(now)s)
                 )
                 ORDER BY next_attempt_at, id
                 FOR UPDATE SKIP LOCKED
                 LIMIT %(limit)s
                """,
                now=now,
                limit=size,
            )
        )
        ids = [row[0] for row in self.env.cr.fetchall()]
        records = self.sudo().browse(ids)
        # The lease must be computed from the locked rows, not from values
        # cached before the lock (same fencing as _owned_lease).
        records.invalidate_recordset()
        for record in records:
            record.write(
                {
                    "state": "leased",
                    "attempt_count": record.attempt_count + 1,
                    "lease_owner": worker_id,
                    "lease_expires_at": now + timedelta(seconds=int(lease_seconds)),
                }
            )
        return [
            {
                "event_id": record.event_id,
                "job_id": record.job_id,
                "event_name": record.event_name,
                "envelope_text": record.envelope_text,
                "payload_fingerprint": record.payload_fingerprint,
                "delivery_generation": record.job_record_id.delivery_generation,
                "attempt_count": record.attempt_count,
            }
            for record in records
        ]

    def _owned_lease(self, event_id, worker_id):
        """Lock the outbox row, then verify ownership AND that the lease is
        still live. Checking without the lock (or without expiry) would let an
        expired or superseded worker overwrite a newer worker's lease."""
        self.sudo().flush_model()
        self.env.cr.execute(
            "SELECT id FROM picking_assistant_outbox "
            "WHERE event_id = %s FOR UPDATE",
            (event_id,),
        )
        row = self.env.cr.fetchone()
        if not row:
            raise ValidationError("Outbox lease is not owned by this worker.")
        record = self.sudo().browse(row[0])
        # Ownership may have changed between our cache read and the lock.
        record.invalidate_recordset()
        now = fields.Datetime.now()
        if (
            record.state != "leased"
            or record.lease_owner != worker_id
            or not record.lease_expires_at
            or record.lease_expires_at <= now
        ):
            raise ValidationError("Outbox lease is not owned by this worker.")
        return record

    @api.model
    def api_ack_delivery(self, event_id, worker_id, accepted_event_id):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        record = self._owned_lease(event_id, worker_id)
        if accepted_event_id != record.event_id:
            raise ValidationError("Acceptance event ID mismatch.")
        record.write(
            {
                "state": "delivered",
                "delivered_at": fields.Datetime.now(),
                "lease_owner": False,
                "lease_expires_at": False,
                "last_error_code": False,
                "last_error_message": False,
            }
        )
        return {"state": "delivered", "event_id": record.event_id}

    @api.model
    def api_nack_delivery(self, event_id, worker_id, error_code, error_message):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        record = self._owned_lease(event_id, worker_id)
        attempt = record.attempt_count
        dead = attempt >= len(BACKOFF_SECONDS)
        retry_after = BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)]
        record.write(
            {
                "state": "dead" if dead else "pending",
                "next_attempt_at": fields.Datetime.now()
                + timedelta(seconds=retry_after),
                "lease_owner": False,
                "lease_expires_at": False,
                "last_error_code": str(error_code)[:64],
                "last_error_message": str(error_message)[:500],
            }
        )
        return {
            "state": record.state,
            "event_id": record.event_id,
            "attempt_count": attempt,
            "retry_after_seconds": retry_after,
        }

    @api.model
    def api_requeue_dead(self, event_id, supervisor_user_id, reason):
        """Put a dead-lettered event back to `pending`.

        Two supervisors requeuing the same event at once must not both
        succeed: one would reset a row the other has already reset (and
        possibly a lease a dispatcher has since re-acquired), delivering the
        event twice (review finding #7). The fix mirrors the pattern already
        used by `api_accept_event`: resolve identifiers WITHOUT a lock, take
        the lock in `LOCK_ORDER` (job ahead of outbox), then revalidate the
        locked row from the database instead of the pre-lock cache -- Task 3
        found that a re-SELECT after a conflict is not enough under Odoo's
        REPEATABLE READ, so the row is validated from the SAME statement that
        holds the lock, not a second one.
        """
        self.env["picking.assistant.api.mixin"]._require_api_service()
        # 1. Resolve and validate the actor BEFORE taking any lock. `.exists()`
        # alone would accept an archived or a share (portal/public) user that
        # still carries the group; both must be refused.
        supervisor = (
            self.env["res.users"].sudo().browse(int(supervisor_user_id)).exists()
        )
        if (
            not supervisor
            or not supervisor.active
            or supervisor.share
            or not supervisor.has_group(
                "picking_assistant_integration.group_supervisor"
            )
        ):
            raise AccessError("Supervisor role required.")

        outboxes = self.sudo()
        jobs = self.env["picking.assistant.integration.job"].sudo()
        outboxes.flush_model()
        # 2. Resolve the dead row's id and its job WITHOUT a lock. This is a
        # lock-free early reject only; the authoritative check happens below,
        # under the outbox lock.
        self.env.cr.execute(
            "SELECT id, job_record_id FROM picking_assistant_outbox "
            "WHERE event_id = %s AND state = 'dead'",
            (event_id,),
        )
        row = self.env.cr.fetchone()
        if not row:
            raise ValidationError("Dead outbox event not found.")
        record = outboxes.browse(row[0])
        job = jobs.browse(row[1])
        # 3. LOCK_ORDER[1] -- "job", ahead of "outbox". This method never
        # writes the job row; the lock exists solely so this path cannot form
        # a lock-order cycle with a path that legitimately needs both (e.g.
        # `api_accept_event`).
        self.env.cr.execute(
            "SELECT id FROM picking_assistant_integration_job "
            "WHERE id = %s FOR UPDATE",
            (job.id,),
        )
        # 4. LOCK_ORDER[3] -- "outbox". Under Odoo's REPEATABLE READ (Task 3),
        # a losing `FOR UPDATE` against a row a concurrent transaction has
        # ALREADY updated and committed does not block-then-return the new
        # tuple: it raises `SerializationFailure` (SQLSTATE 40001) right at
        # this statement. That is the authoritative signal that this requeue
        # lost the race -- classify it by the driver's error class, the same
        # way `_reserve` classifies a nonce replay by constraint name, rather
        # than re-reading a row under a snapshot Task 3 already showed is
        # stale. The savepoint contains the failure so the caller sees a
        # clean refusal instead of a raw psycopg2 error escaping the RPC
        # boundary.
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "SELECT id FROM picking_assistant_outbox WHERE id = %s "
                    "FOR UPDATE",
                    (record.id,),
                )
        except psycopg2.errors.SerializationFailure as exc:
            raise ValidationError("Dead outbox event not found.") from exc
        # 5. Revalidate from the locked row, not the pre-lock cache. This is
        # defensive-only under the race above (a `FOR UPDATE` that succeeds
        # here did so without SQLSTATE 40001, which under REPEATABLE READ
        # means no concurrent committed write happened -- so the row must
        # still read `dead`); it stays because the brief mandates it and
        # because it is the only guard left if a future caller acquires this
        # lock some other way.
        record.invalidate_recordset()
        if record.state != "dead":
            raise ValidationError("Dead outbox event not found.")
        record.write(
            {
                "state": "pending",
                "attempt_count": 0,
                "next_attempt_at": fields.Datetime.now(),
                "lease_owner": False,
                "lease_expires_at": False,
                "last_error_code": "manual_requeue",
                "last_error_message": str(reason)[:500],
            }
        )
        return {"state": "pending", "event_id": record.event_id}
