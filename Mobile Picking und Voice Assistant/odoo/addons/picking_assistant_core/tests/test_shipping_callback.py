"""Ende der Versandkette: Callback wird zu Anhang und Feldern am Picking."""
from odoo.tests.common import TransactionCase


class TestShippingCallbackProjection(TransactionCase):
    def setUp(self):
        super().setUp()
        # `base.res_partner_2` existiert in dieser Test-DB nicht -- Partner
        # wird deshalb explizit angelegt statt per Demo-xmlid referenziert.
        partner = self.env["res.partner"].sudo().create({"name": "Kunde Testfall"})
        picking_type = self.env.ref("stock.picking_type_out")
        self.picking = self.env["stock.picking"].sudo().create(
            {
                "picking_type_id": picking_type.id,
                "partner_id": partner.id,
                "location_id": picking_type.default_location_src_id.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                "shipping_label_status": "pending",
            }
        )
        self.receipts = self.env["picking.assistant.callback.receipt"].sudo()

    def _result(self):
        return {
            "carrier_code": "DHL",
            "carrier_name": "DHL Paket",
            "tracking_number": "PWR-DHL-00066-4F7A",
            "service_note": "Standard, bis 2 kg",
            "label": {
                "picking_name": self.picking.name,
                "sender_name": "Lager 1",
                "recipient": {"name": "Kunde", "street": "Weg 1", "street2": "",
                              "zip": "10115", "city": "Berlin", "country_code": "DE"},
                "items": [{"default_code": "301121", "name": "Stein", "qty": 2.0,
                           "weight_kg": 0.003}],
                "total_weight_kg": 0.006,
            },
        }

    def _project(self, status="succeeded", result=None, error=None):
        return self.receipts._project_callback_result(
            aggregate_model="stock.picking",
            aggregate_res_id=self.picking.id,
            callback_name="shipping.label.status.v1",
            status=status,
            result=self._result() if result is None else result,
            error=error,
        )

    def test_succeeded_creates_attachment_and_fields(self):
        self.assertTrue(self._project())
        self.assertEqual(self.picking.shipping_label_status, "labeled")
        self.assertEqual(self.picking.shipping_carrier_code, "DHL")
        self.assertEqual(self.picking.shipping_tracking_number, "PWR-DHL-00066-4F7A")
        self.assertAlmostEqual(self.picking.shipping_weight_kg, 0.006)
        att = self.picking.shipping_label_attachment_id
        self.assertTrue(att)
        self.assertEqual(att.res_model, "stock.picking")
        self.assertEqual(att.res_id, self.picking.id)
        self.assertEqual(att.mimetype, "application/pdf")
        self.assertTrue(att.raw.startswith(b"%PDF"))
        self.assertTrue(self.picking.shipping_labeled_at)

    def test_failed_sets_reason_and_no_attachment(self):
        # Erst ein Erfolg, dann ein Fehlschlag: ein alter, gueltiger
        # Tracking-Code neben "Fehlgeschlagen" waere irrefuehrend -- alle
        # Versandfelder eines frueheren Erfolgs muessen mit dem Fehlschlag
        # verschwinden, inkl. Anhang.
        self.assertTrue(self._project())
        stale_attachment = self.picking.shipping_label_attachment_id
        self.assertTrue(stale_attachment)

        self.assertTrue(self._project(status="failed", result={},
                                      error={"message": "Carrier-Regel ohne Treffer"}))
        self.assertEqual(self.picking.shipping_label_status, "failed")
        self.assertEqual(self.picking.shipping_failure_reason, "Carrier-Regel ohne Treffer")
        self.assertFalse(self.picking.shipping_label_attachment_id)
        self.assertFalse(self.picking.shipping_carrier_code)
        self.assertFalse(self.picking.shipping_carrier_name)
        self.assertFalse(self.picking.shipping_tracking_number)
        self.assertEqual(self.picking.shipping_weight_kg, 0.0)
        self.assertFalse(self.picking.shipping_labeled_at)
        self.assertFalse(stale_attachment.exists())

    def test_second_success_replaces_attachment_instead_of_stacking(self):
        self._project()
        first = self.picking.shipping_label_attachment_id
        self._project()
        second = self.picking.shipping_label_attachment_id
        self.assertNotEqual(first.id, second.id)
        self.assertFalse(first.exists())
        count = self.env["ir.attachment"].sudo().search_count(
            [("res_model", "=", "stock.picking"), ("res_id", "=", self.picking.id),
             ("mimetype", "=", "application/pdf")]
        )
        self.assertEqual(count, 1)

    def test_running_status_does_not_touch_the_picking(self):
        self.assertFalse(self._project(status="running", result={}))
        self.assertEqual(self.picking.shipping_label_status, "pending")
