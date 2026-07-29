"""Runtime-profile and origin configuration must fail closed.

Regression cover for whole-branch review findings #1 and #2a: a typo in
RUNTIME_PROFILE used to select the full development posture silently, and CORS
was configured from a setting that nothing validated.

Also covers the three Important findings from round 1 of the security review
of this task's own fix: wildcard-plus-credentials CORS reachable outside
production, RUNTIME_PROFILE never being set by the deployed stack, and
reject_removed_env_vars missing a stale key left in a .env file.
"""

import base64
import logging

import pytest
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware

from app.config import (
    ODOO_NONCE_RETENTION_SECONDS,
    Settings,
    parse_origins,
    reject_removed_env_vars,
    reject_wildcard_origins_with_credentials,
    validate_runtime_security,
    warn_non_production_runtime_profile,
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


# --- Round 1 fix findings -----------------------------------------------


def test_wildcard_origin_with_credentials_is_refused_unconditionally():
    # Starlette does not fall back to a safe wildcard when
    # allow_credentials=True; it echoes the request Origin instead. This
    # guard must fire regardless of runtime_profile -- it takes no profile
    # argument at all, on purpose.
    with pytest.raises(ValueError, match="allow_credentials"):
        reject_wildcard_origins_with_credentials(("*",), allow_credentials=True)


def test_wildcard_origin_with_credentials_is_refused_in_development():
    # Explicit regression cover for the exact failure scenario: an operator
    # sets PWA_ORIGINS=* on a development-profile LAN box, believing CORS
    # errors are merely annoying rather than a same-origin bypass.
    candidate = Settings(runtime_profile="development", pwa_origins="*")
    with pytest.raises(ValueError, match="allow_credentials"):
        reject_wildcard_origins_with_credentials(
            parse_origins(candidate.pwa_origins), allow_credentials=True
        )


def test_non_wildcard_origins_with_credentials_are_accepted():
    reject_wildcard_origins_with_credentials(
        ("https://pwa.example.com",), allow_credentials=True
    )


def test_wildcard_without_credentials_is_not_this_guards_concern():
    # allow_credentials=False is not exercised anywhere in this app (main.py
    # hardcodes True), but the guard itself must stay narrowly scoped to the
    # actual danger: wildcard + credentials, not wildcard alone.
    reject_wildcard_origins_with_credentials(("*",), allow_credentials=False)


def test_cors_middleware_setup_rejects_wildcard_with_credentials_at_import(monkeypatch):
    import importlib

    from app import config

    monkeypatch.setattr(config.settings, "runtime_profile", "development")
    monkeypatch.setattr(config.settings, "pwa_origins", "*")
    try:
        with pytest.raises(ValueError, match="allow_credentials"):
            importlib.reload(__import__("app.main", fromlist=["app"]))
    finally:
        monkeypatch.undo()
        importlib.reload(__import__("app.main", fromlist=["app"]))


def test_warns_when_runtime_profile_is_not_production(caplog):
    candidate = Settings(runtime_profile="development", mobile_header_grace_mode=True)
    with caplog.at_level(logging.WARNING, logger="app.config"):
        warn_non_production_runtime_profile(candidate)
    assert len(caplog.records) == 1
    assert "development" in caplog.records[0].message
    assert "True" in caplog.records[0].message


def test_warns_for_test_profile_too(caplog):
    candidate = Settings(runtime_profile="test")
    with caplog.at_level(logging.WARNING, logger="app.config"):
        warn_non_production_runtime_profile(candidate)
    assert len(caplog.records) == 1


def test_does_not_warn_in_production(caplog):
    candidate = Settings(
        runtime_profile="production",
        pwa_origins="https://pwa.example.com",
        odoo_instances_json=PROD_INSTANCES,
        n8n_webhook_secret="w" * 32,
        n8n_callback_secret="c" * 32,
        session_throttle_hmac_secret_b64=_b64_secret(),
        pwr_backend_to_n8n_active_secret_b64=_b64_secret(),
        pwr_n8n_to_backend_active_secret_b64=_b64_secret(),
        pwr_backend_to_n8n_active_key_id="k1",
        pwr_n8n_to_backend_active_key_id="k2",
    )
    with caplog.at_level(logging.WARNING, logger="app.config"):
        warn_non_production_runtime_profile(candidate)
    assert len(caplog.records) == 0


def test_reject_removed_env_vars_also_rejects_a_stale_dotenv_entry(tmp_path):
    # The precise scenario the function's docstring/comment describes: a
    # stale CORS_ORIGINS= line left behind in a .env file. pydantic-settings'
    # dotenv source parses this file directly and never populates
    # os.environ, so passing only os.environ (or an empty dict, as here)
    # must NOT be enough to pass.
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("CORS_ORIGINS=*\n", encoding="utf-8")
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        reject_removed_env_vars({}, env_file=str(dotenv_file))


def test_reject_removed_env_vars_passes_a_clean_dotenv_file(tmp_path):
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("PWA_ORIGINS=https://pwa.example.com\n", encoding="utf-8")
    reject_removed_env_vars({}, env_file=str(dotenv_file))


def test_reject_removed_env_vars_still_works_with_no_dotenv_file(tmp_path):
    missing = tmp_path / "does-not-exist.env"
    reject_removed_env_vars({"PWA_ORIGINS": "https://pwa.example.com"}, env_file=str(missing))
