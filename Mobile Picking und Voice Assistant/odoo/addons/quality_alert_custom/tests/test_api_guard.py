"""Die Wache vor den `api_*`-Fassaden und vor den ai_*-Feldern.

Befund vom 2026-09-02: `quality_alert_custom` trug als einziges Modul keine
`_require_api_service()`-Wache. `group_quality_user` haengt an
`base.group_user`, also konnte jeder interne Nutzer per JSON-RPC Alerts samt
ungeprueften Fotos anlegen, fremde Meldefotos ueber die Job-Kennung lesen,
die SOLL-Beschreibung setzen und per ORM ein Urteil eintragen, das kein
Modell getroffen hat. Diese Tests halten die Tuer zu.
"""
from odoo.exceptions import AccessError

from .common import QualityApiCase


class TestApiGuard(QualityApiCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "picking_assistant.instance_name", "local"
        )
        self.template = self.env["product.product"].create(
            {"name": "Pruefbaustein", "type": "consu"}
        ).product_tmpl_id

    # -- Fassaden -----------------------------------------------------------

    def test_internal_user_cannot_create_alert_over_the_facade(self):
        with self.assertRaises(AccessError):
            self.internal_env["quality.alert.custom"].api_create_alert(
                {"description": "fremd", "priority": "1"}
            )

    def test_internal_user_cannot_read_assessment_media(self):
        with self.assertRaises(AccessError):
            self.internal_env["quality.alert.custom"].api_get_assessment_media(
                "00000000-0000-4000-8000-000000000000", 1, "x" * 43
            )

    def test_internal_user_cannot_set_reference_description(self):
        with self.assertRaises(AccessError):
            self.internal_env["product.template"].api_set_reference_description(
                self.template.id, "erfunden", True
            )
        self.assertFalse(self.template.ai_reference_description)

    def test_api_service_still_passes(self):
        result = self.api_env["quality.alert.custom"].api_create_alert(
            {"description": "echt", "priority": "1"}
        )
        self.assertTrue(result["alert_id"])
        self.assertTrue(
            self.api_env["product.template"].api_set_reference_description(
                self.template.id, "toy brick, yellow", True
            )
        )

    def test_apply_assessment_is_not_reachable_over_rpc(self):
        # Fuehrender Unterstrich: Odoo verweigert solche Methoden per RPC.
        model = self.env["quality.alert.custom"]
        self.assertFalse(hasattr(model, "api_apply_assessment"))
        self.assertTrue(hasattr(model, "_apply_assessment"))

    # -- ai_*-Felder ---------------------------------------------------------

    def test_internal_user_cannot_write_a_verdict(self):
        alert = self.env["quality.alert.custom"].create(
            {"description": "Karton zerdrueckt", "ai_evaluation_status": "pending"}
        )
        with self.assertRaises(AccessError):
            alert.with_user(self.internal_user).write({"ai_disposition": "sellable"})
        with self.assertRaises(AccessError):
            self.internal_env["quality.alert.custom"].create(
                {"description": "neu", "ai_disposition": "scrap"}
            )
        self.assertFalse(alert.ai_disposition)

    def test_internal_user_still_edits_the_business_fields(self):
        alert = self.env["quality.alert.custom"].create({"description": "alt"})
        alert.with_user(self.internal_user).write({"description": "neu"})
        self.assertEqual(alert.description, "neu")
        created = self.internal_env["quality.alert.custom"].create({"description": "eigen"})
        self.assertEqual(created.description, "eigen")
        self.assertFalse(created.ai_disposition)

    def test_projection_under_sudo_still_writes_the_verdict(self):
        alert = self.env["quality.alert.custom"].create(
            {"description": "Karton zerdrueckt", "ai_evaluation_status": "pending"}
        )
        alert.with_user(self.internal_user).sudo()._apply_assessment(
            "succeeded",
            {"disposition": "scrap", "confidence": 0.9, "provider": "p", "model": "m"},
            None,
        )
        self.assertEqual(alert.ai_disposition, "scrap")
