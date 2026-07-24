from odoo.tests.common import TransactionCase, new_test_user


class IntegrationCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.api_user = new_test_user(
            cls.env,
            login="pwr_api",
            groups="base.group_user,picking_assistant_integration.group_api_service",
        )
        cls.picker = new_test_user(
            cls.env,
            login="mina",
            groups="base.group_user,picking_assistant_integration.group_picker",
        )
        cls.supervisor = new_test_user(
            cls.env,
            login="supervisor",
            groups="base.group_user,picking_assistant_integration.group_supervisor",
        )
