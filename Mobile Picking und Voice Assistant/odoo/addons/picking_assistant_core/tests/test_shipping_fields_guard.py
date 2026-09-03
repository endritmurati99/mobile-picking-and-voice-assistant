"""Die shipping_*-Felder sind das Ergebnis der Versandkette.

Jeder interne Nutzer darf ein Picking bearbeiten. Ohne Sperre koennte er per
ORM eine Sendungsnummer eintragen, die nie ein Workflow erzeugt hat.
"""
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestShippingFieldsGuard(TransactionCase):
    def setUp(self):
        super().setUp()
        self.picking_type = self.env.ref("stock.picking_type_out")
        self.picking = self.env["stock.picking"].sudo().create(
            {
                "picking_type_id": self.picking_type.id,
                "location_id": self.picking_type.default_location_src_id.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            }
        )
        self.internal_user = self.env["res.users"].create(
            {
                "name": "Lagerist ohne API-Rolle",
                "login": "lagerist_guard",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id,
                                     self.env.ref("stock.group_stock_user").id])],
            }
        )

    def test_defaults_are_empty(self):
        self.assertEqual(self.picking.shipping_label_status, "none")
        self.assertEqual(self.picking.integration_revision, 1)
        self.assertFalse(self.picking.shipping_tracking_number)

    def test_internal_user_cannot_write_shipping_fields(self):
        picking = self.picking.with_user(self.internal_user)
        with self.assertRaises(AccessError):
            picking.write({"shipping_tracking_number": "FAKE-1"})

    def test_internal_user_can_still_write_other_fields(self):
        picking = self.picking.with_user(self.internal_user)
        picking.write({"note": "normale Bearbeitung"})
        self.assertEqual(picking.note, "<p>normale Bearbeitung</p>")

    def test_superuser_may_write_shipping_fields(self):
        self.picking.sudo().write({"shipping_label_status": "pending"})
        self.assertEqual(self.picking.shipping_label_status, "pending")
