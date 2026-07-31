import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, ValidationError

from ..models.receipts import PickingAssistantEventReceipt
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
        """Since Task 3 the nonce is reserved FIRST (LOCK_ORDER), so this is
        no longer "the method never got that far" -- it is "the failure rolls
        the reservation back with everything else". Odoo's `assertRaises`
        wraps the block in a savepoint, which is the same transaction boundary
        the RPC dispatcher applies to a ValidationError, so the assertion below
        still measures what production does."""
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

    def test_acceptance_revalidates_outbox_under_lock(self):
        """readonly=True does not stop privileged ORM writes, so the
        acceptance decision must re-check the outbox from the row under lock.
        Simulate a concurrent privileged fingerprint change landing between the
        early lock-free check and the outbox lock.

        The tamper used to hang off `_reserve`, because the nonce reservation
        sat in that window. Task 3 moved the reservation to the FRONT of the
        method (LOCK_ORDER starts at "nonce"), so a tamper there now lands
        before the early check and would be caught by it -- the test would
        still go green while covering nothing. `_lock_existing` is what sits in
        the window now, so that is what carries the tamper."""
        receipts = self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        )
        real_lock_existing = PickingAssistantEventReceipt._lock_existing
        outbox_id = self.outbox.id

        def lock_then_tamper(model_self, event_id):
            record = real_lock_existing(model_self, event_id)
            model_self.env.cr.execute(
                "UPDATE picking_assistant_outbox "
                "SET payload_fingerprint = %s WHERE id = %s",
                ("f" * 64, outbox_id),
            )
            return record

        with patch.object(
            PickingAssistantEventReceipt, "_lock_existing", lock_then_tamper
        ):
            with self.assertRaisesRegex(
                ValidationError, "Outbox event changed during acceptance"
            ):
                receipts.api_accept_event(
                    self.outbox.event_id,
                    self.job.job_id,
                    "a" * 64,
                    "b2n-test",
                    "123e4567-e89b-42d3-a456-426614174050",
                    1,
                    "n2b-test",
                    "123e4567-e89b-42d3-a456-426614174051",
                )
        stored = self.env["picking.assistant.event.receipt"].search(
            [("event_id", "=", self.outbox.event_id)]
        )
        self.assertFalse(stored.processing_lease_token)

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

    def test_callback_retry_fails_closed_when_outbox_is_missing(self):
        """Task 6, sibling site to finding #11 found by the required lock-site
        audit: this branch used to move the job to `retry_scheduled` and only
        conditionally touch the outbox (`if outbox_row: ...` with no else),
        so a missing row silently stranded the job with nothing left to
        deliver. Same failure mode as the cron watchdog, different call site
        -- fail closed here too."""
        accepted = self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        ).api_accept_event(
            self.outbox.event_id,
            self.job.job_id,
            "a" * 64,
            "b2n-test",
            "123e4567-e89b-42d3-a456-426614174090",
            1,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174091",
        )
        receipt = self.env["picking.assistant.event.receipt"].search(
            [("event_id", "=", self.outbox.event_id)]
        )
        self.outbox.unlink()
        callback = {
            "callback_id": "3d6a5e2b-7c34-4b9e-9a9f-2b7d0e8a1234",
            "source_event_id": receipt.event_id,
            "job_id": self.job.job_id,
            "sequence": 1,
            "attempt": 1,
            "delivery_generation": 1,
            "processing_lease_token": accepted["processing_lease_token"],
            "status": "retry_scheduled",
            "result": {},
            "error": {"code": "n8n_side_failure"},
            "metrics": {},
        }
        model = self.env["picking.assistant.callback.receipt"].with_user(
            self.api_user
        )

        # This fail-closed path deliberately logs at WARNING; assert it
        # rather than let it pass as unexplained noise against the suite's
        # "0 unexpected warnings" invariant.
        with self.assertLogs(
            "odoo.addons.picking_assistant_integration.models.receipts",
            level="WARNING",
        ) as cm:
            result = model.api_apply_callback(
                callback,
                "b" * 64,
                "n2b-test",
                "123e4567-e89b-42d3-a456-426614174092",
            )
        self.assertTrue(
            any("no outbox row" in message for message in cm.output)
        )

        self.assertEqual(result["status"], "applied")
        self.assertNotEqual(
            self.job.state,
            "retry_scheduled",
            "a job with nothing to deliver must not be scheduled for retry",
        )
        self.assertEqual(self.job.state, "review_required")
        self.assertEqual(receipt.state, "completed")
        # The n8n-supplied failure detail must survive the fail-closed
        # transition alongside the reason review is needed at all -- merged,
        # not replaced.
        self.job.invalidate_recordset()
        error = json.loads(self.job.error_json)
        self.assertEqual(error["code"], "n8n_side_failure")
        self.assertEqual(error["reason"], "missing_outbox_row")
        self.assertFalse(receipt.processing_lease_token)

    def _accept_and_expire_lease(self):
        self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        ).api_accept_event(
            self.outbox.event_id,
            self.job.job_id,
            "a" * 64,
            "b2n-test",
            "123e4567-e89b-42d3-a456-426614174060",
            1,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174061",
        )
        receipt = self.env["picking.assistant.event.receipt"].search(
            [("event_id", "=", self.outbox.event_id)]
        )
        receipt.write(
            {
                "processing_lease_expires_at": fields.Datetime.now()
                - timedelta(seconds=1)
            }
        )
        return receipt

    def test_api_recover_stalled_jobs_requires_api_service_group(self):
        jobs = self.env["picking.assistant.integration.job"].with_user(
            self.picker
        )
        with self.assertRaises(AccessError):
            jobs.api_recover_stalled_jobs(10)

    def test_api_recover_stalled_jobs_returns_counts_only_and_recovers(self):
        receipt = self._accept_and_expire_lease()
        result = self.env["picking.assistant.integration.job"].with_user(
            self.api_user
        ).api_recover_stalled_jobs(10)
        # Counts only: the guarded watchdog batch must never expose lease
        # tokens or any other row data over RPC.
        self.assertEqual(result, {"recovered": 1, "skipped": 0})
        self.assertEqual(receipt.state, "retryable")
        self.assertFalse(receipt.processing_lease_token)
        self.assertEqual(self.job.state, "retry_scheduled")
        self.assertEqual(self.job.delivery_generation, 2)
        self.assertEqual(self.outbox.state, "pending")
        self.assertEqual(self.outbox.envelope_text, '{"schema_version":"v2"}')

    def test_retry_callback_after_a_recovered_retry_is_not_a_dead_end(self):
        """A retry OF a retry -- the branch none of the other 123 tests reach.

        `_recover_expired_lease` leaves the job in `retry_scheduled`; the
        outbox redelivers; `api_accept_event` hands out a fresh lease and moves
        the RECEIPT to `processing` but never touches `job.state`. If the
        worker then reports `retry_scheduled` again with no intervening
        `running` callback, the callback branch must make the same
        `retry_scheduled -> running` hop its two sibling branches already make
        (`:685`, `:706`). Without it `_transition` asks the frozen table for a
        `retry_scheduled -> retry_scheduled` edge that does not exist, and the
        job is a permanent 409 -- redelivered forever, rejected every time.
        """
        self._accept_and_expire_lease()
        self.env["picking.assistant.integration.job"].with_user(
            self.api_user
        ).api_recover_stalled_jobs(10)
        self.job.invalidate_recordset()
        self.assertEqual(self.job.state, "retry_scheduled")
        self.assertEqual(self.job.delivery_generation, 2)

        redelivered = self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        ).api_accept_event(
            self.outbox.event_id,
            self.job.job_id,
            "a" * 64,
            "b2n-test",
            "123e4567-e89b-42d3-a456-426614174070",
            2,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174071",
        )
        self.assertTrue(redelivered["process"])
        self.job.invalidate_recordset()
        # The precondition, asserted rather than assumed: acceptance issues a
        # lease without moving the job out of `retry_scheduled`.
        self.assertEqual(self.job.state, "retry_scheduled")

        callback = {
            "callback_id": "8f2b1c44-0f3a-4a55-9c21-6d1e0b4a7799",
            "source_event_id": self.outbox.event_id,
            "job_id": self.job.job_id,
            "sequence": 1,
            "attempt": 2,
            "delivery_generation": 2,
            "processing_lease_token": redelivered["processing_lease_token"],
            "status": "retry_scheduled",
            "result": {},
            "error": {"code": "n8n_side_failure"},
            "metrics": {},
        }
        result = self.env["picking.assistant.callback.receipt"].with_user(
            self.api_user
        ).api_apply_callback(
            callback,
            "b" * 64,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174072",
        )

        self.assertEqual(result["status"], "applied")
        self.job.invalidate_recordset()
        self.outbox.invalidate_recordset()
        self.assertEqual(self.job.state, "retry_scheduled")
        self.assertEqual(self.job.delivery_generation, 3)
        self.assertFalse(self.job.processing_lease_token)
        self.assertEqual(self.outbox.state, "pending")

    def test_api_recover_stalled_jobs_with_nothing_due_recovers_zero(self):
        result = self.env["picking.assistant.integration.job"].with_user(
            self.api_user
        ).api_recover_stalled_jobs(10)
        self.assertEqual(result, {"recovered": 0, "skipped": 0})
