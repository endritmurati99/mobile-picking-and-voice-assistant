"""Two transactions must never be able to form a lock cycle.

Regression cover for whole-branch review finding #6. This needs two real
connections: on one cursor the two calls are sequential statements in one
transaction and can never contend.

Why every test here loops. A lock cycle is an INTERLEAVING, not a state: the
two workers have to reach their respective first lock inside each other's
window. Starting them on a barrier makes that likely, not certain, so one pass
proves nothing when it comes back clean. `ATTEMPTS` passes with a fresh job and
a fresh nonce each time turn "we did not see it" into evidence. With the bug in
place the very first attempts already deadlock (see task-3-report.md).
"""

import psycopg2

from odoo.tests.common import tagged

from .concurrency_common import CommittedConcurrencyCase

# Empirically the buggy code deadlocked within the first two attempts; ten
# leaves a wide margin without making the suite crawl.
ATTEMPTS = 10


def _deadlocks(results):
    return [
        outcome
        for outcome in results
        if isinstance(outcome, psycopg2.errors.DeadlockDetected)
    ]


@tagged("post_install", "-at_install")
class TestLockOrder(CommittedConcurrencyCase):
    def _assert_no_deadlock(self, results, message):
        found = _deadlocks(results)
        self.assertEqual(
            [str(exc) for exc in found], [], message
        )

    def test_acceptance_and_callback_with_the_same_nonce_do_not_deadlock(self):
        """The cycle from finding #6: acceptance took job-then-nonce while the
        callback took nonce-then-job, so two requests carrying the same nonce
        could each hold one half."""
        for _attempt in range(ATTEMPTS):
            job, receipt = self._job_with_live_lease()
            shared_nonce = "shared-%s" % job.job_id
            acceptance = self._acceptance_args(job, receipt, nonce=shared_nonce)
            callback = self._callback_payload(
                job, receipt, token=receipt.processing_lease_token
            )

            results = self.run_concurrently(
                lambda env: env["picking.assistant.event.receipt"]
                .with_user(self.api_user_id)
                .api_accept_event(*acceptance),
                lambda env: self._apply_callback(
                    callback, env=env, nonce=shared_nonce
                ),
            )

            self._assert_no_deadlock(
                results, "the two paths still take locks in opposite orders"
            )

    def test_two_acceptances_of_the_same_event_do_not_deadlock(self):
        for _attempt in range(ATTEMPTS):
            job, receipt = self._job_with_live_lease()
            args = self._acceptance_args(job, receipt)

            results = self.run_concurrently(
                lambda env: env["picking.assistant.event.receipt"]
                .with_user(self.api_user_id)
                .api_accept_event(*args),
                lambda env: env["picking.assistant.event.receipt"]
                .with_user(self.api_user_id)
                .api_accept_event(*args),
            )

            self._assert_no_deadlock(
                results, "two acceptances of one event deadlocked"
            )

    def test_acceptance_against_a_resource_reservation_does_not_deadlock(self):
        """The resource routes are the third multi-table path.

        The brief named `picking.assistant.resource._reserve_for_job`; no such
        model or method exists. The real resource gate is
        `_locked_job` -> `_require_current_generation`, which is what
        `api_get_job_media` and `api_store_job_artifact` both call, so that is
        what gets raced here.
        """
        for _attempt in range(ATTEMPTS):
            job, receipt = self._job_with_live_lease()
            args = self._acceptance_args(job, receipt)
            job_id = job.job_id
            generation = job.delivery_generation
            source_event_id = receipt.event_id

            def reserve(env):
                jobs = env["picking.assistant.integration.job"].sudo()
                locked = jobs._locked_job(job_id)
                return locked._require_current_generation(
                    generation, source_event_id=source_event_id
                ).id

            results = self.run_concurrently(
                lambda env: env["picking.assistant.event.receipt"]
                .with_user(self.api_user_id)
                .api_accept_event(*args),
                reserve,
            )

            self._assert_no_deadlock(
                results, "acceptance and a resource reservation deadlocked"
            )

    def test_lock_order_constant_is_the_documented_one(self):
        from odoo.addons.picking_assistant_integration.models.receipts import (
            LOCK_ORDER,
        )

        self.assertEqual(LOCK_ORDER, ("nonce", "job", "receipt", "outbox"))
