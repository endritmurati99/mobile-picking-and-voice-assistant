"""Gemeinsame Basis: die `api_*`-Fassaden laufen als Integrationsdienst.

Seit die Fassaden von `quality_alert_custom` dieselbe Wache tragen wie die
der Integrationsmodule, wuerde ein Aufruf als Superuser der Testumgebung
mit AccessError enden -- `__system__` ist in keiner Gruppe. Die Tests rufen
sie deshalb wie das Backend: als Nutzer mit `group_api_service`.
"""
from odoo.tests.common import TransactionCase, new_test_user


class QualityApiCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.api_user = new_test_user(
            cls.env,
            login="quality_api",
            groups="base.group_user,picking_assistant_integration.group_api_service",
        )
        cls.internal_user = new_test_user(
            cls.env, login="quality_intern", groups="base.group_user"
        )
        cls.api_env = cls.env(user=cls.api_user)
        cls.internal_env = cls.env(user=cls.internal_user)
