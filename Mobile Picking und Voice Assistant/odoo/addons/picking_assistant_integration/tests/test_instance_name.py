from odoo.exceptions import ValidationError

from .common import IntegrationCase


class TestInstanceName(IntegrationCase):
    def _mixin(self):
        return self.env["picking.assistant.api.mixin"]

    def _set(self, value):
        self.env["ir.config_parameter"].sudo().set_param(
            "picking_assistant.instance_name", value
        )

    def test_configured_name_is_returned(self):
        self._set("lager-2")
        self.assertEqual(self._mixin()._instance_name(), "lager-2")

    def test_surrounding_whitespace_is_stripped(self):
        self._set("  local  ")
        self.assertEqual(self._mixin()._instance_name(), "local")

    def test_missing_parameter_raises(self):
        self._set("")
        with self.assertRaisesRegex(ValidationError, "instance_name"):
            self._mixin()._instance_name()

    def test_invalid_characters_raise(self):
        self._set("Lager 2")
        with self.assertRaisesRegex(ValidationError, "instance_name"):
            self._mixin()._instance_name()
