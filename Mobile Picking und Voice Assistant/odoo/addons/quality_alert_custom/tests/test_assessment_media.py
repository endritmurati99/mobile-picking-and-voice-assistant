"""Die Fassade, ueber die das Backend an Meldefoto und Katalogbild kommt.

Sie haengt am JOB, nicht an einer mitgeschickten Alert-Kennung: wer den Alert
frei waehlen koennte, kaeme mit einer einzigen gueltigen Signatur an jedes
Foto im System.

Der Alert entsteht hier ueber `api_create_alert`, nicht von Hand. Nur so
entstehen Anhaenge, Job und Outbox-Zeile so, wie sie im Betrieb entstehen --
und genau darauf kommt es an: die Fassade muss die ZWEI Anhangzeilen je Foto
auseinanderhalten, die Odoo dabei anlegt.
"""
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

# 1x1 PNG. Kleinstmoegliches gueltiges Bild -- der Inhalt ist gleichgueltig,
# der Typ nicht: er ist bewusst NICHT JPEG, weil `api_create_alert` jedem
# Anhang hart "image/jpeg" anschreibt und die Leseseite genau das nicht
# glauben darf.
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)


class TestAssessmentMedia(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "picking_assistant.instance_name", "local"
        )
        self.product = self.env["product.product"].create({
            "name": "Pruefbaustein",
            "type": "consu",
        })
        self.product.product_tmpl_id.image_1920 = PNG_B64

    def _create_alert(self, photos=1):
        result = self.env["quality.alert.custom"].api_create_alert({
            "description": "Testmeldung",
            "priority": "1",
            "product_id": self.product.id,
            "photos": [
                {"filename": f"foto_{i}.png", "data_b64": PNG_B64}
                for i in range(photos)
            ],
        })
        alert = self.env["quality.alert.custom"].browse(result["alert_id"])
        job = self.env["picking.assistant.integration.job"].sudo().search([
            ("aggregate_model", "=", "quality.alert.custom"),
            ("aggregate_res_id", "=", alert.id),
        ], limit=1)
        return alert, job

    def _media(self, job):
        """Ruft die Fassade mit weggepatchter Lease-Pruefung.

        Gepatcht wird im TEST, nicht im Produktivcode: eine Umgehung ueber
        einen Kontextschluessel waere eine Hintertuer in genau der Pruefung,
        die den Zugriff eng haelt.
        """
        with patch.object(type(job), "_require_current_generation", return_value=None):
            return self.env["quality.alert.custom"].api_get_assessment_media(
                job.job_id, 1, "x" * 43
            )

    def test_unknown_job_is_refused(self):
        with self.assertRaises(ValidationError):
            self.env["quality.alert.custom"].api_get_assessment_media(
                "00000000-0000-4000-8000-000000000000", 1, "x" * 43
            )

    def test_media_is_returned_for_a_known_job(self):
        _alert, job = self._create_alert()
        result = self._media(job)
        self.assertEqual(len(result["photos"]), 1)
        self.assertEqual(result["photos"][0]["filename"], "foto_0.png")
        self.assertTrue(result["photos"][0]["data_b64"])
        self.assertEqual(result["photo_total"], 1)
        self.assertTrue(result["reference_image_b64"])
        self.assertIn("Pruefbaustein", result["product_label"])

    def test_field_attachment_is_not_counted_as_a_second_photo(self):
        """`api_create_alert` legt je Foto ZWEI ir.attachment-Zeilen an: die
        Ablage des Binaerfeldes `photo` (neu kodiert, nur eine) und die mit den
        urspruenglichen Bytes. Nur die zweite ist das Meldefoto."""
        _alert, job = self._create_alert()
        result = self._media(job)
        self.assertEqual(result["photo_total"], 1)
        self.assertEqual(len(result["photos"]), 1)

    def test_at_most_three_photos_but_the_total_is_honest(self):
        _alert, job = self._create_alert(photos=5)
        result = self._media(job)
        self.assertEqual(len(result["photos"]), 3)
        self.assertEqual(result["photo_total"], 5)

    def test_missing_catalogue_image_is_not_an_error(self):
        """23 von 70 Produkten haben kein Bild. Der Artikelabgleich entfaellt
        dann, die Schadenspruefung laeuft trotzdem."""
        self.product.product_tmpl_id.image_1920 = False
        _alert, job = self._create_alert()
        result = self._media(job)
        self.assertFalse(result["reference_image_b64"])
        self.assertEqual(len(result["photos"]), 1)

    def test_stored_mimetype_matches_the_bytes(self):
        """Vorher stand hier hart "image/jpeg", auch fuer PNG. Der Wert wird
        von der Leseseite nicht geglaubt, aber ein falscher Wert in der
        Datenbank fuehrt irgendwann jemanden in die Irre."""
        alert, _job = self._create_alert()
        attachment = self.env["ir.attachment"].sudo().search([
            ("res_model", "=", "quality.alert.custom"),
            ("res_id", "=", alert.id),
            ("res_field", "=", False),
        ], limit=1)
        self.assertEqual(attachment.mimetype, "image/png")
