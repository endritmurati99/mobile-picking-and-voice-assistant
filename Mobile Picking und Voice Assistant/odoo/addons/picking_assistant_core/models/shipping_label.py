"""Versandkette am Lieferschein.

Die shipping_*-Felder sind die Projektion eines n8n-Jobs, nicht Eingabe.
Geschrieben werden sie ausschliesslich aus dem signierten Callback-Pfad
(`_apply_shipping_label`, laeuft unter sudo) oder vom Integrationsdienst.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Zustaende, in denen ein Job als abgeschlossen gilt -- nur dann darf ein
# neuer Versandlabel-Job fuer dasselbe Picking gestartet werden.
TERMINAL_JOB_STATES = ("succeeded", "review_required", "failed")


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

    @api.model
    def api_complete_and_request_label(self, picking_id):
        """Buchung und Versandereignis in EINER Transaktion.

        Ersetzt den direkten RPC-Aufruf von `button_validate` aus dem
        Backend. Entweder das Picking ist gebucht UND das Ereignis liegt in
        der Outbox, oder nichts von beidem: ein gebuchter Auftrag ohne
        Label-Anforderung waere ein Versand, den niemand anstoesst.
        """
        self.env["picking.assistant.api.mixin"]._require_api_service()
        picking = self.sudo().browse(int(picking_id)).exists()
        if not picking:
            raise ValidationError("Picking nicht gefunden.")

        jobs = self.env["picking.assistant.integration.job"].sudo()
        open_job = jobs.search(
            [
                ("aggregate_model", "=", picking._name),
                ("aggregate_res_id", "=", picking.id),
                ("job_type", "=", "shipping_label"),
                ("state", "not in", list(TERMINAL_JOB_STATES)),
            ],
            limit=1,
        )
        if open_job:
            raise ValidationError(
                "Fuer diesen Lieferschein laeuft bereits eine Label-Anforderung."
            )

        if picking.state != "done":
            picking.with_context(
                skip_immediate=True, skip_backorder=True
            ).button_validate()
        if picking.state != "done":
            raise ValidationError(
                "Odoo hat den Lieferschein nicht abgeschlossen; kein Versandereignis."
            )

        built = self.env["shipment.event.builder"].build(picking)
        jobs._enqueue_job_event(
            job_type="shipping_label",
            aggregate_model=picking._name,
            aggregate_res_id=picking.id,
            aggregate_revision=picking.integration_revision,
            event_id=built["event_id"],
            event_name="shipment.parcel.ready.v1",
            envelope_text=built["envelope_text"],
            payload_fingerprint=built["payload_fingerprint"],
            correlation_id=built["correlation_id"],
            job_id=built["job_id"],
        )
        picking.write({"shipping_label_status": "pending",
                       "shipping_failure_reason": False})
        return {
            "picking_complete": True,
            "job_id": built["job_id"],
            "picking_name": picking.name or "",
        }
