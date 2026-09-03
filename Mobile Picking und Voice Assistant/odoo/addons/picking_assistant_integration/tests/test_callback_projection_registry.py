"""Die Projektion ist eine Tabelle, keine harte Verdrahtung auf Quality.
Das Integrationsmodul kennt nur Namen; ob das Modell installiert ist,
entscheidet zur Laufzeit `env.get`."""
from odoo.tests.common import TransactionCase


class TestCallbackProjectionRegistry(TransactionCase):
    def setUp(self):
        super().setUp()
        self.receipts = self.env["picking.assistant.callback.receipt"].sudo()

    def test_registry_names_both_callbacks(self):
        self.assertEqual(
            self.receipts._PROJECTIONS,
            {
                "quality.assessment.status.v1": ("quality.alert.custom", "_apply_assessment"),
                "shipping.label.status.v1": ("stock.picking", "_apply_shipping_label"),
            },
        )

    def test_unknown_callback_name_is_ignored(self):
        self.assertFalse(
            self.receipts._project_callback_result(
                aggregate_model="stock.picking", aggregate_res_id=1,
                callback_name="something.else.v1", status="succeeded",
                result={}, error=None,
            )
        )

    def test_model_mismatch_is_ignored(self):
        self.assertFalse(
            self.receipts._project_callback_result(
                aggregate_model="res.partner", aggregate_res_id=1,
                callback_name="shipping.label.status.v1", status="succeeded",
                result={}, error=None,
            )
        )

    def test_legacy_name_still_works(self):
        # Alte Aufrufer und Tests nutzen den alten Namen weiter.
        self.assertFalse(
            self.receipts._project_quality_result(
                aggregate_model="res.partner", aggregate_res_id=1,
                callback_name="quality.assessment.status.v1", status="succeeded",
                result={}, error=None,
            )
        )
