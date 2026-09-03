"""Versandkette am Lieferschein.

Die shipping_*-Felder sind die Projektion eines n8n-Jobs, nicht Eingabe.
Geschrieben werden sie ausschliesslich aus dem signierten Callback-Pfad
(`_apply_shipping_label`, laeuft unter sudo) oder vom Integrationsdienst.
"""
from odoo import api, fields, models


class StockPickingShippingLabel(models.Model):
    _inherit = "stock.picking"

    shipping_label_status = fields.Selection(
        [
            ("none", "Kein Label"),
            ("pending", "Label angefordert"),
            ("labeled", "Label erzeugt"),
            ("failed", "Fehlgeschlagen"),
        ],
        string="Versandlabel",
        default="none",
        required=True,
        copy=False,
        tracking=True,
    )
    shipping_carrier_code = fields.Char(string="Carrier-Code", copy=False)
    shipping_carrier_name = fields.Char(string="Carrier", copy=False, tracking=True)
    shipping_tracking_number = fields.Char(
        string="Sendungsnummer", copy=False, tracking=True
    )
    shipping_weight_kg = fields.Float(string="Versandgewicht (kg)", copy=False)
    shipping_label_attachment_id = fields.Many2one(
        "ir.attachment", string="Label-PDF", copy=False, ondelete="set null"
    )
    shipping_failure_reason = fields.Char(string="Fehlergrund", copy=False)
    shipping_labeled_at = fields.Datetime(string="Label erzeugt am", copy=False)
    # Monoton steigende Revision, wie bei quality.alert.custom:
    # `_enqueue_job_event` verlangt aggregate_revision >= 1.
    integration_revision = fields.Integer(
        string="Integrationsrevision", default=1, required=True, copy=False
    )

    _SHIPPING_FIELDS_PREFIX = "shipping_"

    def _require_shipping_fields_writable(self, vals):
        if not any(
            name.startswith(self._SHIPPING_FIELDS_PREFIX) or name == "integration_revision"
            for name in vals
        ):
            return
        if self.env.su:
            return
        self.env["picking.assistant.api.mixin"]._require_api_service()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._require_shipping_fields_writable(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._require_shipping_fields_writable(vals)
        return super().write(vals)
