"""Lego-Klemmbausteine wiegen wenige Gramm.

Die Odoo-Standardpraezision "Stock Weight" hat zwei Nachkommastellen; damit
wuerde jedes Gewicht unter 0,005 kg als 0,00 gespeichert und die
Gewichtssumme auf dem Versandlabel bliebe leer. Dieses Modul hebt die
Praezision per Datensatz-Override auf drei Nachkommastellen an
(data/decimal_precision.xml).
"""
from odoo.tests.common import TransactionCase


class TestDecimalPrecision(TransactionCase):
    def test_stock_weight_precision_is_three_digits(self):
        precision = self.env.ref("product.decimal_stock_weight")
        self.assertEqual(precision.digits, 3)

    def test_product_weight_below_two_digits_survives_roundtrip(self):
        product = self.env["product.product"].create(
            {
                "name": "Demo Klemmbaustein Praezisionstest",
                "type": "consu",
                "is_storable": True,
                "weight": 0.003,
            }
        )
        self.assertEqual(product.weight, 0.003)
