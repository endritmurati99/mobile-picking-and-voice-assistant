from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError

from .common import IntegrationCase


class TestRetention(IntegrationCase):
    def test_legal_hold_blocks_job_and_audit_cleanup(self):
        job, outbox = self.env[
            "picking.assistant.integration.job"
        ]._enqueue_job_event(
            job_type="shipping_label",
            aggregate_model="res.partner",
            aggregate_res_id=self.picker.partner_id.id,
            aggregate_revision=1,
            event_id="a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
            event_name="shipment.parcel.ready.v1",
            envelope_text='{"schema_version":"v2"}',
            payload_fingerprint="a" * 64,
            correlation_id="0b2f7909-4ad9-44c1-8527-e775fe6d4bec",
        )
        old = fields.Datetime.now() - timedelta(days=100)
        job.write({"state": "failed", "completed_at": old, "legal_hold": True})
        outbox.write({"state": "dead", "write_date": old})
        self.env["picking.assistant.integration.job"]._cron_cleanup_audit(limit=100)
        self.assertTrue(job.exists())
        self.assertTrue(outbox.exists())


class TestNonceReplayAndRetention(IntegrationCase):
    """Closes the Task 4 cross-task obligation: nonce replay rejection with a
    retention window of at least 600 seconds."""

    def test_reserve_request_nonce_rejects_replay(self):
        nonces = self.env["picking.assistant.webhook.nonce"].with_user(
            self.api_user
        )
        result = nonces.api_reserve_request_nonce(
            "n8n_to_backend", "n2b-test", "123e4567-e89b-42d3-a456-426614174020"
        )
        self.assertTrue(result["reserved"])
        with self.assertRaises(ValidationError):
            nonces.api_reserve_request_nonce(
                "n8n_to_backend",
                "n2b-test",
                "123e4567-e89b-42d3-a456-426614174020",
            )
        # A different key or direction is a distinct replay scope.
        nonces.api_reserve_request_nonce(
            "n8n_to_backend", "other-key", "123e4567-e89b-42d3-a456-426614174020"
        )
        nonces.api_reserve_request_nonce(
            "backend_to_n8n", "n2b-test", "123e4567-e89b-42d3-a456-426614174020"
        )
        self.assertEqual(
            self.env["picking.assistant.webhook.nonce"].search_count([]), 3
        )

    def test_nonce_retention_is_at_least_600_seconds(self):
        nonces = self.env["picking.assistant.webhook.nonce"].with_user(
            self.api_user
        )
        nonces.api_reserve_request_nonce(
            "n8n_to_backend", "n2b-test", "123e4567-e89b-42d3-a456-426614174021"
        )
        record = self.env["picking.assistant.webhook.nonce"].search(
            [("nonce", "=", "123e4567-e89b-42d3-a456-426614174021")]
        )
        self.assertEqual(len(record), 1)
        self.assertGreaterEqual(
            (record.expires_at - record.received_at).total_seconds(), 600
        )

    def test_cleanup_ephemeral_keeps_unexpired_nonces(self):
        now = fields.Datetime.now()
        model = self.env["picking.assistant.webhook.nonce"].sudo()
        expired = model.create(
            {
                "direction": "n8n_to_backend",
                "key_id": "n2b-test",
                "nonce": "expired-nonce",
                "received_at": now - timedelta(seconds=2000),
                "expires_at": now - timedelta(seconds=1),
            }
        )
        live = model.create(
            {
                "direction": "n8n_to_backend",
                "key_id": "n2b-test",
                "nonce": "live-nonce",
                "received_at": now,
                "expires_at": now + timedelta(seconds=900),
            }
        )
        self.env["picking.assistant.integration.job"]._cron_cleanup_ephemeral(
            limit=100
        )
        self.assertFalse(expired.exists())
        self.assertTrue(live.exists())


