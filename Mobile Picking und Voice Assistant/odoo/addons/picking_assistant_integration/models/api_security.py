from odoo import api, models
from odoo.exceptions import AccessError


class PickingAssistantApiMixin(models.AbstractModel):
    _name = "picking.assistant.api.mixin"
    _description = "Picking Assistant API Guard"

    def _require_api_service(self):
        if not self.env.user.has_group(
            "picking_assistant_integration.group_api_service"
        ):
            raise AccessError("Integration API group required.")


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
