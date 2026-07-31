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

Why every test here also asserts a POSITIVE control. "No DeadlockDetected in
the results" is satisfied just as well by two workers that never reached the
contended section at all -- an auth group rename, a fixture drift or a
`BrokenBarrierError` would all turn these into tests that pass while proving
nothing. So each test additionally pins the outcome the race MUST produce:
both workers carry the same nonce, so exactly one has to win with a result and
the other has to lose with "Webhook nonce replay.". That pair is only
reachable if both workers really ran and really contended.
"""

import psycopg2

from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .concurrency_common import CommittedConcurrencyCase

# Empirically the buggy code deadlocked within the first two attempts; ten
# leaves a wide margin without making the suite crawl.
ATTEMPTS = 10

NONCE_REPLAY = "Webhook nonce replay."


@tagged("post_install", "-at_install")
class TestLockOrder(CommittedConcurrencyCase):
    def _assert_raced_without_deadlock(self, results, message):
        """The one assertion every race in this file makes.

        Two halves, and both are load-bearing:
        1. no `DeadlockDetected` -- the bug is gone;
        2. exactly one winner and exactly one nonce replay -- the race
           actually happened.
        """
        deadlocks = [
            outcome
            for outcome in results
            if isinstance(outcome, psycopg2.errors.DeadlockDetected)
        ]
        self.assertEqual([str(exc) for exc in deadlocks], [], message)

        winners = [r for r in results if isinstance(r, dict)]
        replays = [
            r
            for r in results
            if isinstance(r, ValidationError) and NONCE_REPLAY in str(r)
        ]
        self.assertEqual(
            (len(winners), len(replays)),
            (1, 1),
            "the two workers did not actually contend for the shared nonce; "
            "results were %r\n%s"
            % (
                results,
                "\n".join(
                    getattr(r, "pwr_traceback", "") for r in results
                ),
            ),
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

            self._assert_raced_without_deadlock(
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

            self._assert_raced_without_deadlock(
                results, "two acceptances of one event deadlocked"
            )

    def test_acceptance_and_guarded_nonce_reservation_do_not_deadlock(self):
        """The resource routes are the third path that takes more than one
        lock, and `api_reserve_request_nonce` is the method that was actually
        wrong there -- it locked job and receipt and reserved the nonce LAST.

        This races the real RPC entry point, not the `_locked_job` /
        `_require_current_generation` pair underneath it. Racing the helpers
        would leave the reordered method itself uncovered: someone restoring
        the old "validate the generation before burning a nonce" intent would
        get no red.

        (The brief named `picking.assistant.resource._reserve_for_job`; no such
        model or method exists in this addon.)
        """
        for _attempt in range(ATTEMPTS):
            job, receipt = self._job_with_live_lease()
            shared_nonce = "shared-%s" % job.job_id
            acceptance = self._acceptance_args(job, receipt, nonce=shared_nonce)
            job_id = job.job_id
            generation = job.delivery_generation
            # Plain str, extracted BEFORE the lambda: `receipt` is bound to
            # this test's own env/cursor, and `run_concurrently` runs each
            # lambda on its OWN env/cursor. A lazy `receipt.<field>` access
            # inside the lambda body would read through the wrong cursor
            # (harness hazard -- see module docstrings elsewhere in this
            # lane for the false-positive/false-negative consequence).
            lease_token = receipt.processing_lease_token

            results = self.run_concurrently(
                lambda env: env["picking.assistant.event.receipt"]
                .with_user(self.api_user_id)
                .api_accept_event(*acceptance),
                lambda env: env["picking.assistant.webhook.nonce"]
                .with_user(self.api_user_id)
                .api_reserve_request_nonce(
                    "n8n_to_backend",
                    "n2b-test",
                    shared_nonce,
                    False,
                    job_id,
                    generation,
                    lease_token,
                ),
            )

            self._assert_raced_without_deadlock(
                results,
                "acceptance and the guarded nonce reservation still take "
                "locks in opposite orders",
            )

    def test_lock_order_constant_is_the_documented_one(self):
        from odoo.addons.picking_assistant_integration.models.receipts import (
            LOCK_ORDER,
        )

        self.assertEqual(LOCK_ORDER, ("nonce", "job", "receipt", "outbox"))

    def test_nonce_unique_constraint_name_matches_the_database(self):
        """`_reserve` classifies a cross-transaction replay by constraint name.

        If Odoo ever renames the constraint, the name check silently stops
        matching and a raw `UniqueViolation` escapes to the caller again --
        a 500 instead of a rejection, and only under concurrency, so nothing
        else in the suite would notice.
        """
        from odoo.addons.picking_assistant_integration.models.receipts import (
            NONCE_UNIQUE_CONSTRAINT,
        )

        self.cr.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'picking_assistant_webhook_nonce'::regclass "
            "AND contype = 'u'"
        )
        self.assertIn(
            NONCE_UNIQUE_CONSTRAINT, [row[0] for row in self.cr.fetchall()]
        )

    def test_independent_env_runs_on_its_own_committed_transaction(self):
        """Smoke test for the other half of `_env_on`.

        `run_concurrently` proves `_env_on` under contention; `independent_env`
        uses the same helper but nothing else called it, so its commit path
        was shipped unexecuted. Three lines settle it: write on the independent
        transaction, then read the row back through the class cursor, which is
        a different connection and can only see it once the commit happened.
        """
        job, _receipt = self._job_with_live_lease()
        with self.independent_env() as env:
            env["picking.assistant.integration.job"].sudo().browse(job.id).write(
                {"correlation_id": "independent-env-smoke"}
            )
        self.cr.commit()  # end this cursor's snapshot before re-reading
        job.invalidate_recordset()
        self.assertEqual(job.correlation_id, "independent-env-smoke")
