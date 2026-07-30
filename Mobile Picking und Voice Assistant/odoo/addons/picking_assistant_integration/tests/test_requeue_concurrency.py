"""A dead-letter requeue must never resurrect a leased row.

Regression cover for whole-branch review finding #7.
"""

import psycopg2

from odoo.exceptions import AccessError, ValidationError

from .concurrency_common import CommittedConcurrencyCase

# A barrier makes both workers reach their first lock inside each other's
# window LIKELY, not certain (see `test_lock_order.py`, which this constant
# and the looping pattern below both mirror). Measured directly: with
# `api_requeue_dead` inverted to outbox-then-job, a genuine
# `psycopg2.errors.DeadlockDetected` (confirmed via its own message, not
# inferred -- "Process N waits for ShareLock on transaction M; blocked by
# process M ... CONTEXT: while locking tuple ... in relation
# picking_assistant_integration_job") appeared in roughly 1 of 6 runs of
# `DEADLOCK_TEST_ATTEMPTS = 10`, i.e. a rough per-attempt hit rate on the
# order of 1-2%. `test_lock_order.py`'s own races are nonce-forced (both
# workers deliberately reserve the identical nonce) and deadlock within
# their first two attempts; this race has no such forcing hook, so it needs
# a much larger budget for a comparable single-run catch probability. 30 is
# a compromise: high enough to make a reintroduced inversion very likely to
# surface within one CI run, without adding a slow test to a suite already
# measured in minutes on this environment.
DEADLOCK_TEST_ATTEMPTS = 30


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
        outbox (`LOCK_ORDER[1]` then `[3]`). `test_lock_order.py` covers
        accept-vs-callback, accept-vs-accept and accept-vs-nonce
        reservation; nothing there pairs requeue with acceptance, so this
        method's own lock-ordering claim (`outbox.py` :221-224) was
        dynamically unverified until this test.

        Fix-round-1 shipped a version of this test sharing only the job
        row, and disclosed (correctly) that a single shared resource cannot
        form a cycle regardless of ordering -- which review then correctly
        called out as disclosure, not closure: a test that cannot go red
        under the exact inversion it claims to guard against is not
        covering that claim. This version shares BOTH the job row AND the
        outbox row, which is what real two-resource contention -- and
        therefore a real possibility of a lock-order cycle -- requires.

        Sharing the outbox row was fix-round-1's blocker: `api_requeue_dead`
        writes the outbox row it locks when it wins, and (at the time)
        `api_accept_event`'s own outbox `FOR UPDATE` (`receipts.py`) had no
        SQLSTATE 40001 classification, so the loser would leak a raw
        `SerializationFailure` from inside acceptance in the ordinary,
        non-inverted case too -- not a lock-order finding, just noise. This
        round's review extended the task's scope to `receipts.py` for
        exactly this reason; that lock is now classified the same way
        `api_requeue_dead`'s is, into the same message
        (`"Outbox event changed during acceptance."`) `api_accept_event`
        already raises for an ordinary post-lock linkage change.

        Ordinary-case outcome (both paths correctly ordered, job then
        outbox): whichever worker wins the job lock also wins the outbox
        lock, because the loser is blocked on job for its entire wait and
        the winner has fully committed (releasing both locks) before the
        loser is even unblocked.
        - `api_requeue_dead` (`results[0]`) always ends up succeeding
          either way: if it wins the job race it locks-and-writes outbox
          directly; if it loses, `api_accept_event`'s dedup path (see
          below) never writes outbox, so requeue's own outbox lock hits no
          conflict once it is unblocked. This makes `results[0]` an
          order-independent positive control -- proof both workers really
          acquired the SAME job and outbox rows, not two workers that
          never overlapped.
        - `api_accept_event` (`results[1]`) depends on who won: a `dict`
          (its own dedup success) if it won the job race, or the
          now-classified `ValidationError` if it lost. Both are
          acceptable, non-raw outcomes; the accepted event already carries
          an ALREADY-LIVE processing lease (`_job_with_live_lease`), so
          `api_accept_event` takes the dedup path and never writes job --
          its own copy of the write vs. lock-only asymmetry that makes
          `results[0]`'s outcome deterministic.

        Inverted-case outcome (negative control, `fix-round-2` report): with
        `api_requeue_dead` temporarily flipped to outbox-then-job, the two
        paths take the SAME two locks in OPPOSITE order -- the textbook
        two-resource cycle, and it was reproduced for real: a genuine
        `psycopg2.errors.DeadlockDetected` ("Process N waits for ShareLock
        on transaction M; blocked by process M ... while locking tuple ...
        in relation picking_assistant_integration_job"), Postgres's own
        deadlock detector aborting one side. A single barrier-synced
        attempt only makes the two workers' first-lock timing overlap
        LIKELY, not certain (same reasoning as `test_lock_order.py`'s own
        `ATTEMPTS` loop) -- measured here at roughly a 1-in-6 hit rate per
        `DEADLOCK_TEST_ATTEMPTS`-sized batch at 10 attempts, hence the
        larger budget; see the constant's own comment for the measurement.

        The assertion below checks for "no raw `psycopg2.Error`, on either
        side" rather than filtering for `pgcode == 40P01` alone. The first
        draft of this test used only a `40P01` filter and an early version
        of it went red intermittently EVEN WITH THE CORRECT LOCK ORDER --
        traced (via the exception's own captured traceback, not guessed) to
        an unrelated bug IN THIS TEST, not in `outbox.py` or `receipts.py`:
        the lambdas read `receipt.event_id` / `job.job_id` / etc. lazily,
        AT RACE TIME, on recordsets bound to `self.env` (the class-level
        cursor `cls.cr`). `.write()` calls before the race invalidate that
        cache, so those reads issued a fresh `SELECT` on `cls.cr` from
        WHICHEVER worker thread happened to touch the field first --
        `cls.cr` used from two threads at once, independent of any lock in
        the code under test, and it surfaced as
        `psycopg2.ProgrammingError: no results to fetch` (one thread's
        `execute()` clobbering the other's pending result set). Fixed by
        pre-materializing every value the lambdas need, in the main thread,
        before `run_concurrently` -- the same discipline
        `test_lock_order.py`'s `_acceptance_args(...)`-before-the-race
        already follows; see the comment at the call site below. The
        broader "no raw psycopg2.Error at all" assertion was kept after the
        fix (rather than narrowed back to `pgcode == 40P01` alone) as a
        standing guard against this class of mistake recurring, not only
        against a genuine lock cycle.
        """
        for _attempt in range(DEADLOCK_TEST_ATTEMPTS):
            job, receipt = self._job_with_live_lease()
            outbox = (
                self.env["picking.assistant.outbox"]
                .sudo()
                .search([("event_id", "=", receipt.event_id)])
            )
            outbox.write({"state": "dead"})
            supervisor = self._active_supervisor()
            self.env.cr.commit()

            # Pre-materialize every value the racing lambdas need as PLAIN
            # Python values, in the main thread, BEFORE the race starts.
            # `receipt` / `job` / `supervisor` are recordsets bound to
            # `self.env` -- the class-level cursor `cls.cr`, shared by
            # every test method AND by `tearDownClass`. An UNCACHED field
            # read on them from INSIDE a `run_concurrently` lambda issues a
            # fresh `SELECT` on `cls.cr` from the WORKER thread, not the
            # main one: a genuine cross-thread use of one cursor. The
            # `.write()` calls above (and inside `_job_with_live_lease`)
            # invalidate the ORM's field cache, so `receipt.event_id`
            # accessed lazily inside a lambda is exactly that hazard --
            # confirmed empirically in fix round 2: it produced
            # `psycopg2.ProgrammingError: no results to fetch`, two threads
            # racing statements on the same cursor. `test_lock_order.py`'s
            # own `_acceptance_args(...)` call BEFORE `run_concurrently` is
            # the same precaution already established in this file;
            # `_accept_event(job, receipt, env=env)` is UNSAFE to call FROM
            # a lambda for the same reason (it computes `_acceptance_args`
            # internally, at race time, not before it), so this test calls
            # `api_accept_event` directly with pre-computed args instead.
            event_id = receipt.event_id
            supervisor_id = supervisor.id
            acceptance_args = self._acceptance_args(job, receipt)

            results = self.run_concurrently(
                lambda env: env["picking.assistant.outbox"]
                .with_user(self.api_user_id)
                .api_requeue_dead(event_id, supervisor_id, "reason"),
                lambda env: env["picking.assistant.event.receipt"]
                .with_user(self.api_user_id)
                .api_accept_event(*acceptance_args),
            )

            self._assert_no_lock_cycle(results)

    def _assert_no_lock_cycle(self, results):
        # Positive control #1 (order-independent): requeue always completes
        # when the two paths take job-then-outbox in the same order --
        # proof both workers really acquired the SAME job and outbox rows,
        # not two workers that never overlapped.
        self.assertIsInstance(results[0], dict, results)
        self.assertEqual(results[0]["state"], "pending")
        # Positive control #2: acceptance landed on exactly one of the two
        # outcomes genuine shared-row contention allows under the correct
        # lock order. Any THIRD outcome -- a raw `psycopg2.Error`, or
        # anything else -- is not something the correctly-ordered code
        # should ever produce (see the docstring for what a lock cycle
        # under the INVERTED order actually looks like).
        acceptable = isinstance(results[1], dict) or (
            isinstance(results[1], ValidationError)
            and "Outbox event changed during acceptance." in str(results[1])
        )
        self.assertTrue(
            acceptable, "unexpected acceptance outcome: %r" % (results[1],)
        )

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
