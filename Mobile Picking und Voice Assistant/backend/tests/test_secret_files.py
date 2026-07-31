"""Secret files (`*_SECRET_FILE`) must be a first-class configuration source.

Task 15 of the Platform Security and Event Contracts Foundation: a production
deployment mounts Docker secrets as files below `/run/secrets` instead of
exporting them as environment variables. `read_secret(direct, file_path)` is the
single resolution point, and every downstream factory must go through it -- a
factory that still tests only the `*_B64` direct field is closed in exactly the
deployment shape the secret files exist for.

Two properties are asserted with real files on disk rather than mocks, because
both are properties of the filesystem and not of the call graph:

* a file whose mode has any bit in 0o077 is refused (group/other readable),
* a file-only production configuration passes exactly the same
  `validate_runtime_security` checks as a direct-value configuration.

Configuring BOTH forms of one secret is a hard error rather than a silent
precedence rule: a precedence rule is how two deployments end up disagreeing
about which secret is live.
"""

import base64
import os

import pytest

from app.config import (
    Settings,
    read_secret,
    validate_runtime_security,
)

PROD_INSTANCES = (
    '{"o19-a": {"url": "https://o19-a:8069", "db": "o19-a-db", "api_key": "key-a"}}'
)

THROTTLE_B64 = base64.b64encode(b"0" * 32).decode("ascii")
BACKEND_TO_N8N_B64 = base64.b64encode(b"1" * 32).decode("ascii")
BACKEND_TO_N8N_PREV_B64 = base64.b64encode(b"2" * 32).decode("ascii")
N8N_TO_BACKEND_B64 = base64.b64encode(b"3" * 32).decode("ascii")
N8N_TO_BACKEND_PREV_B64 = base64.b64encode(b"4" * 32).decode("ascii")
WEBHOOK_NATIVE = "w" * 32
CALLBACK_NATIVE = "c" * 32


def write_secret(tmp_path, name: str, content: str, mode: int = 0o600) -> str:
    """A real file on disk with a real mode -- never a mock.

    `tmp_path` lives on the Linux filesystem, not on the /mnt/c DrvFs mount,
    so `chmod` actually takes effect and the permission guard is exercised
    against the same `stat` call it uses in production.
    """
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)
    return str(path)


def direct_production_settings(**overrides) -> Settings:
    values = {
        "runtime_profile": "production",
        "pwa_origins": "https://picking.warehouse.test",
        "mobile_header_grace_mode": False,
        "odoo_instances_json": PROD_INSTANCES,
        "session_throttle_hmac_secret_b64": THROTTLE_B64,
        "pwr_backend_to_n8n_active_key_id": "b2n-2026-07",
        "pwr_backend_to_n8n_active_secret_b64": BACKEND_TO_N8N_B64,
        "pwr_n8n_to_backend_active_key_id": "n2b-2026-07",
        "pwr_n8n_to_backend_active_secret_b64": N8N_TO_BACKEND_B64,
        "n8n_webhook_secret": WEBHOOK_NATIVE,
        "n8n_callback_secret": CALLBACK_NATIVE,
    }
    values.update(overrides)
    return Settings(**values)


def file_production_settings(tmp_path, **overrides) -> Settings:
    """The same production posture, but every secret arrives as a file."""
    values = {
        "runtime_profile": "production",
        "pwa_origins": "https://picking.warehouse.test",
        "mobile_header_grace_mode": False,
        "odoo_instances_json": PROD_INSTANCES,
        "session_throttle_hmac_secret_file": write_secret(
            tmp_path, "throttle", THROTTLE_B64
        ),
        "pwr_backend_to_n8n_active_key_id": "b2n-2026-07",
        "pwr_backend_to_n8n_active_secret_file": write_secret(
            tmp_path, "b2n-active", BACKEND_TO_N8N_B64
        ),
        "pwr_n8n_to_backend_active_key_id": "n2b-2026-07",
        "pwr_n8n_to_backend_active_secret_file": write_secret(
            tmp_path, "n2b-active", N8N_TO_BACKEND_B64
        ),
        "n8n_webhook_secret_file": write_secret(tmp_path, "webhook", WEBHOOK_NATIVE),
        "n8n_callback_secret_file": write_secret(tmp_path, "callback", CALLBACK_NATIVE),
    }
    values.update(overrides)
    return Settings(**values)


