import json
from datetime import timedelta
from uuid import uuid4

from odoo import api, fields, models
from odoo.exceptions import ValidationError

JOB_STATES = [
    ("queued", "Queued"),
    ("running", "Running"),
    ("succeeded", "Succeeded"),
    ("review_required", "Review Required"),
    ("retry_scheduled", "Retry Scheduled"),
    ("failed", "Failed"),
]
TERMINAL_STATES = {"succeeded", "review_required", "failed"}
# Documented amendment to the brief's frozen table: queued -> retry_scheduled
# is the watchdog recovery edge (a processing lease can expire before the
# first callback moves the job to running). The brief's watchdog spec
# requires the edge; recording it here keeps TRANSITIONS the single source
# of truth instead of a parallel rule inside the watchdog helper.
TRANSITIONS = {
    "queued": {"running", "retry_scheduled"},
    "running": {"succeeded", "review_required", "retry_scheduled", "failed"},
    "retry_scheduled": {"running"},
}

# Audit retention windows (days); every cleanup skips legal_hold jobs.
RETENTION_DELIVERED_OUTBOX_DAYS = 30
RETENTION_DEAD_OUTBOX_DAYS = 90
RETENTION_EVENT_RECEIPT_DAYS = 90
RETENTION_CALLBACK_RECEIPT_DAYS = 90
RETENTION_JOB_DAYS = 90
SESSION_GC_GRACE_DAYS = 7


