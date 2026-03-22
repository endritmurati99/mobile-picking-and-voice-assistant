from odoo import models, fields, api


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

    photo = fields.Binary(string="Foto", attachment=True)
    photo_filename = fields.Char(string="Dateiname")

    def _get_default_stage(self):
        return self.env["quality.alert.stage.custom"].search(
            [], order="sequence asc", limit=1
        )

    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        return self.env["quality.alert.stage.custom"].search([])

    @api.model
    def api_create_alert(self, vals):
        """
        Atomare Methode für externe Alert-Erstellung.
        Erstellt Alert + optional Foto-Attachment in einer Transaktion.
        """
        photo_b64 = vals.pop("photo_base64", None)
        photo_filename = vals.pop("photo_filename", None)

        alert = self.create(vals)

        if photo_b64 and photo_filename:
            self.env["ir.attachment"].create({
                "name": photo_filename,
                "type": "binary",
                "datas": photo_b64,
                "res_model": self._name,
                "res_id": alert.id,
                "mimetype": "image/jpeg",
            })

        return {"alert_id": alert.id, "name": alert.name}
