import hashlib
import json

from .common import QualityApiCase


class TestAlertEnqueuesEvent(QualityApiCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "picking_assistant.instance_name", "local"
        )
        # Die Zeilen, die VOR diesem Test schon da waren. Ohne diese Abgrenzung
        # behaupten die Tests unten eine leere Outbox -- das gilt in einer
        # frischen Testdatenbank und sonst nie. Gegen `masterfischer_o19` mit
        # echten Zeilen liefen sie deshalb immer rot, und rote Tests, die man
        # gewohnheitsmaessig uebergeht, sind schlimmer als gar keine.
        self._preexisting = set(
            self.env["picking.assistant.outbox"].sudo().search([]).ids
        )

    def _create(self, description="Karton zerdrueckt"):
        return self.api_env["quality.alert.custom"].api_create_alert(
            {"description": description, "priority": "1"}
        )

    def _outbox(self):
        """Nur die Zeilen, die DIESER Test erzeugt hat."""
        rows = self.env["picking.assistant.outbox"].sudo().search([])
        return rows.filtered(lambda row: row.id not in self._preexisting)

    def test_one_alert_creates_exactly_one_outbox_row(self):
        self._create()
        rows = self._outbox()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.event_name, "quality.assessment.requested.v1")
        self.assertEqual(rows.state, "pending")

    def test_outbox_fingerprint_matches_the_stored_envelope(self):
        self._create()
        row = self._outbox()
        self.assertEqual(
            row.payload_fingerprint,
            hashlib.sha256(row.envelope_text.encode("utf-8")).hexdigest(),
        )

    def test_envelope_points_at_the_created_alert(self):
        result = self._create()
        envelope = json.loads(self._outbox().envelope_text)
        self.assertEqual(envelope["aggregate"]["id"], result["alert_id"])
        self.assertEqual(envelope["payload"]["alert_id"], result["alert_id"])

    def test_alert_starts_pending(self):
        result = self._create()
        alert = self.env["quality.alert.custom"].browse(result["alert_id"])
        self.assertEqual(alert.ai_evaluation_status, "pending")

    def test_rollback_removes_alert_and_event_together(self):
        with self.assertRaisesRegex(RuntimeError, "force rollback"):
            with self.env.cr.savepoint():
                self._create("wird zurueckgerollt")
                raise RuntimeError("force rollback")
        self.env.invalidate_all()
        self.assertFalse(
            self.env["quality.alert.custom"].search(
                [("description", "=", "wird zurueckgerollt")]
            )
        )
        self.assertFalse(self._outbox())