class PickingAssistantIntegrationJob(models.Model):
    _name = "picking.assistant.integration.job"
    _description = "Picking Assistant Integration Job"
    _order = "create_date desc"

    job_id = fields.Char(required=True, index=True, readonly=True)
    job_type = fields.Char(required=True, index=True, readonly=True)
    aggregate_model = fields.Char(required=True, readonly=True)
    aggregate_res_id = fields.Integer(required=True, readonly=True)
    aggregate_revision = fields.Integer(required=True, readonly=True)
    state = fields.Selection(JOB_STATES, required=True, default="queued", index=True)
    sequence = fields.Integer(required=True, default=0)
    attempt = fields.Integer(required=True, default=1)
    delivery_generation = fields.Integer(required=True, default=1)
    processing_lease_token = fields.Char(readonly=True)
    processing_lease_expires_at = fields.Datetime(index=True, readonly=True)
    supersedes_job_record_id = fields.Many2one(
        "picking.assistant.integration.job", ondelete="restrict", readonly=True
    )
    correlation_id = fields.Char(required=True, index=True, readonly=True)
    causation_id = fields.Char(index=True, readonly=True)
    result_json = fields.Text(readonly=True)
    error_json = fields.Text(readonly=True)
    metrics_json = fields.Text(readonly=True)
    started_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(index=True, readonly=True)
    legal_hold = fields.Boolean(default=False, index=True)

    _job_id_unique = models.Constraint("UNIQUE(job_id)", "Job ID must be unique.")
    _revision_positive = models.Constraint(
        "CHECK(aggregate_revision >= 1)", "Aggregate revision must be positive."
    )
    _generation_positive = models.Constraint(
        "CHECK(delivery_generation >= 1)", "Delivery generation must be positive."
    )
    _sequence_nonnegative = models.Constraint(
        "CHECK(sequence >= 0)", "Sequence must be nonnegative."
    )

    @api.model
    def _enqueue_job_event(
        self,
        *,
        job_type,
        aggregate_model,
        aggregate_res_id,
        aggregate_revision,
        event_id,
        event_name,
        envelope_text,
        payload_fingerprint,
        correlation_id,
        causation_id=False,
        job_id=False,
        supersedes_job_id=False,
    ):
        if not isinstance(envelope_text, str):
            raise ValidationError("Envelope must be lossless UTF-8 text.")
        supersedes = False
        if supersedes_job_id:
            supersedes = self.search(
                [("job_id", "=", supersedes_job_id)], limit=1
            )
            if not supersedes or supersedes.state not in TERMINAL_STATES:
                raise ValidationError("Superseded job must be terminal.")
        job = self.create(
            {
                "job_id": job_id or str(uuid4()),
                "job_type": job_type,
                "aggregate_model": aggregate_model,
                "aggregate_res_id": int(aggregate_res_id),
                "aggregate_revision": int(aggregate_revision),
                "correlation_id": correlation_id,
                "causation_id": causation_id or False,
                "supersedes_job_record_id": supersedes.id if supersedes else False,
            }
        )
        outbox = self.env["picking.assistant.outbox"].create(
            {
                "event_id": event_id,
                "job_record_id": job.id,
                "event_name": event_name,
                "envelope_text": envelope_text,
                "payload_fingerprint": payload_fingerprint,
                "state": "pending",
                "next_attempt_at": fields.Datetime.now(),
            }
        )
        return job, outbox

    def _api_payload(self):
        self.ensure_one()
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "state": self.state,
            "aggregate_model": self.aggregate_model,
            "aggregate_res_id": self.aggregate_res_id,
            "aggregate_revision": self.aggregate_revision,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id or None,
            "attempt": self.attempt,
            "delivery_generation": self.delivery_generation,
            "sequence": self.sequence,
            "result": json.loads(self.result_json or "{}"),
            "error": json.loads(self.error_json or "{}"),
            "metrics": json.loads(self.metrics_json or "{}"),
            "created_at": fields.Datetime.to_string(self.create_date),
            "started_at": fields.Datetime.to_string(self.started_at)
            if self.started_at
            else None,
            "completed_at": fields.Datetime.to_string(self.completed_at)
            if self.completed_at
            else None,
        }

    @api.model
    def api_get_job(self, job_id):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        job = self.sudo().search([("job_id", "=", job_id)], limit=1)
        return job._api_payload() if job else False

    def _transition(self, target, *, sequence, result=None, error=None, metrics=None):
        self.ensure_one()
        if target not in TRANSITIONS.get(self.state, set()):
            raise ValidationError(f"Illegal job transition {self.state} -> {target}.")
        now = fields.Datetime.now()
        values = {
            "state": target,
            "sequence": int(sequence),
            "result_json": json.dumps(result or {}, sort_keys=True),
            "error_json": json.dumps(error or {}, sort_keys=True),
            "metrics_json": json.dumps(metrics or {}, sort_keys=True),
        }
        if target == "running" and not self.started_at:
            values["started_at"] = now
        if target in TERMINAL_STATES:
            values["completed_at"] = now
            values["processing_lease_expires_at"] = False
        self.write(values)

    def _watchdog_retry_scheduled(self):
        """Watchdog recovery transition, validated against the authoritative
        TRANSITIONS table (which explicitly lists the queued/running ->
        retry_scheduled recovery edges). Bumps the delivery generation and
        clears the processing lease atomically with the state change."""
        self.ensure_one()
        if "retry_scheduled" not in TRANSITIONS.get(self.state, set()):
            raise ValidationError(
                f"Illegal watchdog recovery from {self.state}."
            )
        self.write(
            {
                "state": "retry_scheduled",
                "delivery_generation": self.delivery_generation + 1,
                "processing_lease_token": False,
                "processing_lease_expires_at": False,
            }
        )

    # ------------------------------------------------------------------
    # Crons
    # ------------------------------------------------------------------

    @api.model
    def _report_cron_progress(self, processed, remaining=0):
        """ir.cron._commit_progress commits the cursor even when called
        outside a cron run (verified in the Odoo-19 runtime), which is
        forbidden on test cursors. Only report when a real cron executes."""
        if self.env.context.get("ir_cron_progress_id"):
            self.env["ir.cron"]._commit_progress(processed, remaining=remaining)

    @api.model
    def _cron_recover_stalled_jobs(self, limit=200):
        """Every minute: recover event receipts whose processing lease expired
        without a terminal callback. Bumps the delivery generation and returns
        the same outbox event (unchanged envelope) to pending."""
        now = fields.Datetime.now()
        receipts = self.env["picking.assistant.event.receipt"].sudo()
        outboxes = self.env["picking.assistant.outbox"].sudo()
        receipts.flush_model()
        self.sudo().flush_model()
        outboxes.flush_model()
        # Candidate scan without locks; each candidate is then locked in the
        # ONE global order every multi-table path uses — job -> receipt ->
        # outbox — and re-validated under the lock.
        self.env.cr.execute(
            "SELECT id, job_record_id FROM picking_assistant_event_receipt "
            "WHERE state = 'processing' AND processing_lease_expires_at <= %s "
            "ORDER BY processing_lease_expires_at, id LIMIT %s",
            (now, max(1, int(limit))),
        )
        candidates = self.env.cr.fetchall()
        recovered = 0
        for receipt_id, job_record_id in candidates:
            self.env.cr.execute(
                "SELECT id FROM picking_assistant_integration_job "
                "WHERE id = %s FOR UPDATE SKIP LOCKED",
                (job_record_id,),
            )
            if not self.env.cr.fetchone():
                continue
            self.env.cr.execute(
                "SELECT id FROM picking_assistant_event_receipt "
                "WHERE id = %s AND state = 'processing' "
                "AND processing_lease_expires_at <= %s "
                "FOR UPDATE SKIP LOCKED",
                (receipt_id, now),
            )
            if not self.env.cr.fetchone():
                continue
            receipt = receipts.browse(receipt_id)
            job = self.sudo().browse(job_record_id)
            receipt.invalidate_recordset()
            job.invalidate_recordset()
            if job.state in ("queued", "running"):
                job._watchdog_retry_scheduled()
                receipt.write(
                    {
                        "state": "retryable",
                        "processing_lease_token": False,
                        "processing_lease_expires_at": False,
                    }
                )
                # Third lock in the global job -> receipt -> outbox order.
                self.env.cr.execute(
                    "SELECT id FROM picking_assistant_outbox "
                    "WHERE event_id = %s FOR UPDATE",
                    (receipt.event_id,),
                )
                outbox_row = self.env.cr.fetchone()
                if outbox_row:
                    outbox = outboxes.browse(outbox_row[0])
                    outbox.invalidate_recordset()
                    outbox.write(
                        {
                            "state": "pending",
                            "next_attempt_at": now,
                            "lease_owner": False,
                            "lease_expires_at": False,
                        }
                    )
            else:
                # Job already terminal/retry_scheduled: only release the
                # stale receipt lease, never touch generation or outbox.
                receipt.write(
                    {
                        "state": "completed"
                        if job.state in TERMINAL_STATES
                        else "retryable",
                        "processing_lease_token": False,
                        "processing_lease_expires_at": False,
                    }
                )
            recovered += 1
        self._report_cron_progress(recovered)

    @api.model
    def _cron_cleanup_ephemeral(self, limit=1000):
        """Every ten minutes: purge expired nonces, throttle rows, and stale
        sessions. Nonces are only removed after their expires_at, which is
        always >= 600 seconds past reservation (replay-window retention)."""
        now = fields.Datetime.now()
        size = max(1, int(limit))
        removed = 0
        nonces = self.env["picking.assistant.webhook.nonce"].sudo().search(
            [("expires_at", "<=", now)], limit=size
        )
        removed += len(nonces)
        nonces.unlink()
        throttles = self.env["picking.assistant.auth.throttle"].sudo().search(
            [("expires_at", "<=", now)], limit=size
        )
        removed += len(throttles)
        throttles.unlink()
        session_cutoff = now - timedelta(days=SESSION_GC_GRACE_DAYS)
        sessions = self.env["picking.assistant.session"].sudo().search(
            [
                "|",
                "&",
                ("revoked_at", "!=", False),
                ("revoked_at", "<=", session_cutoff),
                "&",
                ("revoked_at", "=", False),
                ("expires_at", "<=", session_cutoff),
            ],
            limit=size,
        )
        removed += len(sessions)
        sessions.unlink()
        self._report_cron_progress(removed)

    @api.model
    def _cron_cleanup_audit(self, limit=1000):
        """Daily: enforce audit retention in callback receipt, event receipt,
        outbox, then job order. Every record linked to a legal_hold job is
        skipped."""
        now = fields.Datetime.now()
        size = max(1, int(limit))
        cutoff_delivered = now - timedelta(days=RETENTION_DELIVERED_OUTBOX_DAYS)
        cutoff_dead = now - timedelta(days=RETENTION_DEAD_OUTBOX_DAYS)
        cutoff_event = now - timedelta(days=RETENTION_EVENT_RECEIPT_DAYS)
        cutoff_callback = now - timedelta(days=RETENTION_CALLBACK_RECEIPT_DAYS)
        cutoff_job = now - timedelta(days=RETENTION_JOB_DAYS)
        held_job_ids = self.sudo().search([("legal_hold", "=", True)]).ids
        removed = 0

        callbacks = self.env["picking.assistant.callback.receipt"].sudo().search(
            [
                ("received_at", "<=", cutoff_callback),
                ("job_record_id", "not in", held_job_ids),
            ],
            limit=size,
        )
        removed += len(callbacks)
        callbacks.unlink()

        event_receipts = self.env["picking.assistant.event.receipt"].sudo().search(
            [
                ("job_record_id.state", "in", sorted(TERMINAL_STATES)),
                ("job_record_id.completed_at", "<=", cutoff_event),
                ("job_record_id", "not in", held_job_ids),
            ],
            limit=size,
        )
        removed += len(event_receipts)
        event_receipts.unlink()

        outboxes = self.env["picking.assistant.outbox"].sudo().search(
            [
                ("job_record_id", "not in", held_job_ids),
                "|",
                "&",
                ("state", "=", "delivered"),
                ("delivered_at", "<=", cutoff_delivered),
                "&",
                ("state", "=", "dead"),
                ("write_date", "<=", cutoff_dead),
            ],
            limit=size,
        )
        removed += len(outboxes)
        outboxes.unlink()

        referenced_ids = (
            self.sudo()
            .search([("supersedes_job_record_id", "!=", False)])
            .supersedes_job_record_id.ids
        )
        jobs = self.sudo().search(
            [
                ("state", "in", sorted(TERMINAL_STATES)),
                ("completed_at", "<=", cutoff_job),
                ("legal_hold", "=", False),
                ("id", "not in", referenced_ids),
            ],
            limit=size,
        )
        removed += len(jobs)
        jobs.unlink()
        self._report_cron_progress(removed)
