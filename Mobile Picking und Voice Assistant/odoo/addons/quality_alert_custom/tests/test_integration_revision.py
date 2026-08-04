from odoo.tests.common import TransactionCase


class TestIntegrationRevision(TransactionCase):
    def _alert(self):
        return self.env["quality.alert.custom"].create(
            {"description": "Karton eingedrueckt", "priority": "1"}
        )

    def test_new_alert_starts_at_revision_one(self):
        self.assertEqual(self._alert().integration_revision, 1)

    def test_description_change_raises_revision(self):
        alert = self._alert()
        alert.write({"description": "Karton zerdrueckt, Ware nass"})
        self.assertEqual(alert.integration_revision, 2)

    def test_unrelated_change_keeps_revision(self):
        alert = self._alert()
        alert.write({"ai_summary": "egal"})
        self.assertEqual(alert.integration_revision, 1)

    def test_explicit_revision_is_not_double_counted(self):
        alert = self._alert()
        alert.write({"description": "neu", "integration_revision": 7})
        self.assertEqual(alert.integration_revision, 7)