# ---------------------------------------------------------------------------
# read_secret itself
# ---------------------------------------------------------------------------


def test_read_secret_returns_the_direct_value_when_no_file_is_configured():
    assert read_secret("direct-value", "") == "direct-value"


def test_read_secret_returns_stripped_file_contents(tmp_path):
    path = write_secret(tmp_path, "s", "  file-value \n")
    assert read_secret("", path) == "file-value"


def test_read_secret_refuses_both_forms_at_once(tmp_path):
    path = write_secret(tmp_path, "s", "file-value")
    with pytest.raises(ValueError, match="not both"):
        read_secret("direct-value", path)


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o660, 0o606, 0o666, 0o777])
def test_read_secret_refuses_a_group_or_other_accessible_file(tmp_path, mode):
    path = write_secret(tmp_path, f"s{mode:o}", "file-value", mode=mode)
    with pytest.raises(ValueError, match="permissions"):
        read_secret("", path)


@pytest.mark.parametrize("mode", [0o600, 0o400, 0o700])
def test_read_secret_accepts_an_owner_only_file(tmp_path, mode):
    path = write_secret(tmp_path, f"s{mode:o}", "file-value", mode=mode)
    assert read_secret("", path) == "file-value"


# ---------------------------------------------------------------------------
# validate_runtime_security resolves every pair exactly once
# ---------------------------------------------------------------------------


def test_direct_production_settings_still_pass():
    validate_runtime_security(direct_production_settings())


def test_file_only_production_settings_pass_the_same_checks(tmp_path):
    validate_runtime_security(file_production_settings(tmp_path))


@pytest.mark.parametrize(
    ("direct_field", "file_field"),
    [
        ("session_throttle_hmac_secret_b64", "session_throttle_hmac_secret_file"),
        (
            "pwr_backend_to_n8n_active_secret_b64",
            "pwr_backend_to_n8n_active_secret_file",
        ),
        (
            "pwr_n8n_to_backend_active_secret_b64",
            "pwr_n8n_to_backend_active_secret_file",
        ),
        ("n8n_webhook_secret", "n8n_webhook_secret_file"),
        ("n8n_callback_secret", "n8n_callback_secret_file"),
    ],
)
def test_configuring_both_forms_of_one_secret_fails_startup(
    tmp_path, direct_field, file_field
):
    candidate = file_production_settings(
        tmp_path,
        **{direct_field: "0" * 44},
    )
    with pytest.raises(ValueError, match="not both"):
        validate_runtime_security(candidate)


def test_a_short_native_secret_in_a_file_is_rejected(tmp_path):
    candidate = file_production_settings(
        tmp_path,
        n8n_webhook_secret_file=write_secret(tmp_path, "short-webhook", "too-short"),
    )
    with pytest.raises(ValueError, match="native"):
        validate_runtime_security(candidate)


def test_a_short_legacy_callback_secret_in_a_file_is_rejected(tmp_path):
    candidate = file_production_settings(
        tmp_path,
        n8n_callback_secret_file=write_secret(tmp_path, "short-callback", "too-short"),
    )
    with pytest.raises(ValueError, match="legacy callback"):
        validate_runtime_security(candidate)


def test_an_undersized_base64_secret_in_a_file_is_rejected(tmp_path):
    candidate = file_production_settings(
        tmp_path,
        pwr_backend_to_n8n_active_secret_file=write_secret(
            tmp_path, "short-b2n", base64.b64encode(b"short").decode("ascii")
        ),
    )
    with pytest.raises(ValueError, match="32 bytes"):
        validate_runtime_security(candidate)


def test_a_world_readable_secret_file_fails_startup(tmp_path):
    candidate = file_production_settings(
        tmp_path,
        session_throttle_hmac_secret_file=write_secret(
            tmp_path, "loose-throttle", THROTTLE_B64, mode=0o644
        ),
    )
    with pytest.raises(ValueError, match="permissions"):
        validate_runtime_security(candidate)


