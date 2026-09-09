from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase


class TestMobileBatch(TransactionCase):
    def setUp(self):
        super().setUp()
        self.api_user = self.env["res.users"].create(
            {
                "name": "Batch API",
                "login": "batch_api",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_user").id,
                    self.env.ref("stock.group_stock_manager").id,
                    self.env.ref(
                        "picking_assistant_integration.group_api_service"
                    ).id,
                ])],
            }
        )
        self.internal_user = self.env["res.users"].create(
            {
                "name": "Batch Lagerist",
                "login": "batch_lagerist",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_user").id,
                    self.env.ref("stock.group_stock_user").id,
                ])],
            }
        )
        self.product = self.env["product.product"].create(
            {"name": "Batch Testprodukt", "type": "consu", "is_storable": True}
        )
        self.picking_type = self.env.ref("stock.picking_type_out")
        self.source = self.picking_type.default_location_src_id
        self.destination = self.env.ref("stock.stock_location_customers")
        self.env["stock.quant"]._update_available_quantity(
            self.product, self.source, 20
        )

    def _assigned_picking(self, name):
        picking = self.env["stock.picking"].create(
            {
                "name": name,
                "picking_type_id": self.picking_type.id,
                "location_id": self.source.id,
                "location_dest_id": self.destination.id,
                "move_ids": [(0, 0, {
                    "product_id": self.product.id,
                    "product_uom_qty": 1,
                    "product_uom": self.product.uom_id.id,
                    "location_id": self.source.id,
                    "location_dest_id": self.destination.id,
                })],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        self.assertEqual(picking.state, "assigned")
        return picking

    def test_api_creates_confirmed_batch_and_one_destination_package_per_picking(self):
        first = self._assigned_picking("BATCH/OUT/1")
        second = self._assigned_picking("BATCH/OUT/2")

        batch_id = self.env["stock.picking.batch"].with_user(
            self.api_user
        ).api_create_mobile_batch([second.id, first.id], self.api_user.id)

        batch = self.env["stock.picking.batch"].browse(batch_id)
        self.assertEqual(batch.state, "in_progress")
        self.assertEqual(batch.user_id, self.api_user)
        self.assertEqual(batch.picking_ids, first | second)
        packages = [
            picking.move_line_ids.result_package_id
            for picking in (first, second)
        ]
        self.assertTrue(all(packages))
        self.assertEqual(len({package.id for package in packages}), 2)
        self.assertTrue(packages[0].name.startswith("CLUSTER-B1/"))
        self.assertTrue(packages[1].name.startswith("CLUSTER-B2/"))

    def test_api_refuses_a_picking_that_was_batched_already(self):
        first = self._assigned_picking("BATCH/OUT/1")
        second = self._assigned_picking("BATCH/OUT/2")
        self.env["stock.picking.batch"].with_user(self.api_user).api_create_mobile_batch(
            [first.id, second.id], self.api_user.id
        )

        with self.assertRaises(ValidationError):
            self.env["stock.picking.batch"].with_user(
                self.api_user
            ).api_create_mobile_batch([first.id, second.id], self.api_user.id)

    def test_api_refuses_a_picking_with_an_active_mobile_claim(self):
        first = self._assigned_picking("BATCH/OUT/1")
        second = self._assigned_picking("BATCH/OUT/2")
        now = fields.Datetime.now()
        first.write(
            {
                "mobile_claim_user_id": self.internal_user.id,
                "mobile_claim_device_id": "active-device",
                "mobile_claimed_at": now,
                "mobile_claim_expires_at": now + timedelta(minutes=1),
            }
        )

        with self.assertRaises(ValidationError):
            self.env["stock.picking.batch"].with_user(
                self.api_user
            ).api_create_mobile_batch([first.id, second.id], self.api_user.id)

        self.assertFalse(first.batch_id)
        self.assertFalse(second.batch_id)

    def test_api_allows_an_expired_mobile_claim(self):
        first = self._assigned_picking("BATCH/OUT/1")
        second = self._assigned_picking("BATCH/OUT/2")
        now = fields.Datetime.now()
        first.write(
            {
                "mobile_claim_user_id": self.internal_user.id,
                "mobile_claim_device_id": "expired-device",
                "mobile_claimed_at": now - timedelta(minutes=2),
                "mobile_claim_expires_at": now - timedelta(minutes=1),
            }
        )

        batch_id = self.env["stock.picking.batch"].with_user(
            self.api_user
        ).api_create_mobile_batch([first.id, second.id], self.api_user.id)

        self.assertTrue(self.env["stock.picking.batch"].browse(batch_id).exists())

    def test_single_picking_claim_is_refused_after_batch_creation(self):
        first = self._assigned_picking("BATCH/OUT/1")
        second = self._assigned_picking("BATCH/OUT/2")
        self.env["stock.picking.batch"].with_user(
            self.api_user
        ).api_create_mobile_batch([first.id, second.id], self.api_user.id)

        result = self.env["stock.picking"].with_user(self.api_user).api_claim_mobile(
            first.id, self.internal_user.id, "single-device"
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "conflict")
        self.assertTrue(result["conflict"])
        self.assertFalse(first.mobile_claim_user_id)

    def test_api_requires_the_service_role(self):
        first = self._assigned_picking("BATCH/OUT/1")
        second = self._assigned_picking("BATCH/OUT/2")

        with self.assertRaises(AccessError):
            self.env["stock.picking.batch"].with_user(
                self.internal_user
            ).api_create_mobile_batch([first.id, second.id], self.internal_user.id)
