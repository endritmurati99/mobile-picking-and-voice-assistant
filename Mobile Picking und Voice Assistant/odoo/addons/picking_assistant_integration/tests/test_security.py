from odoo.exceptions import AccessError

from .common import IntegrationCase


class TestIntegrationSecurity(IntegrationCase):
    def test_picker_cannot_call_session_rpc_or_raw_crud(self):
        sessions = self.env["picking.assistant.session"].with_user(self.picker)
        with self.assertRaises(AccessError):
            sessions.api_get_session("0" * 64)
        with self.assertRaises(AccessError):
            sessions.create(
                {
                    "session_id": "session",
                    "token_hash": "0" * 64,
                    "csrf_hash": "1" * 64,
                    "user_id": self.picker.id,
                    "device_id": "device",
                    "roles_json": '["picker"]',
                    "expires_at": "2026-07-24 00:00:00",
                }
            )

    def test_api_user_can_call_rpc_but_cannot_raw_write(self):
        users = self.env["res.users"].with_user(self.api_user)
        principal = users.api_get_picker_principal(self.picker.id)
        self.assertEqual(principal["roles"], ["picker"])
        with self.assertRaises(AccessError):
            self.env["picking.assistant.session"].with_user(self.api_user).create({})
