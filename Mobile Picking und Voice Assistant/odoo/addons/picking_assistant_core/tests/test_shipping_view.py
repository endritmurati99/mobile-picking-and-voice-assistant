"""Regressionsschutz fuer den Reiter "Versand" am Lieferschein-Formular.

Ohne diesen Test koennte ein spaeterer Refactor den Reiter oder das
Tracking-Feld aus der Ansicht entfernen, ohne dass eine Testsuite es
bemerkt - die Felder aus Task 1 waeren dann fuer den Nutzer unsichtbar.
"""
from odoo.tests.common import TransactionCase


class TestShippingView(TransactionCase):
    def test_form_view_has_shipping_tab(self):
        view = self.env["stock.picking"].get_view(view_type="form")
        arch = view["arch"]
        self.assertIn('name="shipping_label"', arch)
        self.assertIn("shipping_tracking_number", arch)
