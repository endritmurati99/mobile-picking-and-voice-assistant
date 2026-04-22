from odoo import models, fields, api
from markupsafe import Markup


class QualityAlertStage(models.Model):
    _name = "quality.alert.stage.custom"
    _description = "Quality Alert Stage"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    fold = fields.Boolean(default=False)


class QualityAlert(models.Model):
    _name = "quality.alert.custom"
    _description = "Quality Alert"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="Referenz",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "quality.alert.custom"
        ) or "NEU",
    )
    description = fields.Text(string="Beschreibung", required=True)

    # Verknüpfungen
    picking_id = fields.Many2one(
        "stock.picking", string="Transfer", ondelete="set null", tracking=True,
    )
    product_id = fields.Many2one(
        "product.product", string="Produkt", ondelete="set null", tracking=True,
    )
    location_id = fields.Many2one(
        "stock.location", string="Lagerort", ondelete="set null",
    )
    lot_id = fields.Many2one(
        "stock.lot", string="Charge/Seriennummer", ondelete="set null",
    )

    # Workflow
    stage_id = fields.Many2one(
        "quality.alert.stage.custom",
        string="Status",
        tracking=True,
        group_expand="_read_group_stage_ids",
        default=lambda self: self._get_default_stage(),
    )
    priority = fields.Selection(
        [("0", "Normal"), ("1", "Niedrig"), ("2", "Hoch"), ("3", "Kritisch")],
        string="Priorität",
        default="0",
        tracking=True,
    )
    user_id = fields.Many2one(
        "res.users", string="Erfasst von", default=lambda self: self.env.user,
    )

    # Systembewertung (automatische Auswertung via n8n-Heuristik)
    ai_disposition = fields.Selection(
        [
            ("sellable", "Verkaufbar"),
            ("rework", "Nacharbeit"),
            ("quarantine", "Quarantäne"),
            ("scrap", "Totalschaden"),
        ],
        string="Einstufung",
        tracking=True,
    )
    ai_confidence = fields.Float(string="Konfidenz", tracking=True)
    ai_summary = fields.Text(string="System-Begründung", tracking=True)
    ai_enhanced_description = fields.Text(string="Systembeschreibung")
    ai_photo_analysis = fields.Text(string="Fotoanalyse")
    ai_recommended_action = fields.Text(string="Empfohlene Aktion", tracking=True)
    ai_last_analyzed_at = fields.Datetime(string="Analysiert am", tracking=True)
    ai_provider = fields.Char(string="Provider")
    ai_model = fields.Char(string="Modell")
    ai_evaluation_status = fields.Selection(
        [
            ("pending", "Ausstehend"),
            ("completed", "Abgeschlossen"),
            ("failed", "Fehlgeschlagen"),
        ],
        string="Analyse-Status",
        tracking=True,
    )
    ai_failure_reason = fields.Char(string="Fehlergrund")

    # Fotos
    photo = fields.Binary(string="Foto", attachment=True)
    photo_filename = fields.Char(string="Dateiname")
    photo_count = fields.Integer(string="Anzahl Fotos", compute="_compute_photo_count")
    photo_gallery = fields.Html(string="Foto-Galerie", compute="_compute_photo_gallery", sanitize=False)

    def _compute_photo_count(self):
        for rec in self:
            rec.photo_count = self.env["ir.attachment"].search_count([
                ("res_model", "=", "quality.alert.custom"),
                ("res_id", "=", rec.id),
                ("mimetype", "like", "image"),
            ])

    def _compute_photo_gallery(self):
        for rec in self:
            attachments = self.env["ir.attachment"].search([
                ("res_model", "=", "quality.alert.custom"),
                ("res_id", "=", rec.id),
                ("mimetype", "like", "image"),
            ])
            if not attachments:
                rec.photo_gallery = Markup("<p style='color:#888'>Keine Fotos vorhanden.</p>")
                continue
            parts = []
            for att in attachments:
                url = f"/web/image/{att.id}"
                parts.append(
                    f'<a href="{url}" target="_blank" title="{att.name}"'
                    f' style="display:block;overflow:hidden;border-radius:8px;">'
                    f'<img src="{url}" style="width:100%;height:120px;'
                    f'border:1px solid #ddd;object-fit:cover;display:block;'
                    f'border-radius:8px;"/>'
                    f'</a>'
                )
            html = (
                '<div style="display:grid;'
                'grid-template-columns:repeat(auto-fill,minmax(120px,1fr));'
                'gap:8px;padding:8px 0;max-height:300px;overflow-y:auto;">'
                + "".join(parts)
                + '</div>'
            )
            rec.photo_gallery = Markup(html)

    def _get_default_stage(self):
        return self.env["quality.alert.stage.custom"].search(
            [], order="sequence asc", limit=1
        )

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return self.env["quality.alert.stage.custom"].search([])

    def action_set_in_progress(self):
        stage = self.env.ref(
            "quality_alert_custom.stage_in_progress", raise_if_not_found=False
        )
        if stage:
            self.write({"stage_id": stage.id})

    def action_set_done(self):
        stage = self.env.ref(
            "quality_alert_custom.stage_done", raise_if_not_found=False
        )
        if stage:
            self.write({"stage_id": stage.id})

    @api.model
    def api_create_alert(self, vals):
        """
        Atomare Methode für externe Alert-Erstellung.
        Akzeptiert photos als Liste von {data_b64, filename}.
        sudo() wird verwendet, da die Rechteprüfung auf API-Ebene (FastAPI) erfolgt.
        """
        photos = vals.pop("photos", [])
        single_b64 = vals.pop("photo_base64", None)
        single_name = vals.pop("photo_filename", None)
        if single_b64 and single_name:
            photos.insert(0, {"data_b64": single_b64, "filename": single_name})

        if photos:
            vals["photo"] = photos[0]["data_b64"]

        alert = self.sudo().create(vals)

        for i, p in enumerate(photos):
            self.env["ir.attachment"].sudo().create({
                "name": p.get("filename", f"photo_{i}.jpg"),
                "type": "binary",
                "datas": p["data_b64"],
                "res_model": self._name,
                "res_id": alert.id,
                "mimetype": "image/jpeg",
            })

        return {"alert_id": alert.id, "name": alert.name}
