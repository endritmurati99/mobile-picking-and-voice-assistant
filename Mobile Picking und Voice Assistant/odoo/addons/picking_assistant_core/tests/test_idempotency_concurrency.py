"""The idempotency reservation race, on two real transactions.

A single-cursor test structurally cannot reproduce this: both "concurrent"
reservations would run inside one transaction, see each other's uncommitted
rows, and never contend for the unique index. The bug this file exists for is
only visible across two connections, and it has TWO halves:

1. the loser must receive a NAMED answer, never a raw `psycopg2.UniqueViolation`
   leaking out as a 500;
2. the loser's own transaction must SURVIVE. The pre-Task-12 implementation
   called `self.env.cr.rollback()` on the collision, which threw away every
   unrelated write the caller had already made in that transaction. That is
   invisible to any test that does nothing else in the losing transaction --
   so this one deliberately writes a marker first and asserts it is still
   there afterwards.

Note on the retry that is NOT here: re-SELECTing after the IntegrityError
cannot work. Odoo runs REPEATABLE READ, so the winner's row was committed after
this transaction's snapshot was taken and is invisible to it -- the same trap
that leaked a raw UniqueViolation out of the webhook-nonce path in lane R2. The
collision is therefore classified from the constraint name on the exception
itself, which needs no second look at the table.
"""

from uuid import uuid4

import psycopg2

from odoo.tests.common import tagged

from odoo.addons.picking_assistant_integration.tests.concurrency_common import (
    CommittedConcurrencyCase,
)

ENDPOINT = "confirm-line"


@tagged("post_install", "-at_install")
class TestIdempotencyReservationRace(CommittedConcurrencyCase):
    def _reserve(self, env, key, scope, fingerprint="a" * 64):
        return (
            env["picking.assistant.idempotency"]
            .with_user(self.api_user_id)
            .api_reserve_request(ENDPOINT, key, fingerprint, scope)
        )

    def _entries(self, key):
        return self.env["picking.assistant.idempotency"].search(
            [("endpoint", "=", ENDPOINT), ("key", "=", key)]
        )

    def test_two_transactions_reserving_the_same_key_produce_one_winner(self):
        key = "race-%s" % uuid4().hex
        results = self.run_concurrently(
            lambda env: self._reserve(env, key, "user:7"),
            lambda env: self._reserve(env, key, "user:7"),
        )

        for result in results:
            self.assertNotIsInstance(
                result,
                psycopg2.Error,
                "a raw driver error reached the caller instead of a named "
                "answer:\n%s" % getattr(result, "pwr_traceback", ""),
            )
            self.assertIsInstance(
                result,
                dict,
                "unexpected result %r:\n%s"
                % (result, getattr(result, "pwr_traceback", "")),
            )

        statuses = sorted(result["status"] for result in results)
        self.assertEqual(
            statuses,
            ["pending", "reserved"],
            "exactly one transaction must win the key; got %r" % (statuses,),
        )
        loser = next(r for r in results if r["status"] == "pending")
        self.assertEqual(loser["status_code"], 409)

        entries = self._entries(key)
        self.track(entries)
        self.assertEqual(
            len(entries), 1, "the unique index must leave exactly one row"
        )

    def test_the_loser_keeps_the_rest_of_its_transaction(self):
        """The collision must not roll the caller's own work back.

        The marker is an unrelated row written in the SAME transaction before
        the losing reservation. `cr.rollback()` on the collision path -- what
        the pre-Task-12 code did -- takes it with it.
        """
        key = "race-%s" % uuid4().hex
        marker_key = "marker-%s" % uuid4().hex
        seen = {}

        def winner(env):
            return self._reserve(env, key, "user:7")

        def loser(env):
            marker = self._reserve(env, marker_key, "user:9")
            seen["marker_id"] = marker["entry_id"]
            outcome = self._reserve(env, key, "user:7")
            model = env["picking.assistant.idempotency"]
            seen["marker_alive_in_txn"] = bool(
                model.browse(marker["entry_id"]).exists()
            )
            return outcome

        results = self.run_concurrently(winner, loser)
        for result in results:
            self.assertIsInstance(
                result,
                dict,
                "unexpected result %r:\n%s"
                % (result, getattr(result, "pwr_traceback", "")),
            )

        self.assertTrue(
            seen.get("marker_alive_in_txn"),
            "the collision rolled back the caller's own earlier write",
        )

        marker = self.env["picking.assistant.idempotency"].browse(seen["marker_id"])
        self.track(marker.exists())
        self.track(self._entries(key))
        self.assertTrue(
            marker.exists(),
            "the marker did not survive the commit, so the losing "
            "transaction was rolled back after all",
        )
