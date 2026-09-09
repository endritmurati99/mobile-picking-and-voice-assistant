from odoo import api, fields, models
from odoo.exceptions import ValidationError


class StockPickingBatchMobile(models.Model):
    _inherit = "stock.picking.batch"

    @api.model
    def api_create_mobile_batch(self, picking_ids, user_id=False):
        """Create one batch only after locking all selected pickings.

        The lock and the ``batch_id`` check share the RPC transaction. A
        process-local lock or a preceding backend read cannot protect against
        concurrent workers with different idempotency keys.
        """
        self.env["picking.assistant.api.mixin"]._require_api_service()
        ids = sorted({int(picking_id) for picking_id in (picking_ids or [])})
        if not ids:
            raise ValidationError("Keine Pickings fuer den Batch angegeben.")

        self.env.cr.execute(
            "SELECT id FROM stock_picking WHERE id IN %s ORDER BY id FOR UPDATE",
            [tuple(ids)],
        )
        self.env.invalidate_all()
        pickings = self.env["stock.picking"].sudo().browse(ids).exists()
        if len(pickings) != len(ids):
            raise ValidationError("Ein Picking wurde nicht gefunden.")
        if not 2 <= len(ids) <= 8:
            raise ValidationError("Ein Cluster braucht zwischen 2 und 8 Pickings.")
        if any(picking.state != "assigned" or picking.batch_id for picking in pickings):
            raise ValidationError("Mindestens ein Picking ist nicht mehr fuer einen neuen Batch verfuegbar.")
        now = fields.Datetime.now()
        if any(
            picking.mobile_claim_user_id
            and picking.mobile_claim_expires_at
            and picking.mobile_claim_expires_at > now
            for picking in pickings
        ):
            raise ValidationError("Mindestens ein Picking wird aktuell mobil bearbeitet.")

        company_ids = set(pickings.mapped("company_id").ids)
        if len(company_ids) > 1:
            raise ValidationError("Cluster darf keine Pickings aus mehreren Companies enthalten.")
        delivery_dates = {
            str(picking.date_deadline or picking.scheduled_date or "")[:10]
            for picking in pickings
            if picking.date_deadline or picking.scheduled_date
        }
        if len(delivery_dates) > 1:
            raise ValidationError("Cluster-Pickings brauchen denselben Ausliefertag.")
        vals = {"picking_ids": [(6, 0, ids)]}
        if company_ids:
            vals["company_id"] = next(iter(company_ids))
        if user_id:
            vals["user_id"] = int(user_id)
        batch = self.sudo().create(vals)
        package_model = self.env["stock.package"].sudo()
        for index, picking in enumerate(pickings.sorted("id"), start=1):
            lines = picking.move_line_ids
            if lines:
                package = package_model.create({"name": f"CLUSTER-B{index}/{picking.name}"})
                lines.sudo().write({"result_package_id": package.id})
        batch.with_context(skip_sms=True).action_confirm()
        return batch.id
