"""Die festgeschriebene SOLL-Beschreibung eines Artikels.

Sie existiert, weil das Bildmodell das Katalogbild von `[6023350] Brick 2x2x2
R=15 gelb` an drei Tagen wortgleich als "plastic corner protector, yellow,
cube with rounded top" beschrieb -- QA/0227, QA/0233, QA/0234. Ein
Duplo-Stein ist kein Eckenschutz, und derselbe Aufruf auf demselben Bild
liefert immer dasselbe Wort: dagegen hilft nur, den Satz einmal durchsehen zu
lassen und danach stehen zu lassen.

Die Pruefsumme ist der Kern der Sache und nicht Beiwerk. Ein geprueft
aussehender Satz ueber ein Bild, das inzwischen ein anderes ist, waere
schlimmer als gar keiner.
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase

# 1x1 PNG, und weiter unten ein zweites, anderes Bild -- der Bildwechsel ist
# der Fall, den die Pruefsumme abfangen muss.
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)
PNG_ROT_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z/C/HgAGgwJ/lK3Q"
    "6wAAAABJRU5ErkJggg=="
)

SOLL = "toy building brick, yellow, 2x2 studs with rounded top"


class TestReferenceDescription(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "picking_assistant.instance_name", "local"
        )
        self.product = self.env["product.product"].create({
            "name": "Pruefbaustein",
            "type": "consu",
        })
        self.template = self.product.product_tmpl_id
        self.template.image_1920 = PNG_B64

    # -- Setzen und Zuruecknehmen ------------------------------------------

    def test_setting_a_description_stamps_the_current_image(self):
        self.env["product.template"].api_set_reference_description(
            self.template.id, SOLL
        )
        self.assertEqual(self.template.ai_reference_description, SOLL)
        self.assertEqual(
            self.template.ai_reference_image_sha1,
            self.template._ai_reference_checksum(),
        )
        self.assertFalse(self.template.ai_reference_reviewed)

    def test_a_description_can_be_marked_as_reviewed(self):
        self.env["product.template"].api_set_reference_description(
            self.template.id, SOLL, reviewed=True
        )
        self.assertTrue(self.template.ai_reference_reviewed)

    def test_an_empty_description_clears_everything(self):
        """Zuruecknehmen muss so einfach sein wie Setzen -- sonst bleibt eine
        falsche Beschreibung stehen, weil das Loeschen umstaendlich ist."""
        self.env["product.template"].api_set_reference_description(
            self.template.id, SOLL, reviewed=True
        )
        self.env["product.template"].api_set_reference_description(
            self.template.id, "  "
        )
        self.assertFalse(self.template.ai_reference_description)
        self.assertFalse(self.template.ai_reference_image_sha1)
        self.assertFalse(self.template.ai_reference_reviewed)

    # -- Die Pruefsumme ----------------------------------------------------

    def test_the_description_is_delivered_while_the_image_is_unchanged(self):
        self.env["product.template"].api_set_reference_description(
            self.template.id, SOLL
        )
        self.assertEqual(self.template.ai_reference_description_if_current(), SOLL)

    def test_a_changed_catalogue_image_silences_the_description(self):
        """Der Fall, gegen den die Pruefsumme steht: jemand tauscht das
        Katalogbild, der alte Satz beschriebe ein Bild, das es nicht mehr
        gibt."""
        self.env["product.template"].api_set_reference_description(
            self.template.id, SOLL, reviewed=True
        )
        self.template.image_1920 = PNG_ROT_B64
        self.assertEqual(self.template.ai_reference_description_if_current(), "")
        # Das Feld selbst bleibt stehen: der Text ist Arbeit eines Menschen und
        # wird nicht stillschweigend geloescht, nur nicht mehr benutzt.
        self.assertEqual(self.template.ai_reference_description, SOLL)

    def test_a_product_without_an_image_may_still_carry_a_description(self):
        """23 von 70 Artikeln haben kein Katalogbild; fuer sie fiel der
        Abgleich bisher still aus. Ohne Bild ist die Pruefsumme leer, und leer
        gegen leer ist ein gueltiger Vergleich."""
        self.template.image_1920 = False
        self.env["product.template"].api_set_reference_description(
            self.template.id, SOLL, reviewed=True
        )
        self.assertFalse(self.template.ai_reference_image_sha1)
        self.assertEqual(self.template.ai_reference_description_if_current(), SOLL)

    def test_a_description_written_past_the_api_is_not_delivered(self):
        """Direktes `write` setzt keine Pruefsumme. Ein Satz ohne Summe gilt
        nicht -- sonst waere die Summe umgehbar und damit wertlos."""
        self.template.write({"ai_reference_description": SOLL})
        self.assertEqual(self.template.ai_reference_description_if_current(), "")

    # -- Der Weg zur Bewertungskette ---------------------------------------

    def _media_for_alert(self):
        result = self.env["quality.alert.custom"].api_create_alert({
            "description": "Testmeldung",
            "priority": "1",
            "product_id": self.product.id,
            "photos": [{"filename": "foto.png", "data_b64": PNG_B64}],
        })
        alert = self.env["quality.alert.custom"].browse(result["alert_id"])
        job = self.env["picking.assistant.integration.job"].sudo().search([
            ("aggregate_model", "=", "quality.alert.custom"),
            ("aggregate_res_id", "=", alert.id),
        ], limit=1)
        with patch.object(type(job), "_require_current_generation", return_value=None):
            return self.env["quality.alert.custom"].api_get_assessment_media(
                job.job_id, 1, "x" * 43
            )

    def test_the_media_facade_hands_the_description_to_the_chain(self):
        self.env["product.template"].api_set_reference_description(
            self.template.id, SOLL, reviewed=True
        )
        media = self._media_for_alert()
        self.assertEqual(media["reference_description"], SOLL)
        # Das Bild reist trotzdem mit: die Kette faellt darauf zurueck, sobald
        # die Beschreibung nicht mehr gilt.
        self.assertTrue(media["reference_image_b64"])

    def test_the_media_facade_stays_silent_without_a_description(self):
        media = self._media_for_alert()
        self.assertEqual(media["reference_description"], "")
        self.assertTrue(media["reference_image_b64"])
