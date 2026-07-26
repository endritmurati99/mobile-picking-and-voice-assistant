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
