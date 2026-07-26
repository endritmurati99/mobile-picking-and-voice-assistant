from datetime import timedelta

from odoo import fields

from .common import IntegrationCase


class TestJobOutboxTransaction(IntegrationCase):
    def _enqueue(self, suffix="1", envelope='{"schema_version":"v2","text":"Gruss"}'):
        return self.env["picking.assistant.integration.job"]._enqueue_job_event(
            job_type="quality_assessment",
            aggregate_model="res.partner",
            aggregate_res_id=self.picker.partner_id.id,
            aggregate_revision=1,
            event_id=f"a4ff5ca2-4546-4ea4-8e6c-b75bc003ca3{suffix}",
            event_name="quality.assessment.requested.v1",
            envelope_text=envelope,
            payload_fingerprint="a" * 64,
            correlation_id=f"0b2f7909-4ad9-44c1-8527-e775fe6d4be{suffix}",
        )

    def test_business_write_job_and_outbox_rollback_together(self):
        marker = "PWR atomic rollback marker"
        with self.assertRaisesRegex(RuntimeError, "force rollback"):
            with self.env.cr.savepoint():
                self.env["res.partner"].create({"name": marker})
                self._enqueue()
                raise RuntimeError("force rollback")
        self.env.invalidate_all()
        self.assertFalse(self.env["res.partner"].search([("name", "=", marker)]))
        self.assertFalse(self.env["picking.assistant.integration.job"].search([]))
        self.assertFalse(self.env["picking.assistant.outbox"].search([]))

    def test_success_keeps_exact_envelope_text(self):
        envelope = '{"schema_version":"v2","message":"Gruess dich"}'
        job, outbox = self._enqueue(envelope=envelope)
        self.assertEqual(job.state, "queued")
        self.assertEqual(outbox.envelope_text, envelope)
        self.assertEqual(outbox.event_id, "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca31")

    def test_two_leases_are_disjoint_and_nack_uses_frozen_backoff(self):
        self._enqueue("1")
        self._enqueue("2")
        model = self.env["picking.assistant.outbox"].with_user(self.api_user)
        first = model.api_lease_due("worker-a", limit=1, lease_seconds=60)
        second = model.api_lease_due("worker-b", limit=1, lease_seconds=60)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first[0]["event_id"], second[0]["event_id"])
        failed = model.api_nack_delivery(
            first[0]["event_id"], "worker-a", "timeout", "n8n timeout"
        )
        self.assertEqual(failed["attempt_count"], 1)
        self.assertEqual(failed["retry_after_seconds"], 10)
