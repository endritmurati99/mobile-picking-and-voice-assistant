"""Die Projektion am Ende der Kette.

Ohne sie endet ein Callback im Integrationslayer: Job und Receipt waeren
vollstaendig, der fachliche Datensatz saehe aber unveraendert aus -- die
Bewertung waere technisch angekommen und fachlich unsichtbar.
"""
from odoo.tests.common import TransactionCase


class TestCallbackProjection(TransactionCase):
    def setUp(self):
        super().setUp()
        self.alert = self.env["quality.alert.custom"].create(
            {"description": "Karton zerdrueckt", "ai_evaluation_status": "pending"}
        )
        self.receipts = self.env["picking.assistant.callback.receipt"].sudo()

    def _project(self, **overrides):
        values = {
            "aggregate_model": self.alert._name,
            "aggregate_res_id": self.alert.id,
            "callback_name": "quality.assessment.status.v1",
            "status": "succeeded",
            "result": {
                "disposition": "scrap",
                "confidence": 0.9,
                "provider": "ollama-local",
                "model": "qwen2.5:7b",
            },
            "error": None,
        }
        values.update(overrides)
        return self.receipts._project_quality_result(**values)

    def test_terminal_quality_callback_writes_the_alert(self):
        self.assertTrue(self._project())
        self.assertEqual(self.alert.ai_evaluation_status, "completed")
        self.assertEqual(self.alert.ai_disposition, "scrap")
        self.assertEqual(self.alert.ai_provider, "ollama-local")

    def test_foreign_callback_name_is_ignored(self):
        self.assertFalse(self._project(callback_name="shipping.label.status.v1"))
        self.assertEqual(self.alert.ai_evaluation_status, "pending")

    def test_running_status_does_not_project(self):
        self.assertFalse(self._project(status="running", result={}))
        self.assertEqual(self.alert.ai_evaluation_status, "pending")

    def test_foreign_aggregate_model_is_ignored(self):
        self.assertFalse(self._project(aggregate_model="res.partner"))
        self.assertEqual(self.alert.ai_evaluation_status, "pending")

    def test_missing_record_is_ignored_instead_of_raising(self):
        self.assertFalse(self._project(aggregate_res_id=999999))

    def test_review_required_reaches_the_alert_without_a_verdict(self):
        self.assertTrue(
            self._project(
                status="review_required",
                result={},
                error={"code": "llm_unavailable", "message": "Timeout"},
            )
        )
        self.assertEqual(self.alert.ai_evaluation_status, "review_required")
        self.assertFalse(self.alert.ai_disposition)
