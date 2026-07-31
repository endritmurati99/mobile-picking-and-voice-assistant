"""Scoped idempotency (Foundation Task 12).

The property under test is that an Idempotency-Key belongs to a PRINCIPAL, not
to the endpoint. Before this task two different authenticated users sending the
same key to the same endpoint collided: the second one was answered with the
first one's reservation. The scope is supplied by the server from the
authenticated session and can never be taken from a request body or header.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged

API_SERVICE_GROUP = "picking_assistant_integration.group_api_service"
PICKER_GROUP = "picking_assistant_integration.group_picker"


@tagged("post_install", "-at_install")
class TestScopedIdempotency(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.api_user = new_test_user(
            cls.env,
            login="core_api",
            groups="base.group_user,%s" % API_SERVICE_GROUP,
        )
        cls.picker = new_test_user(
            cls.env,
            login="core_picker",
            groups="base.group_user,%s" % PICKER_GROUP,
        )

    def model(self, user=None):
        return self.env["picking.assistant.idempotency"].with_user(
            user or self.api_user
        )

    # ------------------------------------------------------------------
    # The API guard
    # ------------------------------------------------------------------

    def test_picker_cannot_call_public_reservation_method(self):
        with self.assertRaises(AccessError):
            self.model(self.picker).api_reserve_request(
                "confirm-line", "same-key", "a" * 64, "user:7"
            )

    def test_picker_cannot_call_finalize_or_abort(self):
        reserved = self.model().api_reserve_request(
            "confirm-line", "guard-key", "a" * 64, "user:7"
        )
        entry_id = reserved["entry_id"]
        with self.assertRaises(AccessError):
            self.model(self.picker).api_finalize_request(entry_id, "user:7", {"ok": 1})
        with self.assertRaises(AccessError):
            self.model(self.picker).api_abort_request(entry_id, "user:7")

    # ------------------------------------------------------------------
    # The scope itself
    # ------------------------------------------------------------------

    def test_same_key_is_independent_between_principal_scopes(self):
        model = self.model()
        first = model.api_reserve_request("confirm-line", "same-key", "a" * 64, "user:7")
        second = model.api_reserve_request(
            "confirm-line", "same-key", "a" * 64, "user:8"
        )
        self.assertEqual(first["status"], "reserved")
        self.assertEqual(second["status"], "reserved")
        self.assertNotEqual(first["entry_id"], second["entry_id"])

    def test_a_missing_or_legacy_scope_is_refused(self):
        model = self.model()
        for scope in (False, "", "legacy"):
            with self.assertRaises(ValidationError):
                model.api_reserve_request("confirm-line", "k", "a" * 64, scope)

    def test_same_scope_key_with_different_fingerprint_conflicts(self):
        model = self.model()
        model.api_reserve_request("confirm-line", "same-key", "a" * 64, "user:7")
        conflict = model.api_reserve_request(
            "confirm-line", "same-key", "b" * 64, "user:7"
        )
        self.assertEqual(conflict["status"], "conflict")
        self.assertEqual(conflict["status_code"], 409)

    def test_a_completed_entry_replays_its_recorded_response(self):
        model = self.model()
        reserved = model.api_reserve_request(
            "confirm-line", "replay-key", "a" * 64, "user:7"
        )
        model.api_finalize_request(
            reserved["entry_id"], "user:7", {"picking_id": 42}, 201
        )
        replay = model.api_reserve_request(
            "confirm-line", "replay-key", "a" * 64, "user:7"
        )
        self.assertEqual(replay["status"], "replay")
        self.assertEqual(replay["status_code"], 201)
        self.assertEqual(replay["response_payload"], {"picking_id": 42})

    def test_a_reservation_still_running_answers_pending(self):
        model = self.model()
        model.api_reserve_request("confirm-line", "busy-key", "a" * 64, "user:7")
        again = model.api_reserve_request(
            "confirm-line", "busy-key", "a" * 64, "user:7"
        )
        self.assertEqual(again["status"], "pending")
        self.assertEqual(again["status_code"], 409)

    # ------------------------------------------------------------------
    # Finalize and abort are scope-bound too
    # ------------------------------------------------------------------

    def test_finalize_refuses_a_foreign_scope(self):
        model = self.model()
        reserved = model.api_reserve_request(
            "confirm-line", "mine", "a" * 64, "user:7"
        )
        with self.assertRaises(ValidationError):
            model.api_finalize_request(reserved["entry_id"], "user:8", {"ok": 1})

    def test_abort_refuses_a_foreign_scope(self):
        model = self.model()
        reserved = model.api_reserve_request(
            "confirm-line", "mine-too", "a" * 64, "user:7"
        )
        with self.assertRaises(ValidationError):
            model.api_abort_request(reserved["entry_id"], "user:8")
        # and the entry survives the refusal
        self.assertTrue(
            self.env["picking.assistant.idempotency"]
            .browse(reserved["entry_id"])
            .exists()
        )

    def test_abort_releases_the_key_for_the_same_scope(self):
        model = self.model()
        first = model.api_reserve_request("confirm-line", "retry", "a" * 64, "user:7")
        model.api_abort_request(first["entry_id"], "user:7")
        second = model.api_reserve_request("confirm-line", "retry", "b" * 64, "user:7")
        self.assertEqual(second["status"], "reserved")

    # ------------------------------------------------------------------
    # Expiry
    # ------------------------------------------------------------------

    def test_expired_row_is_reused_without_transaction_rollback(self):
        model = self.model()
        first = model.api_reserve_request(
            "confirm-line", "same-key", "a" * 64, "user:7", ttl_seconds=1
        )
        entry = self.env["picking.assistant.idempotency"].browse(first["entry_id"])
        entry.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        second = model.api_reserve_request(
            "confirm-line", "same-key", "b" * 64, "user:7"
        )
        self.assertEqual(second["status"], "reserved")
        self.assertEqual(second["entry_id"], first["entry_id"])
        self.assertEqual(entry.request_fingerprint, "b" * 64)

    def test_reusing_an_expired_row_clears_the_previous_response(self):
        """A stale reply must never be handed to the new reservation."""
        model = self.model()
        first = model.api_reserve_request(
            "confirm-line", "stale", "a" * 64, "user:7"
        )
        model.api_finalize_request(first["entry_id"], "user:7", {"old": True}, 201)
        entry = self.env["picking.assistant.idempotency"].browse(first["entry_id"])
        entry.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        model.api_reserve_request("confirm-line", "stale", "b" * 64, "user:7")
        self.assertEqual(entry.state, "pending")
        self.assertFalse(entry.response_payload)
        self.assertFalse(entry.processed_at)
        self.assertEqual(entry.status_code, 200)

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    def test_the_cron_deletes_only_expired_entries(self):
        model = self.model()
        live = model.api_reserve_request("confirm-line", "live", "a" * 64, "user:7")
        dead = model.api_reserve_request("confirm-line", "dead", "a" * 64, "user:8")
        records = self.env["picking.assistant.idempotency"]
        records.browse(dead["entry_id"]).expires_at = fields.Datetime.now() - timedelta(
            seconds=1
        )
        processed = records._cron_cleanup_expired()
        self.assertEqual(processed, 1)
        self.assertFalse(records.browse(dead["entry_id"]).exists())
        self.assertTrue(records.browse(live["entry_id"]).exists())

    def test_the_cron_reports_the_remainder_it_did_not_reach(self):
        """A GC that silently truncates reads as 'nothing left to do'."""
        model = self.model()
        records = self.env["picking.assistant.idempotency"]
        stale = fields.Datetime.now() - timedelta(seconds=1)
        for index in range(3):
            entry = model.api_reserve_request(
                "confirm-line", "gc-%s" % index, "a" * 64, "user:%s" % index
            )
            records.browse(entry["entry_id"]).expires_at = stale

        reported = []
        job_model = self.env["picking.assistant.integration.job"]
        self.patch(
            type(job_model),
            "_report_cron_progress",
            lambda self, processed, remaining=0: reported.append((processed, remaining)),
        )
        processed = records._cron_cleanup_expired(limit=2)
        self.assertEqual(processed, 2)
        self.assertEqual(reported, [(2, 1)])
