"""An expired lease must be worthless everywhere, not only at acceptance.

Regression cover for whole-branch review finding #5.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .concurrency_common import CommittedConcurrencyCase


@tagged("post_install", "-at_install")
class TestLeaseExpiry(CommittedConcurrencyCase):
    def _job_with_expired_lease(self):
        """Commit a job whose receipt holds a lease that expired one second ago."""
        env = self.env
        job = self.track(
            env["picking.assistant.integration.job"].create(self._job_values())
        )
        receipt = self.track(
            env["picking.assistant.event.receipt"].create(
                self._receipt_values(job, state="processing")
            )
        )
        self.track(
            env["picking.assistant.outbox"].create(
                self._outbox_values(job, receipt)
            )
        )
        now = fields.Datetime.now()
        receipt.write(
            {
                "processing_lease_token": "stale-token",
                "processing_lease_expires_at": now - timedelta(seconds=1),
            }
        )
        job.write(
            {
                "processing_lease_token": "stale-token",
                "processing_lease_expires_at": now - timedelta(seconds=1),
            }
        )
        env.cr.commit()
        return job, receipt

    def test_callback_with_an_expired_lease_is_refused(self):
        job, receipt = self._job_with_expired_lease()
        callback = self._callback_payload(job, receipt, token="stale-token")

        with self.assertRaises(ValidationError) as caught:
            self._apply_callback(callback)

        self.assertIn("lease", str(caught.exception).lower())

    def test_callback_with_a_live_lease_still_succeeds(self):
        job, receipt = self._job_with_expired_lease()
        receipt.write(
            {"processing_lease_expires_at": fields.Datetime.now() + timedelta(minutes=5)}
        )
        self.env.cr.commit()
        callback = self._callback_payload(job, receipt, token="stale-token")

        result = self._apply_callback(callback)

        self.assertTrue(result["callback_id"])
        self.assertEqual(result["status"], "applied")

    def test_the_lease_primitive_itself_refuses_an_expired_lease(self):
        """The lease check must be one primitive, not a per-call-site opinion.

        Renamed in fix round 1: the old name promised media and artifact cover
        that this test never provided. That cover now lives in
        `test_resources.py` and goes through the real RPC entry points
        (`test_expired_processing_lease_cannot_read_media`,
        `test_expired_processing_lease_cannot_attach`,
        `test_artifact_binds_to_its_own_event_not_to_any_live_lease`).
        """
        job, receipt = self._job_with_expired_lease()
        with self.assertRaises(ValidationError):
            self.env["picking.assistant.event.receipt"]._assert_active_lease(
                job,
                receipt,
                generation=job.delivery_generation,
                supplied_token="stale-token",
                now=fields.Datetime.now(),
            )

    def test_the_error_text_is_no_oracle_for_a_guessed_token(self):
        """Fix round 1, finding 1.

        A wrong token and a correct-but-late token must be indistinguishable
        from the outside. Previously the token comparison ran first and expiry
        had its own message, so `"Processing lease has expired."` was reachable
        ONLY on a correct guess -- a positive signal on a correct token.
        """
        job, receipt = self._job_with_expired_lease()

        right_token = self._callback_payload(job, receipt, token="stale-token")
        wrong_token = self._callback_payload(job, receipt, token="not-the-token")

        with self.assertRaises(ValidationError) as late:
            self._apply_callback(right_token)
        with self.assertRaises(ValidationError) as guess:
            self._apply_callback(wrong_token)

        self.assertEqual(str(late.exception), str(guess.exception))

    # ------------------------------------------------------------------
    # Finding #5, second half: an expired lease must not be survivable by
    # handing out a new token under the SAME delivery generation.
    # ------------------------------------------------------------------

    def test_acceptance_does_not_reissue_a_token_in_the_same_generation(self):
        """The hole: acceptance saw "no live lease" and issued a fresh token.

        The old worker's token stopped matching, but the generation never
        moved -- so every consumer bound to "generation plus SOME live lease"
        (the resource routes are exactly that, see `_require_current_generation`)
        was fooled into serving the new worker's window to the old one.
        """
        job, receipt = self._job_with_expired_lease()
        generation_before = job.delivery_generation

        with self.assertRaises(ValidationError) as caught:
            self.env["picking.assistant.event.receipt"].with_user(
                self.api_user_id
            ).api_accept_event(*self._acceptance_args(job, receipt))

        self.assertIn("processing_lease_expired", str(caught.exception))
        job.invalidate_recordset()
        receipt.invalidate_recordset()
        self.assertEqual(job.delivery_generation, generation_before)
        # Refusing must not quietly mint a token either.
        self.assertEqual(receipt.processing_lease_token, "stale-token")

    def test_recovery_increments_the_generation_and_clears_the_lease(self):
        job, receipt = self._job_with_expired_lease()
        generation_before = job.delivery_generation

        self.env["picking.assistant.integration.job"]._recover_expired_lease(
            job, receipt, fields.Datetime.now()
        )

        job.invalidate_recordset()
        receipt.invalidate_recordset()
        self.assertEqual(job.delivery_generation, generation_before + 1)
        self.assertFalse(receipt.processing_lease_token)
        self.assertFalse(receipt.processing_lease_expires_at)
        self.assertFalse(job.processing_lease_token)
        self.assertEqual(receipt.state, "retryable")
        self.assertEqual(job.state, "retry_scheduled")
        outbox = self.env["picking.assistant.outbox"].search(
            [("job_record_id", "=", job.id)], limit=1
        )
        self.assertEqual(outbox.state, "pending")
        self.assertEqual(outbox.envelope_text, '{"schema_version":"v2"}')

    def test_the_old_worker_is_useless_after_recovery(self):
        job, receipt = self._job_with_expired_lease()
        self.env["picking.assistant.integration.job"]._recover_expired_lease(
            job, receipt, fields.Datetime.now()
        )
        self.env.cr.commit()

        callback = self._callback_payload(job, receipt, token="stale-token")
        with self.assertRaises(ValidationError):
            self._apply_callback(callback)

    def test_recovery_refuses_a_lease_that_is_still_live(self):
        """Fix round 1, finding 2.

        Recovery invalidates a worker by moving the generation. Doing that to a
        LIVE lease silently kills a healthy in-flight worker. "Only one caller
        today" is not a guard, so the function asserts the precondition itself
        -- with the SAME predicate the acceptance path uses, so there stays
        exactly one definition of "expired".
        """
        job, receipt = self._job_with_expired_lease()
        receipt.write(
            {
                "processing_lease_expires_at": fields.Datetime.now()
                + timedelta(minutes=5)
            }
        )
        generation_before = job.delivery_generation

        with self.assertRaises(ValidationError):
            self.env["picking.assistant.integration.job"]._recover_expired_lease(
                job, receipt, fields.Datetime.now()
            )

        job.invalidate_recordset()
        receipt.invalidate_recordset()
        self.assertEqual(job.delivery_generation, generation_before)
        self.assertEqual(job.state, "running")
        self.assertEqual(receipt.processing_lease_token, "stale-token")

    def test_recovery_refuses_when_the_outbox_event_is_gone(self):
        """Fix round 1, finding 1.

        Without its outbox row the event can never be redelivered. Applying
        three of the four effects and reporting success parks the job forever
        AND counts it as recovered. The transaction must roll back instead --
        the receipt can outlive its outbox row, because `_cron_cleanup_audit`
        purges delivered/dead outbox rows at 30/90 days while receipts live to
        90 (the retention half of that is Task 6, not this function).
        """
        job, receipt = self._job_with_expired_lease()
        self.env["picking.assistant.outbox"].search(
            [("event_id", "=", receipt.event_id)]
        ).unlink()
        self.env.cr.commit()

        with self.assertRaises(ValidationError):
            self.env["picking.assistant.integration.job"]._recover_expired_lease(
                job, receipt, fields.Datetime.now()
            )

        # Raising is only worth anything if the partial writes go with it.
        self.env.cr.rollback()
        self.env.invalidate_all()
        self.assertEqual(job.delivery_generation, 1)
        self.assertEqual(job.state, "running")
        self.assertEqual(receipt.state, "processing")
        self.assertEqual(receipt.processing_lease_token, "stale-token")

    def test_a_bare_transition_can_no_longer_reach_retry_scheduled(self):
        """Decision §3.3: recovery is the ONLY producer of that state from
        `queued`. A bare `_transition()` would leave the generation, the lease
        and the outbox row untouched -- i.e. exactly the state an old worker
        can keep working in."""
        job, _receipt = self._job_with_expired_lease()
        job.write({"state": "queued"})

        with self.assertRaises(ValidationError):
            job._transition("retry_scheduled", sequence=1)
