"""Runtime-profile and origin configuration must fail closed.

Regression cover for whole-branch review findings #1 and #2a: a typo in
RUNTIME_PROFILE used to select the full development posture silently, and CORS
was configured from a setting that nothing validated.
"""

import base64

import pytest
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware

from app.config import (
    ODOO_NONCE_RETENTION_SECONDS,
    Settings,
    parse_origins,
    reject_removed_env_vars,
    validate_runtime_security,
)

PROD_INSTANCES = (
    '{"o19-a": {"url": "https://o19-a:8069", "db": "o19-a-db", "api_key": "key-a"}}'
)


def _b64_secret() -> str:
    return base64.b64encode(b"0" * 32).decode("ascii")


@pytest.mark.parametrize(
    "value",
    ["prod", "Production", "PRODUCTION", " production", "production ", "", "dev", "prd"],
)
def test_unknown_runtime_profile_is_rejected_at_construction(value):
    with pytest.raises(ValidationError):
        Settings(runtime_profile=value)


@pytest.mark.parametrize("value", ["development", "test", "production"])
def test_known_runtime_profiles_are_accepted(value):
    assert Settings(runtime_profile=value).runtime_profile == value


def test_grace_mode_is_off_by_default():
    assert Settings().mobile_header_grace_mode is False


def test_hmac_skew_above_300_seconds_is_rejected():
    with pytest.raises(ValidationError):
        Settings(pwr_hmac_max_skew_seconds=301)


def test_role_revalidation_above_300_seconds_is_rejected():
    with pytest.raises(ValidationError):
        Settings(session_role_revalidate_seconds=301)


def test_nonce_ttl_must_exceed_the_signature_acceptance_window():
    # The window is +/- skew, so 2 * skew wide. A nonce that is forgotten
    # before the window closes is a replay that no store can catch.
    with pytest.raises(ValidationError):
        Settings(pwr_hmac_max_skew_seconds=300, pwr_nonce_ttl_seconds=599)


def test_nonce_ttl_may_not_exceed_the_odoo_retention():
    # Odoo retains nonces for ODOO_NONCE_RETENTION_SECONDS. Configuring the
    # backend to expect longer memory than Odoo actually has is a lie.
    with pytest.raises(ValidationError):
        Settings(pwr_nonce_ttl_seconds=ODOO_NONCE_RETENTION_SECONDS + 1)


def test_removed_cors_origins_env_var_fails_closed():
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        reject_removed_env_vars({"CORS_ORIGINS": "*"})


def test_reject_removed_env_vars_passes_a_clean_environment():
    reject_removed_env_vars({"PWA_ORIGINS": "https://pwa.example.com"})


def test_settings_no_longer_carries_a_second_origin_field():
    assert "cors_origins" not in Settings.model_fields


def test_production_rejects_wildcard_pwa_origins():
    candidate = Settings(
        runtime_profile="production",
        pwa_origins="*",
        odoo_instances_json=PROD_INSTANCES,
        n8n_webhook_secret="w" * 32,
        n8n_callback_secret="c" * 32,
        session_throttle_hmac_secret_b64=_b64_secret(),
        pwr_backend_to_n8n_active_secret_b64=_b64_secret(),
        pwr_n8n_to_backend_active_secret_b64=_b64_secret(),
        pwr_backend_to_n8n_active_key_id="k1",
        pwr_n8n_to_backend_active_key_id="k2",
    )
    with pytest.raises(ValueError, match="Wildcard"):
        validate_runtime_security(candidate)


def test_cors_middleware_uses_the_single_validated_origin_list():
    from app.config import settings
    from app.main import app

    cors = [entry for entry in app.user_middleware if entry.cls is CORSMiddleware]
    assert len(cors) == 1, "exactly one CORS middleware is expected"
    assert tuple(cors[0].kwargs["allow_origins"]) == parse_origins(settings.pwa_origins)


def test_grace_mode_is_inactive_outside_development(monkeypatch):
    from app import dependencies

    monkeypatch.setattr(dependencies.settings, "runtime_profile", "test")
    monkeypatch.setattr(dependencies.settings, "mobile_header_grace_mode", True)
    assert dependencies._grace_mode_active() is False


def test_grace_mode_still_works_in_development_when_explicitly_enabled(monkeypatch):
    from app import dependencies

    monkeypatch.setattr(dependencies.settings, "runtime_profile", "development")
    monkeypatch.setattr(dependencies.settings, "mobile_header_grace_mode", True)
    assert dependencies._grace_mode_active() is True
