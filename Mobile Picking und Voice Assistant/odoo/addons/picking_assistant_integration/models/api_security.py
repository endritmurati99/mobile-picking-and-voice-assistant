import re

from odoo import api, models
from odoo.exceptions import AccessError, ValidationError


class PickingAssistantApiMixin(models.AbstractModel):
    _name = "picking.assistant.api.mixin"
    _description = "Picking Assistant API Guard"

    # Muster identisch zu EventSource.odoo_instance im Backend
    # (backend/app/models/events.py). Weicht es ab, baut Odoo Envelopes, die
    # die Gegenseite nicht annimmt.
    _INSTANCE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

    def _require_api_service(self):
        if not self.env.user.has_group(
            "picking_assistant_integration.group_api_service"
        ):
            raise AccessError("Integration API group required.")

    @api.model
    def _instance_name(self):
        """Der Name, unter dem das Backend DIESE Instanz kennt.

        Er steuert, in welche Datenbank ein Callback zurueckschreibt, und ist
        deshalb Konfiguration, keine Ableitung: Odoo kann seinen eigenen
        Profilnamen im Backend nicht erraten.
        """
        raw = self.env["ir.config_parameter"].sudo().get_param(
            "picking_assistant.instance_name"
        )
        value = (raw or "").strip()
        if not self._INSTANCE_NAME_RE.match(value):
            raise ValidationError(
                "picking_assistant.instance_name ist nicht gesetzt oder ungueltig."
            )
        return value


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def api_get_picker_principal(self, user_id):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        user = self.sudo().browse(int(user_id)).exists()
        if not user or not user.active or user.share:
            return {"allowed": False}
        roles = []
        if user.has_group("picking_assistant_integration.group_picker"):
            roles.append("picker")
        if user.has_group("picking_assistant_integration.group_supervisor"):
            roles.append("supervisor")
        return {
            "allowed": bool(roles),
            "picker_user_id": user.id,
            "picker_name": user.name,
            "roles": roles,
        }
