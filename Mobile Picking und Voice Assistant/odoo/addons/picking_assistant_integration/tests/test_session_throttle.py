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

        Under Odoo's REPEATABLE READ (Task 3), eight workers started
        together on a barrier and contending for the SAME row's `FOR UPDATE`
        lock can structurally produce at most ONE clean completion per
        round: every worker's snapshot is taken at (essentially) the same
        moment, so whichever worker loses the lock wakes up to find its own
        snapshot already stale against the winner's commit and gets
        `SerializationFailure` (SQLSTATE 40001), not a delayed look at the
        updated row -- there is no in-process retry here the way Odoo's own
        `retrying()` RPC wrapper would provide in production. That makes
        `len(allowed) <= 5` true in every run regardless of whether the
        in-flight counting guard is even wired up correctly; it is a smoke
        test for "no crash under real concurrent load", not a discriminating
        proof of the 5-slot budget. The budget itself is what
        `test_an_abandoned_attempt_stops_counting_after_the_ttl` proves,
        sequentially and deterministically, on a single cursor where the
        REPEATABLE READ restriction above does not apply -- confirmed by a
        negative control breaking the same guard condition (see this task's
        report).
        """
        login_key, ip_key = "picker@example.com", "hmac-value"
        api_user_id = self.api_user_id

        results = self.run_concurrently(
            *[
                (lambda env, api_user_id=api_user_id: env["picking.assistant.auth.throttle"]
                    .with_user(api_user_id)
                    .api_begin_login_attempt(login_key, ip_key))
                for _ in range(8)
            ]
        )

        type_errors = [r for r in results if isinstance(r, TypeError)]
        self.assertEqual(
            type_errors,
            [],
            "in-flight reservation must never surface a raw TypeError:\n%s"
            % "\n".join(getattr(r, "pwr_traceback", "") for r in results),
        )
        allowed = [r for r in results if isinstance(r, dict) and r["allowed"]]
        self.assertLessEqual(len(allowed), 5, "in-flight attempts must count against the limit")

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

    def test_nonce_style_constraint_name_matches_the_database(self):
        """`_lock_or_create` classifies a cross-transaction row-creation
        race by constraint name (mandatory addition, escalated from Task 3's
        re-review). If Odoo ever renames the constraint, the name check
        silently stops matching and a raw `TypeError` on `browse(None)`
        returns -- a 500 instead of a transparent retry, and only under
        concurrency, so nothing else in the suite would notice."""
        from odoo.addons.picking_assistant_integration.models.auth_throttle import (
            THROTTLE_UNIQUE_CONSTRAINT,
        )

        self.cr.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'picking_assistant_auth_throttle'::regclass "
            "AND contype = 'u'"
        )
        self.assertIn(
            THROTTLE_UNIQUE_CONSTRAINT, [row[0] for row in self.cr.fetchall()]
        )

    def test_concurrent_row_creation_never_raises_a_raw_typeerror(self):
        """Mandatory addition escalated from Task 3's re-review:
        `_lock_or_create`'s `except IntegrityError` branch used to re-SELECT
        `FOR UPDATE` after a losing INSERT. Under Odoo's REPEATABLE READ that
        re-SELECT runs on the loser's original (pre-commit) snapshot, finds
        nothing, and `browse(row[0])` on `row = None` raised a raw
        `TypeError: 'NoneType' object is not subscriptable` -- which Odoo's
        `retrying()` RPC wrapper does not retry, because it is not a
        serialization or deadlock failure.

        This needs two real transactions creating the SAME (login_key,
        source_ip_hmac) row for the first time: on one cursor the loser's
        `SELECT ... FOR UPDATE` sees its own uncommitted INSERT and the
        `IntegrityError` branch is never reached at all.

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
                    "retryable SerializationFailure, not %r -- Odoo's "
                    "retrying() wrapper only retries that class, so anything "
                    "else surfaces to the caller instead of transparently "
                    "retrying with a fresh snapshot" % (loser,),
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
