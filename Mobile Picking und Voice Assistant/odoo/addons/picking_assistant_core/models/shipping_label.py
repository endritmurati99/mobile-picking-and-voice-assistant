"""Versandkette am Lieferschein.

Die shipping_*-Felder sind die Projektion eines n8n-Jobs, nicht Eingabe.
Geschrieben werden sie ausschliesslich aus dem signierten Callback-Pfad
(`_apply_shipping_label`, laeuft unter sudo) oder vom Integrationsdienst.
"""
import base64

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.picking_assistant_core.services.shipping_label_pdf import render_label
# Zustaende, in denen ein Job als abgeschlossen gilt -- nur dann darf ein
# neuer Versandlabel-Job fuer dasselbe Picking gestartet werden. Gemeinsam
# mit picking_assistant_integration definiert (core -> integration ist eine
# erlaubte Abhaengigkeitsrichtung), damit es nur eine Quelle der Wahrheit gibt.
from odoo.addons.picking_assistant_integration.models.integration_job import (
    TERMINAL_STATES as TERMINAL_JOB_STATES,
)


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
    # `_enqueue_job_event` verlangt aggregate_revision >= 1. Wird in
    # `api_complete_and_request_label` VOR dem Envelope-Bau erhoeht, damit
    # `aggregate.revision` im Envelope den neuen Stand traegt (nicht den
    # Stand vor der Anforderung).
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
            # skip_sms: mit installiertem stock_sms und Kunden mit Telefonnummer
            # liefert button_validate sonst den Wizard confirm.stock.sms zurueck
            # statt zu buchen (live gemessen am CH-Demokunden, 2026-09-03).
            picking.with_context(
                skip_immediate=True, skip_backorder=True, skip_sms=True
            ).button_validate()
        if picking.state != "done":
            raise ValidationError(
                "Odoo hat den Lieferschein nicht abgeschlossen; kein Versandereignis."
            )

        # Revision VOR dem Envelope-Bau erhoehen, sonst traegt
        # `aggregate.revision` noch den alten Stand (siehe Feldkommentar).
        picking.sudo().write({"integration_revision": picking.integration_revision + 1})
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

    _SHIPPING_STATUS_MAP = {
        "succeeded": "labeled",
        "review_required": "failed",
        "failed": "failed",
    }

    def _apply_shipping_label(self, status, result, error):
        """Wendet den Terminal-Callback der Versandkette an.

        Aufgerufen aus `picking.assistant.callback.receipt`, also in DERSELBEN
        Transaktion wie Job- und Receipt-Zustand. Privat (Unterstrich): ueber
        RPC nicht aufrufbar; ein Label entsteht nur ueber den signierten
        Callback-Pfad.
        """
        self.ensure_one()
        mapped = self._SHIPPING_STATUS_MAP.get(status)
        if mapped is None:
            raise ValidationError(f"Unbekannter Versandstatus: {status!r}")
        result = result or {}
        error = error or {}
        values = {
            "shipping_label_status": mapped,
            "shipping_failure_reason": error.get("message") or False,
        }
        if mapped == "failed":
            # Ein alter, gueltiger Tracking-Code neben "Fehlgeschlagen" waere
            # irrefuehrend -- alle Versandfelder eines frueheren Erfolgs
            # muessen mit dem Fehlschlag verschwinden, inkl. Anhang.
            old = self.shipping_label_attachment_id
            if old:
                old.unlink()
            values.update(
                {
                    "shipping_carrier_code": False,
                    "shipping_carrier_name": False,
                    "shipping_tracking_number": False,
                    "shipping_weight_kg": 0.0,
                    "shipping_labeled_at": False,
                    "shipping_label_attachment_id": False,
                }
            )
        if mapped == "labeled":
            label_data = dict(result.get("label") or {})
            label_data.setdefault("picking_name", self.name or "")
            label_data["tracking_number"] = result.get("tracking_number") or ""
            label_data["carrier_name"] = result.get("carrier_name") or ""
            label_data["service_note"] = result.get("service_note") or ""
            pdf_bytes = render_label(label_data)

            old = self.shipping_label_attachment_id
            attachment = self.env["ir.attachment"].sudo().create(
                {
                    "name": f"Versandlabel {self.name or self.id}.pdf",
                    "type": "binary",
                    "datas": base64.b64encode(pdf_bytes).decode("ascii"),
                    "mimetype": "application/pdf",
                    "res_model": self._name,
                    "res_id": self.id,
                }
            )
            if old:
                old.unlink()
            values.update(
                {
                    "shipping_carrier_code": result.get("carrier_code") or False,
                    "shipping_carrier_name": result.get("carrier_name") or False,
                    "shipping_tracking_number": result.get("tracking_number") or False,
                    "shipping_weight_kg": float(label_data.get("total_weight_kg") or 0.0),
                    "shipping_label_attachment_id": attachment.id,
                    "shipping_labeled_at": fields.Datetime.now(),
                }
            )
        self.sudo().write(values)
        return True
