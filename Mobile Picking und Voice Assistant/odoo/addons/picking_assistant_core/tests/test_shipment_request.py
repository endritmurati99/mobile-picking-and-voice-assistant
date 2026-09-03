"""Buchung und Ereignis entstehen zusammen oder gar nicht (Transactional
Outbox). Zweiter Aufruf fuer dasselbe Picking wird abgewiesen."""
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase


class TestCompleteAndRequestLabel(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "picking_assistant.instance_name", "lager1"
        )
        self.api_user = self.env["res.users"].create(
            {
                "name": "Integrationsdienst",
                "login": "api_service_ship",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_user").id,
                    self.env.ref("stock.group_stock_manager").id,
                    self.env.ref("picking_assistant_integration.group_api_service").id,
                ])],
            }
        )
        self.partner = self.env["res.partner"].create(
            {"name": "Kundschaft Testfall", "street": "Musterweg 1",
             "zip": "12345", "city": "Musterstadt"}
        )
        self.product = self.env["product.product"].create(
            {"name": "Demo Achse 4M", "default_code": "343721",
             "type": "consu", "is_storable": True, "weight": 0.05}
        )
        picking_type = self.env.ref("stock.picking_type_out")
        src = picking_type.default_location_src_id
        self.env["stock.quant"]._update_available_quantity(self.product, src, 10)
        self.picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "partner_id": self.partner.id,
                "location_id": src.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                "move_ids": [(0, 0, {
                    "product_id": self.product.id,
                    "product_uom_qty": 2,
                    "product_uom": self.product.uom_id.id,
                    "location_id": src.id,
                    "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                })],
            }
        )
        self.picking.action_confirm()
        self.picking.action_assign()
        for line in self.picking.move_line_ids:
            line.quantity = line.quantity_product_uom or 2
            line.picked = True
        self.Picking = self.env["stock.picking"].with_user(self.api_user)
        self.internal_user = self.env["res.users"].create(
            {
                "name": "Lagerist ohne API-Rolle",
                "login": "lagerist_ship_guard",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_user").id,
                    self.env.ref("stock.group_stock_user").id,
                ])],
            }
        )

    def _outbox_rows(self):
        return self.env["picking.assistant.outbox"].sudo().search(
            [("job_record_id.aggregate_model", "=", "stock.picking"),
             ("job_record_id.aggregate_res_id", "=", self.picking.id)]
        )

    def test_books_the_picking_and_enqueues_exactly_one_event(self):
        result = self.Picking.api_complete_and_request_label(self.picking.id)
        self.assertTrue(result["picking_complete"])
        self.assertEqual(self.picking.state, "done")
        self.assertEqual(self.picking.shipping_label_status, "pending")
        rows = self._outbox_rows()
        self.assertEqual(len(rows), 1)
        job = rows.job_record_id
        self.assertEqual(job.job_type, "shipping_label")
        # event_name lebt auf der Outbox-Zeile, nicht auf dem Job-Datensatz
        # (siehe picking.assistant.integration.job._enqueue_job_event).
        self.assertEqual(rows.event_name, "shipment.parcel.ready.v1")
        self.assertEqual(job.job_id, result["job_id"])

    def test_second_call_is_refused_while_job_is_open(self):
        self.Picking.api_complete_and_request_label(self.picking.id)
        with self.assertRaises(ValidationError):
            self.Picking.api_complete_and_request_label(self.picking.id)
        self.assertEqual(len(self._outbox_rows()), 1)

    def test_requires_api_service_group(self):
        with self.assertRaises(AccessError):
            self.env["stock.picking"].with_user(
                self.internal_user
            ).api_complete_and_request_label(self.picking.id)

    def test_validate_failure_leaves_no_event_behind(self):
        # Ohne gepickte Menge weigert sich Odoo -- dann darf auch kein
        # Ereignis entstehen.
        for line in self.picking.move_line_ids:
            line.quantity = 0
            line.picked = False
        with self.assertRaises(Exception):
            self.Picking.api_complete_and_request_label(self.picking.id)
        self.assertEqual(len(self._outbox_rows()), 0)
        self.assertEqual(self.picking.shipping_label_status, "none")