def test_previous_key_presence_is_compared_against_the_resolved_file_secret(tmp_path):
    """A previous key ID with the previous secret only in a file is complete."""
    candidate = file_production_settings(
        tmp_path,
        pwr_backend_to_n8n_previous_key_id="b2n-2026-06",
        pwr_backend_to_n8n_previous_secret_file=write_secret(
            tmp_path, "b2n-prev", BACKEND_TO_N8N_PREV_B64
        ),
        pwr_n8n_to_backend_previous_key_id="n2b-2026-06",
        pwr_n8n_to_backend_previous_secret_file=write_secret(
            tmp_path, "n2b-prev", N8N_TO_BACKEND_PREV_B64
        ),
    )
    validate_runtime_security(candidate)


def test_a_previous_key_id_without_any_resolved_previous_secret_fails(tmp_path):
    candidate = file_production_settings(
        tmp_path,
        pwr_backend_to_n8n_previous_key_id="b2n-2026-06",
    )
    with pytest.raises(ValueError, match="key ID must be configured together"):
        validate_runtime_security(candidate)


def test_a_previous_secret_file_without_its_key_id_fails(tmp_path):
    candidate = file_production_settings(
        tmp_path,
        pwr_n8n_to_backend_previous_secret_file=write_secret(
            tmp_path, "n2b-prev-orphan", N8N_TO_BACKEND_PREV_B64
        ),
    )
    with pytest.raises(ValueError, match="key ID must be configured together"):
        validate_runtime_security(candidate)


# ---------------------------------------------------------------------------
# Downstream consumers must all resolve through read_secret
# ---------------------------------------------------------------------------


def test_n8n_to_backend_keyring_builds_from_files_only(tmp_path):
    from app.dependencies import build_n8n_to_backend_keyring

    candidate = file_production_settings(
        tmp_path,
        pwr_n8n_to_backend_previous_key_id="n2b-2026-06",
        pwr_n8n_to_backend_previous_secret_file=write_secret(
            tmp_path, "n2b-prev-2", N8N_TO_BACKEND_PREV_B64
        ),
    )
    keyring = build_n8n_to_backend_keyring(candidate)
    assert keyring.active.key_id == "n2b-2026-07"
    assert keyring.active.secret == b"3" * 32
    assert keyring.previous is not None
    assert keyring.previous.secret == b"4" * 32


def test_outbox_dispatcher_transport_builds_from_files_only(tmp_path):
    from app.services.outbox_dispatcher import build_outbox_dispatcher

    candidate = file_production_settings(tmp_path)
    dispatcher = build_outbox_dispatcher(candidate, lambda name: None, {})
    transport = dispatcher._transport
    assert transport._key.key_id == "b2n-2026-07"
    assert transport._key.secret == b"1" * 32
    # The native header secret is a file too -- a transport that read the
    # direct field would carry an empty string here and every delivery would
    # be rejected by n8n.
    assert transport._native_secret == WEBHOOK_NATIVE


def test_session_service_throttle_secret_builds_from_a_file(tmp_path, monkeypatch):
    import app.dependencies as dependencies

    candidate = file_production_settings(tmp_path)
    monkeypatch.setattr(dependencies, "settings", candidate)
    dependencies._build_session_service.cache_clear()
    try:
        service = dependencies._build_session_service()
    finally:
        dependencies._build_session_service.cache_clear()
    assert service._throttle_secret == b"0" * 32


def test_legacy_callback_guard_accepts_a_file_provided_secret(tmp_path, monkeypatch):
    import app.dependencies as dependencies

    candidate = file_production_settings(tmp_path)
    monkeypatch.setattr(dependencies, "settings", candidate)
    # Correct secret from the file: no exception.
    dependencies.require_n8n_callback_secret(provided_secret=CALLBACK_NATIVE)


def test_legacy_callback_guard_still_rejects_a_wrong_secret(tmp_path, monkeypatch):
    from fastapi import HTTPException

    import app.dependencies as dependencies

    candidate = file_production_settings(tmp_path)
    monkeypatch.setattr(dependencies, "settings", candidate)
    with pytest.raises(HTTPException) as excinfo:
        dependencies.require_n8n_callback_secret(provided_secret="wrong")
    assert excinfo.value.status_code == 403


def test_legacy_n8n_webhook_client_reads_the_native_secret_from_a_file(
    tmp_path, monkeypatch
):
    import app.services.n8n_webhook as n8n_webhook

    candidate = file_production_settings(tmp_path)
    monkeypatch.setattr(n8n_webhook, "settings", candidate)
    client = n8n_webhook.N8NWebhookClient()
    assert client._secret == WEBHOOK_NATIVE
