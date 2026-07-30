"""A dead-letter requeue must never resurrect a leased row.

Regression cover for whole-branch review finding #7.
"""

import psycopg2

from odoo.exceptions import AccessError, ValidationError

from .concurrency_common import CommittedConcurrencyCase


class TestRequeueConcurrency(CommittedConcurrencyCase):
    def test_two_requeues_do_not_both_reset_the_row(self):
        outbox = self._dead_outbox_row()
        supervisor = self._active_supervisor()

        results = self.run_concurrently(
            lambda env: env["picking.assistant.outbox"]
            .with_user(self.api_user_id)
            .api_requeue_dead(outbox.event_id, supervisor.id, "first"),
            lambda env: env["picking.assistant.outbox"]
            .with_user(self.api_user_id)
            .api_requeue_dead(outbox.event_id, supervisor.id, "second"),
        )

        winners = [r for r in results if isinstance(r, dict)]
        losers = [r for r in results if isinstance(r, Exception)]
        # `isinstance(r, dict)` alone is not a positive control: it is
        # satisfied by ANY loser outcome whatsoever -- a clean
        # `ValidationError`, a raw `psycopg2.errors.SerializationFailure`,
        # even an `AttributeError` from a typo. Postgres's own REPEATABLE
        # READ already forbids the second write from silently succeeding, so
        # that half of the assertion holds even with `FOR UPDATE` and the
        # revalidation removed entirely. Pinning the loser's exception TYPE
        # is what actually exercises this method's classification: it must
        # be the same clean `ValidationError` a caller gets from the
        # lock-free path, not the raw driver error `outbox.py` classifies by
        # SQLSTATE 40001 (`psycopg2.errors.SerializationFailure`).
        self.assertEqual(
            len(winners), 1, "exactly one requeue may win; the other must find no dead row"
        )
        self.assertEqual(len(losers), 1)
        self.assertIsInstance(
            losers[0],
            ValidationError,
            "the losing requeue must be refused cleanly, not leak a raw "
            "psycopg2 error: %r" % (losers[0],),
        )
        self.assertNotIsInstance(losers[0], psycopg2.Error)

    def test_two_requeues_do_not_deadlock_with_accept_event(self):
        """`api_requeue_dead` and `api_accept_event` both take job THEN
        outbox. `test_lock_order.py` covers accept-vs-callback,
        accept-vs-accept and accept-vs-nonce reservation; nothing there pairs
        requeue with acceptance.

        Scope decision, recorded rather than papered over: this test shares
        only the JOB row between the two workers, not the outbox row. A
        genuine two-resource race (both workers also fighting over the SAME
        outbox row) is what a true cycle test needs -- but `api_requeue_dead`
        WRITES the outbox row it locks when it wins, and `api_accept_event`'s
        own outbox `FOR UPDATE` (`receipts.py` :368-372) has no SQLSTATE
        40001 classification of its own. Whichever worker loses the outbox
        race would then surface a raw, untranslated `SerializationFailure`
        from INSIDE `api_accept_event` roughly half the time (whichever side
        loses the earlier job-lock race also loses the outbox race, since
        both take the same two locks in the same order) -- a real,
        pre-existing gap, but in `receipts.py`, not `outbox.py`, and
        therefore out of this task's scope per review (classification here
        was scoped to the outbox lock in `api_requeue_dead` only). Sharing
        the outbox row would make this test flaky for a reason that has
        nothing to do with the lock-ordering claim under test.

        Consequence, checked empirically rather than assumed: with only ONE
        resource genuinely shared, no ordering of the other (unshared)
        locks can ever form a two-resource cycle -- that's what "cycle"
        means. Verified by temporarily inverting `api_requeue_dead` to
        outbox-then-job and re-running this test: it stayed green across 3
        runs (see fix-round-1 report), confirming this test cannot, by
        construction, catch a lock-order inversion in `api_requeue_dead`.
        What it DOES verify is the positive control below: both entry
        points really lock the SAME job row concurrently and both still
        complete -- which is the part of the docstring's claim ("this path
        cannot form a lock-order cycle") that a dynamic test can check at
        all; the rest of the claim (both paths take job before outbox) is a
        static fact, confirmed by reading `outbox.py` and `receipts.py`
        side by side, not by this test.

        The accepted event already carries a LIVE processing lease
        (`_job_with_live_lease`, the same fixture `test_lock_order.py` uses):
        `api_accept_event` then takes its early-return, dedup path and never
        writes the job row either, so this test's own job lock never risks
        the same unclassified-write conflict on that resource.
        """
        job, live_receipt = self._job_with_live_lease()
        dead_receipt = self.track(
            self.env["picking.assistant.event.receipt"].create(
                self._receipt_values(job, state="processing")
            )
        )
        dead_outbox = self.track(
            self.env["picking.assistant.outbox"].create(
                self._outbox_values(job, dead_receipt, state="dead")
            )
        )
        supervisor = self._active_supervisor()
        self.env.cr.commit()

        results = self.run_concurrently(
            lambda env: env["picking.assistant.outbox"]
            .with_user(self.api_user_id)
            .api_requeue_dead(dead_outbox.event_id, supervisor.id, "reason"),
            lambda env: self._accept_event(job, live_receipt, env=env),
        )

        deadlocks = [
            r
            for r in results
            if isinstance(r, psycopg2.Error)
            and getattr(r, "pgcode", None) == "40P01"
        ]
        self.assertFalse(
            deadlocks, "requeue and accept must not deadlock: %r" % (results,)
        )
        # Positive control: both workers really contended for the same job
        # row (not "no deadlock" by two workers that never overlapped) --
        # the requeue is on a different event than the acceptance, so
        # nothing but the shared job lock could make either one fail, and
        # both must succeed.
        self.assertIsInstance(results[0], dict)
        self.assertEqual(results[0]["state"], "pending")
        self.assertIsInstance(results[1], dict)
        self.assertEqual(results[1]["process"], False)

    def test_requeue_clears_the_dispatcher_lease(self):
        outbox = self._dead_outbox_row(lease_owner="held-by-a-dispatcher")
        supervisor = self._active_supervisor()

        self.env["picking.assistant.outbox"].with_user(
            self.api_user_id
        ).api_requeue_dead(outbox.event_id, supervisor.id, "reason")

        outbox.invalidate_recordset()
        self.assertEqual(outbox.state, "pending")
        self.assertFalse(outbox.lease_owner)
        self.assertFalse(outbox.lease_expires_at)

    def test_archived_supervisor_is_refused(self):
        outbox = self._dead_outbox_row()
        supervisor = self._active_supervisor()
        supervisor.sudo().write({"active": False})
        self.env.cr.commit()

        with self.assertRaises(AccessError):
            self.env["picking.assistant.outbox"].with_user(
                self.api_user_id
            ).api_requeue_dead(outbox.event_id, supervisor.id, "reason")

    def test_share_user_with_the_group_is_refused(self):
        outbox = self._dead_outbox_row()
        supervisor = self._active_supervisor()
        supervisor.sudo().write({"share": True})
        self.env.cr.commit()

        with self.assertRaises(AccessError):
            self.env["picking.assistant.outbox"].with_user(
                self.api_user_id
            ).api_requeue_dead(outbox.event_id, supervisor.id, "reason")
