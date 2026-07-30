import json
import threading
import traceback
from datetime import timedelta
from uuid import uuid4

import psycopg2

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import IntegrationCase
from .concurrency_common import CommittedConcurrencyCase


class TestSessionAndThrottle(IntegrationCase):
    def test_session_stores_hashes_and_returns_sanitized_principal(self):
        model = self.env["picking.assistant.session"].with_user(self.api_user)
        expires_at = fields.Datetime.now() + timedelta(hours=8)
        model.api_create_session(
            "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
            "0" * 64,
            "1" * 64,
            self.picker.id,
            "device-42",
            ["picker"],
            fields.Datetime.to_string(expires_at),
        )
        result = model.api_get_session("0" * 64, touch=True)
        self.assertEqual(result["picker_user_id"], self.picker.id)
        self.assertNotIn("token_hash", result)
        self.assertNotIn("csrf_hash", result)

    def test_session_lifetime_over_8h_is_rejected(self):
        model = self.env["picking.assistant.session"].with_user(self.api_user)
        expires_at = fields.Datetime.now() + timedelta(hours=8, seconds=1)
        with self.assertRaises(ValidationError):
            model.api_create_session(
                "5eec3553-f69b-58af-a7ac-2fd2e88ac999",
                "2" * 64,
                "3" * 64,
                self.picker.id,
                "device-43",
                ["picker"],
                fields.Datetime.to_string(expires_at),
            )

    def test_fifth_failure_locks_for_window_and_success_clears(self):
        throttle = self.env["picking.assistant.auth.throttle"].with_user(self.api_user)
        for _index in range(5):
            state = throttle.api_record_login_result("mina", "a" * 64, False)
        self.assertFalse(state["allowed"])
        self.assertTrue(state["locked_until"])
        state = throttle.api_record_login_result("mina", "a" * 64, True)
        self.assertTrue(state["allowed"])
        self.assertEqual(state["failure_count"], 0)

    def test_csrf_hash_is_compared_inside_odoo(self):
        model = self.env["picking.assistant.session"].with_user(self.api_user)
        expires_at = fields.Datetime.now() + timedelta(hours=8)
        model.api_create_session(
            "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
            "0" * 64,
            "1" * 64,
            self.picker.id,
            "device-42",
            ["picker"],
            fields.Datetime.to_string(expires_at),
        )
        self.assertTrue(
            model.api_validate_csrf(
                "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88", "1" * 64
            )
        )
        self.assertFalse(
            model.api_validate_csrf(
                "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88", "2" * 64
            )
        )

    def test_role_marking_rejects_a_revoked_session(self):
        """Cover for minor M1. Deterministic, no concurrency needed: the old
        `api_mark_roles_checked` wrote the new roles and handed the session
        back unconditionally -- it never checked `revoked_at` or
        `expires_at` at all, concurrently or otherwise."""
        model = self.env["picking.assistant.session"].with_user(self.api_user)
        session_id = "6a13d222-1111-4444-8888-000000000001"
        expires_at = fields.Datetime.now() + timedelta(hours=8)
        model.api_create_session(
            session_id,
            "4" * 64,
            "5" * 64,
            self.picker.id,
            "device-99",
            ["picker"],
            fields.Datetime.to_string(expires_at),
        )
        self.env["picking.assistant.session"].sudo().search(
            [("session_id", "=", session_id)]
        ).write({"revoked_at": fields.Datetime.now()})

        result = model.api_mark_roles_checked(session_id, ["picker", "supervisor"])
        self.assertFalse(result, "a revoked session must not survive role marking")

    def test_role_marking_rejects_an_expired_session(self):
        """Cover for minor M1's other half: expiry, not just revocation."""
        model = self.env["picking.assistant.session"].with_user(self.api_user)
        session_id = "6a13d222-1111-4444-8888-000000000002"
        expires_at = fields.Datetime.now() + timedelta(hours=8)
        model.api_create_session(
            session_id,
            "6" * 64,
            "7" * 64,
            self.picker.id,
            "device-99",
            ["picker"],
            fields.Datetime.to_string(expires_at),
        )
        self.env["picking.assistant.session"].sudo().search(
            [("session_id", "=", session_id)]
        ).write({"expires_at": fields.Datetime.now() - timedelta(seconds=1)})

        result = model.api_mark_roles_checked(session_id, ["picker"])
        self.assertFalse(result, "an expired session must not survive role marking")

    def test_role_marking_updates_roles_for_a_live_session(self):
        """Happy path: the fix must not reject a session that is neither
        revoked nor expired."""
        model = self.env["picking.assistant.session"].with_user(self.api_user)
        session_id = "6a13d222-1111-4444-8888-000000000003"
        expires_at = fields.Datetime.now() + timedelta(hours=8)
        model.api_create_session(
            session_id,
            "8" * 64,
            "9" * 64,
            self.picker.id,
            "device-99",
            ["picker"],
            fields.Datetime.to_string(expires_at),
        )
        result = model.api_mark_roles_checked(session_id, ["picker", "supervisor"])
        self.assertEqual(sorted(result["roles"]), ["picker", "supervisor"])