class TestWatchdogAndAuditCleanup(IntegrationCase):
    def _accept(self, job, outbox, ingress_nonce, acceptance_nonce):
        return self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        ).api_accept_event(
            outbox.event_id,
            job.job_id,
            "a" * 64,
            "b2n-test",
            ingress_nonce,
            job.delivery_generation,
            "n2b-test",
            acceptance_nonce,
        )

    def _enqueue(self, suffix="5"):
        return self.env["picking.assistant.integration.job"]._enqueue_job_event(
            job_type="quality_assessment",
            aggregate_model="res.partner",
            aggregate_res_id=self.picker.partner_id.id,
            aggregate_revision=1,
            event_id=f"a4ff5ca2-4546-4ea4-8e6c-b75bc003ca3{suffix}",
            event_name="quality.assessment.requested.v1",
            envelope_text='{"schema_version":"v2"}',
            payload_fingerprint="a" * 64,
            correlation_id=f"0b2f7909-4ad9-44c1-8527-e775fe6d4be{suffix}",
        )

    def test_watchdog_recovers_expired_processing_lease(self):
        job, outbox = self._enqueue("5")
        self._accept(
            job,
            outbox,
            "123e4567-e89b-42d3-a456-426614174030",
            "123e4567-e89b-42d3-a456-426614174031",
        )
        receipt = self.env["picking.assistant.event.receipt"].search(
            [("event_id", "=", outbox.event_id)]
        )
        self.assertEqual(receipt.state, "processing")
        receipt.write(
            {
                "processing_lease_expires_at": fields.Datetime.now()
                - timedelta(seconds=1)
            }
        )
        self.env["picking.assistant.integration.job"]._cron_recover_stalled_jobs(
            limit=10
        )
        self.assertEqual(receipt.state, "retryable")
        self.assertFalse(receipt.processing_lease_token)
        self.assertEqual(job.state, "retry_scheduled")
        self.assertEqual(job.delivery_generation, 2)
        self.assertFalse(job.processing_lease_token)
        self.assertEqual(outbox.state, "pending")
        self.assertEqual(outbox.envelope_text, '{"schema_version":"v2"}')

    def test_one_poisoned_candidate_does_not_deny_recovery_to_the_others(self):
        """Fix round 2, finding 1: denial of recovery.

        An orphaned receipt (its outbox row purged by retention) makes
        `_recover_expired_lease` raise. If that raise escapes the batch, the
        WHOLE batch dies -- and the poison row is deterministically FIRST,
        because the candidate scan orders by `processing_lease_expires_at` and
        a receipt is orphaned precisely because it is old enough for retention
        to have removed its outbox row. One such row would starve every
        candidate, this minute and every minute after, and the cron is now the
        only exit from an expired lease.

        Per-recovery atomicity was what the previous round asked for, not
        per-batch: the savepoint gives back all three writes of the poisoned
        candidate and nothing else.

        Task 6 update: the poisoned candidate no longer sits silently in its
        old state. `_recover_expired_lease` now fails closed to
        `review_required` for exactly this case (missing outbox row), so the
        savepoint keeps THAT write instead of rolling everything back -- the
        candidate is still counted `skipped` (its recovery still refused
        itself), but it is no longer invisible to an operator.
        """
        orphan_job, orphan_outbox = self._enqueue("9")
        self._accept(
            orphan_job,
            orphan_outbox,
            "123e4567-e89b-42d3-a456-426614174070",
            "123e4567-e89b-42d3-a456-426614174071",
        )
        orphan_receipt = self.env["picking.assistant.event.receipt"].search(
            [("event_id", "=", orphan_outbox.event_id)]
        )
        healthy_job, healthy_outbox = self._enqueue("a")
        self._accept(
            healthy_job,
            healthy_outbox,
            "123e4567-e89b-42d3-a456-426614174072",
            "123e4567-e89b-42d3-a456-426614174073",
        )
        healthy_receipt = self.env["picking.assistant.event.receipt"].search(
            [("event_id", "=", healthy_outbox.event_id)]
        )
        now = fields.Datetime.now()
        # The orphan sorts to the head of the batch, exactly as it would in
        # production -- it is old enough that retention took its outbox row.
        orphan_receipt.write(
            {"processing_lease_expires_at": now - timedelta(days=40)}
        )
        healthy_receipt.write(
            {"processing_lease_expires_at": now - timedelta(seconds=1)}
        )
        orphan_outbox.unlink()

        result = self.env["picking.assistant.integration.job"].with_user(
            self.api_user
        ).api_recover_stalled_jobs(10)

        self.env.invalidate_all()
        self.assertEqual(result, {"recovered": 1, "skipped": 1})
        # The healthy candidate behind the poison row still recovers fully.
        self.assertEqual(healthy_job.state, "retry_scheduled")
        self.assertEqual(healthy_job.delivery_generation, 2)
        self.assertEqual(healthy_receipt.state, "retryable")
        self.assertEqual(healthy_outbox.state, "pending")
        # The poisoned candidate fails closed to review_required (Task 6)
        # instead of being rolled back to its old, invisible state. Its
        # generation is untouched -- no delivery was promised.
        self.assertEqual(orphan_job.state, "review_required")
        self.assertEqual(orphan_job.delivery_generation, 1)
        self.assertEqual(orphan_receipt.state, "completed")
        self.assertFalse(orphan_receipt.processing_lease_token)

    def test_retention_keeps_the_outbox_of_a_non_terminal_job(self):
        """Deleting the only deliverable of a live job strands it forever.
        Regression cover for finding #11."""
        job, outbox = self._enqueue("b")
        old = fields.Datetime.now() - timedelta(days=90)
        outbox.write({"state": "delivered", "delivered_at": old})
        self.assertEqual(job.state, "queued")

        self.env["picking.assistant.integration.job"]._cron_cleanup_audit(
            limit=100
        )

        self.assertTrue(
            outbox.exists(), "a non-terminal job must keep its outbox row"
        )

    def test_retention_still_deletes_the_outbox_of_a_terminal_job(self):
        job, outbox = self._enqueue("c")
        old = fields.Datetime.now() - timedelta(days=90)
        job.write({"state": "failed", "completed_at": old})
        outbox.write({"state": "delivered", "delivered_at": old})

        self.env["picking.assistant.integration.job"]._cron_cleanup_audit(
            limit=100
        )

        self.assertFalse(outbox.exists())

    def test_watchdog_fails_closed_to_review_required_when_outbox_is_missing(
        self,
    ):
        """Task 6, step 4: even with retention no longer able to delete a
        non-terminal job's outbox, the lease-recovery batch must still fail
        closed if the row is somehow gone -- never `retry_scheduled` with
        nothing left to deliver."""
        job, outbox = self._enqueue("d")
        self._accept(
            job,
            outbox,
            "123e4567-e89b-42d3-a456-426614174082",
            "123e4567-e89b-42d3-a456-426614174083",
        )
        receipt = self.env["picking.assistant.event.receipt"].search(
            [("event_id", "=", outbox.event_id)]
        )
        self.assertEqual(job.state, "queued")
        receipt.write(
            {
                "processing_lease_expires_at": fields.Datetime.now()
                - timedelta(seconds=1)
            }
        )
        outbox.unlink()

        self.env["picking.assistant.integration.job"]._cron_recover_stalled_jobs(
            limit=10
        )

        job.invalidate_recordset()
        receipt.invalidate_recordset()
        self.assertNotEqual(
            job.state,
            "retry_scheduled",
            "a job with nothing to deliver must not be scheduled for retry",
        )
        self.assertEqual(job.state, "review_required")
        self.assertEqual(receipt.state, "completed")
        self.assertFalse(receipt.processing_lease_token)

    def test_recovery_rejects_states_it_may_not_recover_from(self):
        """Renamed with `_watchdog_retry_scheduled`, which no longer exists:
        the watchdog has no recovery edge of its own any more, it calls the
        one recovery function. The guarded state set is unchanged."""
        job, outbox = self._enqueue("7")
        receipt = self.env["picking.assistant.event.receipt"].create(
            {
                "event_id": outbox.event_id,
                "job_record_id": job.id,
                "payload_fingerprint": "a" * 64,
                "delivery_generation": job.delivery_generation,
                "state": "processing",
            }
        )
        jobs = self.env["picking.assistant.integration.job"]
        for unlisted in ("succeeded", "review_required", "failed",
                         "retry_scheduled"):
            job.write({"state": unlisted})
            with self.assertRaises(ValidationError):
                jobs._recover_expired_lease(job, receipt, fields.Datetime.now())

    def test_a_bare_transition_cannot_produce_the_recovery_edge(self):
        """Decision §3.3: `queued -> retry_scheduled` exists ONLY as a side
        effect of recovery, never as a bare state change."""
        job, _outbox = self._enqueue("8")
        self.assertEqual(job.state, "queued")
        with self.assertRaises(ValidationError):
            job._transition("retry_scheduled", sequence=1)

    def test_audit_cleanup_deletes_old_unheld_records(self):
        job, outbox = self._enqueue("6")
        old = fields.Datetime.now() - timedelta(days=100)
        job.write({"state": "failed", "completed_at": old, "legal_hold": False})
        outbox.write({"state": "delivered", "delivered_at": old})
        self.env["picking.assistant.integration.job"]._cron_cleanup_audit(
            limit=100
        )
        self.assertFalse(outbox.exists())
        self.assertFalse(job.exists())
