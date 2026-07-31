from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError

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

    def test_lease_reads_locked_row_not_stale_orm_cache(self):
        _job, outbox = self._enqueue("1")
        # Prime the ORM cache, then change the row behind its back (stands in
        # for another transaction's committed write).
        self.assertEqual(outbox.attempt_count, 0)
        self.env.cr.execute(
            "UPDATE picking_assistant_outbox SET attempt_count = 3 "
            "WHERE id = %s",
            (outbox.id,),
        )
        model = self.env["picking.assistant.outbox"].with_user(self.api_user)
        leased = model.api_lease_due("worker-a", limit=1, lease_seconds=60)
        # A lease computed from the stale cache would report 1 and overwrite
        # the newer attempt_count; the locked row's value must win.
        self.assertEqual(leased[0]["attempt_count"], 4)

    def test_expired_lease_holder_cannot_ack_or_nack(self):
        self._enqueue("1")
        model = self.env["picking.assistant.outbox"].with_user(self.api_user)
        leased = model.api_lease_due("worker-a", limit=1, lease_seconds=60)
        event_id = leased[0]["event_id"]
        outbox = self.env["picking.assistant.outbox"].search(
            [("event_id", "=", event_id)]
        )
        outbox.write(
            {"lease_expires_at": fields.Datetime.now() - timedelta(seconds=1)}
        )
        with self.assertRaises(ValidationError):
            model.api_ack_delivery(event_id, "worker-a", event_id)
        with self.assertRaises(ValidationError):
            model.api_nack_delivery(event_id, "worker-a", "timeout", "too late")
        self.assertEqual(outbox.state, "leased")
        self.assertFalse(outbox.delivered_at)

    def test_stale_owner_cannot_overwrite_newer_lease(self):
        self._enqueue("1")
        model = self.env["picking.assistant.outbox"].with_user(self.api_user)
        first = model.api_lease_due("worker-a", limit=1, lease_seconds=60)
        event_id = first[0]["event_id"]
        outbox = self.env["picking.assistant.outbox"].search(
            [("event_id", "=", event_id)]
        )
        outbox.write(
            {"lease_expires_at": fields.Datetime.now() - timedelta(seconds=1)}
        )
        second = model.api_lease_due("worker-b", limit=1, lease_seconds=60)
        self.assertEqual(second[0]["event_id"], event_id)
        with self.assertRaises(ValidationError):
            model.api_ack_delivery(event_id, "worker-a", event_id)
        with self.assertRaises(ValidationError):
            model.api_nack_delivery(event_id, "worker-a", "timeout", "stale owner")
        self.assertEqual(outbox.lease_owner, "worker-b")
        self.assertEqual(outbox.state, "leased")

    def test_requeue_dead_event_clears_lease_and_resets_state(self):
        _job, outbox = self._enqueue("1")
        outbox.write(
            {
                "state": "dead",
                "attempt_count": 10,
                "lease_owner": "worker-a",
                "lease_expires_at": fields.Datetime.now() + timedelta(seconds=60),
            }
        )
        model = self.env["picking.assistant.outbox"].with_user(self.api_user)
        result = model.api_requeue_dead(
            outbox.event_id, self.supervisor.id, "manual retry"
        )
        self.assertEqual(result, {"state": "pending", "event_id": outbox.event_id})
        outbox.invalidate_recordset()
        self.assertEqual(outbox.state, "pending")
        self.assertEqual(outbox.attempt_count, 0)
        self.assertFalse(outbox.lease_owner)
        self.assertFalse(outbox.lease_expires_at)
        self.assertEqual(outbox.last_error_code, "manual_requeue")

    def test_requeue_refuses_a_row_that_is_not_dead(self):
        _job, outbox = self._enqueue("1")
        self.assertEqual(outbox.state, "pending")
        model = self.env["picking.assistant.outbox"].with_user(self.api_user)
        with self.assertRaises(ValidationError):
            model.api_requeue_dead(outbox.event_id, self.supervisor.id, "reason")

    def test_requeue_refuses_a_supervisor_without_the_group(self):
        _job, outbox = self._enqueue("1")
        outbox.write({"state": "dead"})
        model = self.env["picking.assistant.outbox"].with_user(self.api_user)
        with self.assertRaises(AccessError):
            model.api_requeue_dead(outbox.event_id, self.picker.id, "reason")