# Empirically the buggy `_lock_or_create` raised on the very first attempt
# of the dedicated race below; five leaves a wide margin without making the
# suite crawl (see `test_lock_order.py` for the same reasoning).
_RACE_ATTEMPTS = 5


@tagged("post_install", "-at_install")
class TestThrottleConcurrency(CommittedConcurrencyCase):
    """Races finding #10 needs two real transactions: on one cursor the
    "check, authenticate, record" sequence is three statements in one
    transaction and can never contend. See `concurrency_common.py`."""

    def test_parallel_attempts_cannot_all_pass_the_check(self):
        """Five in-flight attempts consume the budget even before any of them
        has failed. Regression cover for finding #10.

        Fix round 1, Finding 2: a first version of this test raced eight
        workers with `run_concurrently` (no retry) against a shared row.
        Under Odoo's REPEATABLE READ, eight workers started together on a
        barrier and contending for the SAME row's `FOR UPDATE` lock can
        structurally produce at most ONE clean completion per round: every
        loser's snapshot is already stale against the winner's commit and
        it gets `SerializationFailure`, not a delayed look at the updated
        row. That made `len(allowed) <= 5` true in EVERY run regardless of
        whether the in-flight counting guard was even wired up correctly
        -- and it did not even guard the method's existence: delete
        `api_begin_login_attempt` and all eight results are
        `AttributeError`, `allowed` is empty, and `assertLessEqual(0, 5)`
        still passes green.

        Fixed by giving each worker its own bounded retry loop -- a fresh
        cursor and environment per attempt, exactly like Odoo's own
        `retrying()` RPC wrapper does in production, which `run_concurrently`
        does not provide. That makes the eight workers actually serialise
        through the row lock instead of dying on the first contention, and
        the outcome becomes exactly 5 allowed with a correct guard versus 8
        with it broken -- `assertEqual(len(allowed), 5)` below discriminates
        both directions, not just "no crash under load".
        """
        login_key, ip_key = "picker@example.com", "hmac-value"
        api_user_id = self.api_user_id
        worker_count = 8
        max_tries = 10

        # Match `run_concurrently`'s own discipline: commit the class
        # cursor first so no fixture write from a previous test is still
        # held as a lock the workers would wait on.
        self.cr.commit()
        barrier = threading.Barrier(worker_count)
        results = [None] * worker_count

        def worker(index):
            barrier.wait(timeout=30)
            last_exc = None
            for _try in range(max_tries):
                cr = self.registry.cursor()
                try:
                    env = self._env_on(cr)
                    result = (
                        env["picking.assistant.auth.throttle"]
                        .with_user(api_user_id)
                        .api_begin_login_attempt(login_key, ip_key)
                    )
                    cr.commit()
                    results[index] = result
                    return
                except Exception as exc:  # noqa: BLE001 - retry-or-record
                    cr.rollback()
                    last_exc = exc
                    if not isinstance(exc, psycopg2.errors.SerializationFailure):
                        exc.pwr_traceback = traceback.format_exc()
                        results[index] = exc
                        return
                finally:
                    cr.close()
            last_exc.pwr_traceback = "exhausted %d retries" % max_tries
            results[index] = last_exc

        threads = [
            threading.Thread(target=worker, args=(i,)) for i in range(worker_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
            self.assertFalse(thread.is_alive(), "a retrying worker did not finish")
        self.cr.commit()

        type_errors = [r for r in results if isinstance(r, TypeError)]
        self.assertEqual(
            type_errors,
            [],
            "in-flight reservation must never surface a raw TypeError:\n%s"
            % "\n".join(getattr(r, "pwr_traceback", "") for r in results),
        )
        allowed = [r for r in results if isinstance(r, dict) and r["allowed"]]
        self.assertEqual(
            len(allowed),
            5,
            "in-flight attempts must count exactly against the limit once "
            "every worker has been retried to completion; results were %r\n%s"
            % (
                results,
                "\n".join(getattr(r, "pwr_traceback", "") for r in results),
            ),
        )

        self.track(
            self.env["picking.assistant.auth.throttle"]
            .sudo()
            .search([("login_key", "=", login_key), ("source_ip_hmac", "=", ip_key)])
        )

    def test_a_finished_successful_attempt_frees_its_slot(self):
        login_key, ip_key = "picker2@example.com", "hmac-value"
        model = self.env["picking.assistant.auth.throttle"]
        api_model = model.with_user(self.api_user_id)
        started = api_model.api_begin_login_attempt(login_key, ip_key)
        self.assertTrue(started["allowed"])

        api_model.api_finish_login_attempt(login_key, ip_key, started["attempt_token"], True)

        record = model.search(
            [("login_key", "=", login_key), ("source_ip_hmac", "=", ip_key)], limit=1
        )
        self.track(record)
        self.assertEqual(record.in_flight_count, 0)
        self.assertEqual(record.failure_count, 0)

    def test_a_finished_failed_attempt_becomes_a_recorded_failure(self):
        login_key, ip_key = "picker3@example.com", "hmac-value"
        model = self.env["picking.assistant.auth.throttle"]
        api_model = model.with_user(self.api_user_id)
        started = api_model.api_begin_login_attempt(login_key, ip_key)

        api_model.api_finish_login_attempt(login_key, ip_key, started["attempt_token"], False)

        record = model.search(
            [("login_key", "=", login_key), ("source_ip_hmac", "=", ip_key)], limit=1
        )
        self.track(record)
        self.assertEqual(record.in_flight_count, 0)
        self.assertEqual(record.failure_count, 1)

    def test_a_success_resets_the_failure_window(self):
        """Regression cover for fix round 1, Finding 3.

        `_failure_values` anchors `locked_until` at `window_started_at +
        FAILURE_WINDOW`. The brief's literal success branch of
        `api_finish_login_attempt` cleared `failure_count` and
        `locked_until` but left `window_started_at` stale, so a lockout
        following a later run of failures silently anchored to the OLD
        window instead of the new one -- concretely: failures at t=0, a
        success at t=1 (failure_count reset to 0, window_started_at stays
        0), then five more failures at t=14min would compute
        `locked_until = 0 + 15min`, a lockout of about ONE minute instead
        of a full FAILURE_WINDOW. Four failures, a success, then five more
        failures must anchor the lockout at the LAST run's start, not the
        first one's.
        """
        login_key, ip_key = "picker5@example.com", "hmac-value"
        model = self.env["picking.assistant.auth.throttle"]
        api_model = model.with_user(self.api_user_id)

        for _ in range(4):
            started = api_model.api_begin_login_attempt(login_key, ip_key)
            api_model.api_finish_login_attempt(
                login_key, ip_key, started["attempt_token"], False
            )

        started = api_model.api_begin_login_attempt(login_key, ip_key)
        api_model.api_finish_login_attempt(
            login_key, ip_key, started["attempt_token"], True
        )

        record = model.sudo().search(
            [("login_key", "=", login_key), ("source_ip_hmac", "=", ip_key)], limit=1
        )
        self.track(record)
        self.assertFalse(
            record.window_started_at,
            "a success must clear the failure window, not just "
            "failure_count -- a stale window silently shortens the NEXT "
            "lockout below a full FAILURE_WINDOW",
        )

        from odoo.addons.picking_assistant_integration.models.auth_throttle import (
            FAILURE_WINDOW,
        )

        before_second_run = fields.Datetime.now()
        for _ in range(5):
            started = api_model.api_begin_login_attempt(login_key, ip_key)
            api_model.api_finish_login_attempt(
                login_key, ip_key, started["attempt_token"], False
            )
        record.invalidate_recordset()
        self.assertTrue(record.locked_until)
        self.assertGreaterEqual(
            record.locked_until,
            before_second_run + FAILURE_WINDOW - timedelta(seconds=5),
            "the lockout must span a full FAILURE_WINDOW anchored at the "
            "failure run that actually triggered it, not a stale "
            "pre-success window",
        )

    def test_an_abandoned_attempt_stops_counting_after_the_ttl(self):
        """A crashed backend must not lock an account out forever."""
        login_key, ip_key = "picker4@example.com", "hmac-value"
        model = self.env["picking.assistant.auth.throttle"]
        api_model = model.with_user(self.api_user_id)
        for _ in range(5):
            api_model.api_begin_login_attempt(login_key, ip_key)
        self.assertFalse(api_model.api_begin_login_attempt(login_key, ip_key)["allowed"])

        record = model.search(
            [("login_key", "=", login_key), ("source_ip_hmac", "=", ip_key)], limit=1
        )
        self.track(record)
        record.write({"last_attempt_at": fields.Datetime.now() - timedelta(seconds=31)})

        self.assertTrue(api_model.api_begin_login_attempt(login_key, ip_key)["allowed"])

    def test_concurrent_row_creation_never_raises_a_raw_typeerror(self):
        """Mandatory addition escalated from Task 3's re-review:
        `_lock_or_create`'s `except IntegrityError` branch used to re-SELECT
        `FOR UPDATE` after a losing INSERT. Under Odoo's REPEATABLE READ that
        re-SELECT runs on the loser's original (pre-commit) snapshot, finds
        nothing, and `browse(row[0])` on `row = None` raised a raw
        `TypeError: 'NoneType' object is not subscriptable` -- which Odoo's
        `retrying()` RPC wrapper does not retry, because it is not a
        serialization or deadlock failure.

        Fix round 1, Finding 1: a first version of the fix classified the
        conflict by constraint name and raised a Python-constructed
        `psycopg2.errors.SerializationFailure`. That was insufficient:
        `retrying()` does not dispatch on exception CLASS, it reads
        `exc.pgcode`, and a Python-instantiated psycopg2 exception has
        `pgcode = None` (confirmed: `python -c "import psycopg2.errors;
        print(psycopg2.errors.SerializationFailure('x').pgcode)"` -> `None`
        inside the odoo19-trial image). `None` is never in the retried set,
        so the synthetic exception was re-raised on the first pass -- same
        two consequences as the original bug, just a different traceback.
        The actual fix asks Postgres to raise the real thing via
        `INSERT ... ON CONFLICT DO UPDATE ... RETURNING id`, which forces
        an EvalPlanQual recheck that Postgres itself turns into a
        driver-populated `SerializationFailure` (pgcode `40001`) under
        REPEATABLE READ. This test now asserts on `pgcode` directly,
        because the exception CLASS alone is exactly the insufficient
        thing fix round 1 shipped.

        This needs two real transactions creating the SAME (login_key,
        source_ip_hmac) row for the first time: on one cursor the loser's
        `SELECT ... FOR UPDATE` sees its own uncommitted INSERT and the
        conflict path is never reached at all.

        The loop is required for the same reason `test_lock_order.py`'s is:
        a race is an interleaving, not a state, so one clean pass proves
        nothing. Each iteration uses a fresh (login_key, ip) pair so the
        create-vs-create race, not the update-vs-update race, is what is
        being exercised every time.
        """
        for _attempt in range(_RACE_ATTEMPTS):
            login_key = "race-%s@example.com" % uuid4().hex
            ip_key = "hmac-%s" % uuid4().hex

            results = self.run_concurrently(
                lambda env: env["picking.assistant.auth.throttle"]
                .with_user(self.api_user_id)
                .api_begin_login_attempt(login_key, ip_key),
                lambda env: env["picking.assistant.auth.throttle"]
                .with_user(self.api_user_id)
                .api_begin_login_attempt(login_key, ip_key),
            )

            type_errors = [r for r in results if isinstance(r, TypeError)]
            self.assertEqual(
                type_errors,
                [],
                "a concurrent row-creation race must never surface a raw "
                "TypeError:\n%s"
                % "\n".join(getattr(r, "pwr_traceback", "") for r in results),
            )

            winners = [r for r in results if isinstance(r, dict)]
            losers = [r for r in results if not isinstance(r, dict)]
            self.assertGreaterEqual(
                len(winners),
                1,
                "at least one side of the race must complete the create; "
                "results were %r" % (results,),
            )
            for loser in losers:
                self.assertIsInstance(
                    loser,
                    psycopg2.errors.SerializationFailure,
                    "the losing side of a row-creation race must raise a "
                    "SerializationFailure, not %r" % (loser,),
                )
                self.assertEqual(
                    getattr(loser, "pgcode", None),
                    "40001",
                    "the exception CLASS alone is not enough -- fix round 1 "
                    "shipped a Python-constructed SerializationFailure whose "
                    "pgcode was None, which Odoo's retrying() does not "
                    "retry. This must be a driver-populated 40001, i.e. "
                    "raised by Postgres itself, not synthesised in Python.",
                )

            self.track(
                self.env["picking.assistant.auth.throttle"]
                .sudo()
                .search(
                    [
                        ("login_key", "=", login_key),
                        ("source_ip_hmac", "=", ip_key),
                    ]
                )
            )


# Same reasoning as `_RACE_ATTEMPTS` above: one clean interleaving proves
# nothing about a race, and `run_concurrently` needs two REAL transactions
# for `revoke` and `mark` to ever contend for the same row at all.
_ROLE_MARKING_RACE_ATTEMPTS = 8


@tagged("post_install", "-at_install")
class TestSessionRoleMarkingConcurrency(CommittedConcurrencyCase):
    """Defense-in-depth for minor M1 under actual concurrent contention.

    IMPORTANT, established empirically with a negative control (revert only
    `session.py`'s fix and re-run this class): this specific race does
    **not** discriminate the pre-fix code from the fix. Every one of 4
    measured runs (32 attempts total) came back with the SAME result on
    both sides of the fix -- `mark`'s write, guarded or not, collided with
    `revoke`'s write and Postgres itself raised `SerializationFailure` on
    the LOSING statement, because REPEATABLE READ rejects ANY UPDATE
    against a row a concurrently-committed transaction has already changed,
    not only a `SELECT ... FOR UPDATE`. A barrier-synchronised start simply
    never produces the interleaving the bug needs (mark's read completing,
    then its write landing AFTER revoke has already committed, with no
    conflicting write on mark's own side) -- that specific gap only exists
    with the un-guarded code, and closing it is exactly what the lock adds,
    but the two naked UPDATEs from `revoke` and the OLD `mark` already
    fight each other head-on before either commits.

    The REAL, DISCRIMINATING regression cover for M1 is
    `TestSessionAndThrottle.test_role_marking_rejects_a_revoked_session`
    and `..._rejects_an_expired_session` above: they revoke/expire the
    session on the SAME transaction/cursor `mark` reads from (no race
    needed -- REPEATABLE READ trivially allows a transaction to see its
    own uncommitted writes), which reproduces exactly the "resolved once,
    stale by the time roles are marked" defect from the finding. Those two
    tests fail on the pre-fix code (confirmed) and pass after the fix
    (confirmed); THIS test passes on both, always.

    What this test still proves, and is kept for: the fix's `FOR UPDATE` +
    savepoint pattern converts a real, driver-raised 40001 into a
    `ValidationError` rather than leaking a raw `psycopg2` exception past
    the RPC boundary, and never lets a session that ends up revoked walk
    away with a live payload -- exactly the invariant a reviewer would
    otherwise have to trust by reading the code.
    """

    def test_role_marking_rechecks_revocation_under_lock(self):
        """See the class docstring for what this test does and does not
        discriminate.

        Harness hazard #1: `revoke` and `mark` below take only pre-
        materialised primitives (`session_pk`, `session_id`, `api_user_id`)
        -- never a `self.env`-bound recordset -- so each worker's lazy ORM
        field access runs on ITS OWN cursor, not the outer environment's.

        Harness hazard #2: both sides of this race take a lock on the SAME
        row (`revoke` via the ORM's implicit UPDATE lock, `mark` via its
        explicit `FOR UPDATE`), so under REPEATABLE READ either one can
        lose with a driver-raised `SerializationFailure` -- a first version
        of this test asserted "revoke never fails", which is exactly the
        untested-assumption trap the harness notes warn about, and it was
        caught by a real GREEN-run failure, not by inspection. The
        assertion below does not guess which side wins: it re-reads the
        row's COMMITTED state after the race and checks the one thing that
        must never be true regardless of interleaving -- a session that
        ended up revoked must never have handed back a live role-marking
        payload.
        """
        api_user_id = self.api_user_id
        outcomes = {"revoked_and_falsy_or_raised": 0, "not_revoked_and_dict": 0}
        bad_attempts = []

        for attempt in range(_ROLE_MARKING_RACE_ATTEMPTS):
            session_id = "race-session-%d-%s" % (attempt, uuid4().hex)
            session = self.track(
                self.env["picking.assistant.session"].sudo().create(
                    {
                        "session_id": session_id,
                        "token_hash": uuid4().hex,
                        "csrf_hash": uuid4().hex,
                        "user_id": api_user_id,
                        "device_id": "device-race",
                        "roles_json": json.dumps(["picker"]),
                        "expires_at": fields.Datetime.now() + timedelta(hours=1),
                    }
                )
            )
            session_pk = session.id
            self.env.cr.commit()

            def revoke(env):
                env["picking.assistant.session"].sudo().browse(session_pk).write(
                    {"revoked_at": fields.Datetime.now()}
                )

            def mark(env):
                return (
                    env["picking.assistant.session"]
                    .with_user(api_user_id)
                    .api_mark_roles_checked(session_id, ["picker", "supervisor"])
                )

            results = self.run_concurrently(revoke, mark)
            revoke_result, marked = results

            for result in results:
                if isinstance(result, Exception) and not isinstance(
                    result,
                    (psycopg2.errors.SerializationFailure, ValidationError),
                ):
                    self.fail(
                        "unexpected exception from the race: %r\n%s"
                        % (result, getattr(result, "pwr_traceback", ""))
                    )

            session.invalidate_recordset()
            ended_revoked = bool(session.revoked_at)
            marked_is_live_payload = isinstance(marked, dict)

            if marked_is_live_payload and ended_revoked:
                bad_attempts.append(
                    (attempt, revoke_result, marked, ended_revoked)
                )
            outcomes[
                "not_revoked_and_dict"
                if marked_is_live_payload
                else "revoked_and_falsy_or_raised"
            ] += 1

        self.assertFalse(
            bad_attempts,
            "role marking returned a live payload for a session that ended "
            "up revoked in %d/%d attempts -- minor M1 is not fixed: %r"
            % (len(bad_attempts), _ROLE_MARKING_RACE_ATTEMPTS, bad_attempts),
        )
        self.assertEqual(
            sum(outcomes.values()), _ROLE_MARKING_RACE_ATTEMPTS
        )
