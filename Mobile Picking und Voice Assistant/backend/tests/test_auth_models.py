from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.config import Settings, validate_runtime_security
from app.models.auth import PickerSessionLoginRequest, Principal


def secure_settings(**overrides) -> Settings:
    values = {
        "runtime_profile": "production",
        "pwa_origins": "https://picking.warehouse.test",
        "mobile_header_grace_mode": False,
        "odoo_api_key": "service-key",
        "session_throttle_hmac_secret_b64": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        "pwr_backend_to_n8n_active_key_id": "b2n-2026-07",
        "pwr_backend_to_n8n_active_secret_b64": "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=",
        "pwr_n8n_to_backend_active_key_id": "n2b-2026-07",
        "pwr_n8n_to_backend_active_secret_b64": "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI=",
        "n8n_webhook_secret": "3" * 32,
        "n8n_callback_secret": "4" * 32,
    }
    values.update(overrides)
    return Settings(**values)


def test_login_request_rejects_unknown_fields_and_bad_device_id():
    with pytest.raises(ValidationError):
        PickerSessionLoginRequest(
            login="mina",
            password="secret",
            device_id="not-a-uuid",
            odoo_instance="o19",
            picker_user_id=7,
        )


def test_principal_is_immutable_and_instance_bound():
    principal = Principal(
        picker_user_id=7,
        picker_name="Mina Muster",
        device_id="123e4567-e89b-42d3-a456-426614174000",
        odoo_instance="o19",
        roles=frozenset({"picker"}),
        session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
        expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(AttributeError):
        principal.odoo_instance = "local"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"pwa_origins": "*"}, "Wildcard"),
        ({"pwa_origins": "http://warehouse.test"}, "HTTPS"),
        ({"mobile_header_grace_mode": True}, "grace"),
        ({"pwr_backend_to_n8n_active_secret_b64": "c2hvcnQ="}, "32 bytes"),
        ({"n8n_webhook_secret": ""}, "native"),
        ({"odoo_api_key": "", "odoo_password": ""}, "Odoo service"),
    ],
)
def test_production_security_is_fail_closed(overrides, message):
    with pytest.raises(ValueError, match=message):
        validate_runtime_security(secure_settings(**overrides))


def test_secure_production_settings_pass():
    validate_runtime_security(secure_settings())
