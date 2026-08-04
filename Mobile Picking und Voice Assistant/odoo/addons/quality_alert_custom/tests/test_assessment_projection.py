from odoo.tests.common import TransactionCase

RESULT = {
    "disposition": "scrap",
    "confidence": 0.95,
    "summary": "Kartons zerdrueckt, Ware unbrauchbar.",
    "recommended_action": "Artikel sperren.",
    "provider": "ollama-local",
    "model": "qwen2.5:7b",
}


class TestAssessmentProjection(TransactionCase):
    def _alert(self):
        return self.env["quality.alert.custom"].create(
            {"description": "Karton zerdrueckt", "ai_evaluation_status": "pending"}
        )

    def test_success_writes_the_verdict(self):
        alert = self._alert()
        alert.api_apply_assessment("succeeded", RESULT, None)
        self.assertEqual(alert.ai_evaluation_status, "completed")
        self.assertEqual(alert.ai_disposition, "scrap")
        self.assertEqual(alert.ai_confidence, 0.95)
        self.assertEqual(alert.ai_provider, "ollama-local")
        self.assertEqual(alert.ai_model, "qwen2.5:7b")
        self.assertTrue(alert.ai_last_analyzed_at)

    def test_review_required_writes_no_verdict(self):
        alert = self._alert()
        alert.api_apply_assessment(
            "review_required", {}, {"code": "llm_unavailable", "message": "Timeout"}
        )
        self.assertEqual(alert.ai_evaluation_status, "review_required")
        self.assertFalse(alert.ai_disposition)
        self.assertFalse(alert.ai_confidence)
        self.assertEqual(alert.ai_failure_reason, "Timeout")

    def test_failed_writes_no_verdict(self):
        alert = self._alert()
        alert.api_apply_assessment("failed", {}, {"message": "Odoo weg"})
        self.assertEqual(alert.ai_evaluation_status, "failed")
        self.assertFalse(alert.ai_disposition)

    def test_projection_does_not_raise_the_revision(self):
        alert = self._alert()
        before = alert.integration_revision
        alert.api_apply_assessment("succeeded", RESULT, None)
        self.assertEqual(alert.integration_revision, before)

    def test_unknown_status_is_refused(self):
        from odoo.exceptions import ValidationError

        alert = self._alert()
        with self.assertRaises(ValidationError):
            alert.api_apply_assessment("erfunden", RESULT, None)
