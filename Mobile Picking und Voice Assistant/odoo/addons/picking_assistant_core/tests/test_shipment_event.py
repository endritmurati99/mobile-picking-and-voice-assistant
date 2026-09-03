"""Der Envelope ist der Vertrag mit n8n: was hier fehlt, kann der Workflow
nicht entscheiden. Fingerprint-Regel wie bei quality.alert.event.builder."""
import hashlib
import json

from odoo.tests.common import TransactionCase


class TestShipmentEventBuilder(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "picking_assistant.instance_name", "lager1"
        )
        country = self.env.ref("base.at")
        self.partner = self.env["res.partner"].create(
            {
                "name": "Alpen Bau GmbH",
                "street": "Ringstrasse 5",
                "zip": "1010",
                "city": "Wien",
                "country_id": country.id,
            }
        )
        # Gewicht > 0.01 kg als Sicherheitsabstand: die Dezimalgenauigkeit
        # "Stock Weight" steht seit data/decimal_precision.xml zwar auf 3
        # Nachkommastellen in dieser Instanz, aber ein Wert deutlich ueber
        # der Rundungsgrenze macht den Test robust gegen die Standardgenauig-
        # keit (2 Nachkommastellen), falls decimal_precision.xml fehlt.
        self.product = self.env["product.product"].create(
            {"name": "Demo Klemmbaustein 2x4 rot", "default_code": "301121",
             "type": "consu", "is_storable": True, "weight": 0.05}
        )
        picking_type = self.env.ref("stock.picking_type_out")
        self.picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "partner_id": self.partner.id,
                "origin": "S00042",
                "location_id": picking_type.default_location_src_id.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                "move_ids": [(0, 0, {
                    "product_id": self.product.id,
                    "product_uom_qty": 4,
                    "product_uom": self.product.uom_id.id,
                    "location_id": picking_type.default_location_src_id.id,
                    "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                })],
            }
        )
        self.builder = self.env["shipment.event.builder"]

    def test_envelope_carries_recipient_items_and_weight(self):
        built = self.builder.build(self.picking)
        envelope = json.loads(built["envelope_text"])
        self.assertEqual(envelope["event_name"], "shipment.parcel.ready.v1")
        self.assertEqual(envelope["aggregate"]["model"], "stock.picking")
        self.assertEqual(envelope["aggregate"]["id"], self.picking.id)
        self.assertEqual(envelope["source"]["odoo_instance"], "lager1")
        payload = envelope["payload"]
        self.assertEqual(payload["recipient"]["country_code"], "AT")
        self.assertEqual(payload["recipient"]["city"], "Wien")
        self.assertEqual(payload["origin"], "S00042")
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["default_code"], "301121")
        self.assertEqual(payload["items"][0]["qty"], 4.0)
        self.assertAlmostEqual(payload["total_weight_kg"], 0.2, places=6)
        self.assertEqual(payload["job_id"], built["job_id"])
        self.assertEqual(
            set(payload["callback_ids_by_generation"]), {"1", "2", "3", "4", "5"}
        )

    def test_fingerprint_is_sha256_of_envelope_text(self):
        built = self.builder.build(self.picking)
        expected = hashlib.sha256(built["envelope_text"].encode("utf-8")).hexdigest()
        self.assertEqual(built["payload_fingerprint"], expected)

    def test_envelope_text_is_canonical_json(self):
        built = self.builder.build(self.picking)
        parsed = json.loads(built["envelope_text"])
        self.assertEqual(
            built["envelope_text"],
            json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        )

    def test_missing_partner_yields_empty_recipient(self):
        self.picking.partner_id = False
        payload = json.loads(self.builder.build(self.picking)["envelope_text"])["payload"]
        self.assertEqual(payload["recipient"]["name"], "")
        self.assertEqual(payload["recipient"]["country_code"], "")
