from odoo.exceptions import ValidationError

from .common import IntegrationCase


class TestReceiptsAndCallbacks(IntegrationCase):
    def setUp(self):
        super().setUp()
        self.job, self.outbox = self.env[
            "picking.assistant.integration.job"
        ]._enqueue_job_event(
            job_type="quality_assessment",
            aggregate_model="res.partner",
            aggregate_res_id=self.picker.partner_id.id,
            aggregate_revision=1,
            event_id="a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
            event_name="quality.assessment.requested.v1",
            envelope_text='{"schema_version":"v2"}',
            payload_fingerprint="a" * 64,
            correlation_id="0b2f7909-4ad9-44c1-8527-e775fe6d4bec",
            job_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
        )

    def test_acceptance_returns_one_processing_lease_then_deduplicates(self):
        receipts = self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        )
        first = receipts.api_accept_event(
            self.outbox.event_id,
            self.job.job_id,
            "a" * 64,
            "b2n-test",
            "123e4567-e89b-42d3-a456-426614174000",
            1,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174001",
        )
        second = receipts.api_accept_event(
            self.outbox.event_id,
            self.job.job_id,
            "a" * 64,
            "b2n-test",
            "123e4567-e89b-42d3-a456-426614174003",
            1,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174002",
        )
        self.assertTrue(first["process"])
        self.assertTrue(first["processing_lease_token"])
        self.assertFalse(second["process"])
        self.assertEqual(
            self.env["picking.assistant.event.receipt"].search_count([]), 1
        )

    def test_reused_ingress_nonce_is_rejected_even_for_same_event(self):
        receipts = self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        )
        args = [
            self.outbox.event_id,
            self.job.job_id,
            "a" * 64,
            "b2n-test",
            "123e4567-e89b-42d3-a456-426614174000",
            1,
            "n2b-test",
        ]
        receipts.api_accept_event(
            *args, "123e4567-e89b-42d3-a456-426614174001"
        )
        with self.assertRaises(ValidationError):
            receipts.api_accept_event(
                *args, "123e4567-e89b-42d3-a456-426614174002"
            )
        self.assertEqual(receipts.search_count([]), 1)

    def test_wrong_job_id_causes_no_nonce_or_receipt_write(self):
        receipts = self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        )
        with self.assertRaises(ValidationError):
            receipts.api_accept_event(
                self.outbox.event_id,
                "00000000-0000-4000-8000-000000000099",
                "a" * 64,
                "b2n-test",
                "123e4567-e89b-42d3-a456-426614174010",
                1,
                "n2b-test",
                "123e4567-e89b-42d3-a456-426614174011",
            )
        self.assertFalse(receipts.search_count([]))
        self.assertFalse(
            self.env["picking.assistant.webhook.nonce"].search_count([])
        )

    def test_callback_replay_and_stale_sequence_have_no_second_effect(self):
        receipts = self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        )
        accepted = receipts.api_accept_event(
            self.outbox.event_id,
            self.job.job_id,
            "a" * 64,
            "b2n-test",
            "123e4567-e89b-42d3-a456-426614174000",
            1,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174001",
        )
        callback = {
            "callback_id": "cbdc037f-8458-4be0-938a-4bc8242116af",
            "source_event_id": self.outbox.event_id,
            "job_id": self.job.job_id,
            "sequence": 1,
            "attempt": 1,
            "delivery_generation": 1,
            "processing_lease_token": accepted["processing_lease_token"],
            "status": "running",
            "result": {},
            "error": False,
            "metrics": {},
        }
        model = self.env["picking.assistant.callback.receipt"].with_user(
            self.api_user
        )
        first = model.api_apply_callback(
            callback,
            "b" * 64,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174003",
        )
        replay = model.api_apply_callback(
            callback,
            "b" * 64,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174004",
        )
        self.assertEqual(first["status"], "applied")
        self.assertEqual(replay, first)
        self.assertEqual(self.job.state, "running")
        self.assertEqual(self.job.sequence, 1)
