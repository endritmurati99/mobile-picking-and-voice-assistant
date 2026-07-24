from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError

from .common import IntegrationCase


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
