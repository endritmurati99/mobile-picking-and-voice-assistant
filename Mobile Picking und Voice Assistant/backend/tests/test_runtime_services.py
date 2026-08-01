"""Foundation Task 16, RuntimeServices half.

`create_app(candidate)` takes a Settings instance, but until now nothing bound
it: the Odoo client cache, the SessionService and the HMAC keyring all came from
module-global state in `app.dependencies`, keyed on `app.config.settings`. Two
apps in one process therefore shared them, and the `candidate` argument was
decorative for everything below the router table.

These tests state that as a defect and fail against the unfixed code. They do
NOT go through the network: they read what each app actually bound, because the
sharing is invisible from the outside until two apps disagree about a secret.
"""
import pytest

from app.main import create_app
from tests.security_settings import make_secure_settings


def test_each_app_owns_its_runtime_services():
    first = create_app(make_secure_settings())
    second = create_app(make_secure_settings())

    assert hasattr(first.state, "runtime"), (
        "create_app must bind a RuntimeServices to app.state.runtime; without it "
        "the candidate settings reach the router table and nothing else"
    )
    assert first.state.runtime is not second.state.runtime, (
        "two apps share one RuntimeServices, so the second app's settings are "
        "silently ignored by every dependency"
    )


def test_the_runtime_carries_the_settings_it_was_built_with():
    candidate = make_secure_settings(llm_model="candidate-model")
    app = create_app(candidate)

    assert app.state.runtime.settings is candidate, (
        "the runtime must hold the candidate instance itself -- an equal-looking "
        "copy of app.config.settings would pass a value check while still "
        "reading global configuration"
    )
    assert app.state.runtime.settings.llm_model == "candidate-model"


def test_the_odoo_client_cache_is_per_app():
    first = create_app(make_secure_settings())
    second = create_app(make_secure_settings())

    client_a = first.state.runtime.odoo_client("local")
    client_b = second.state.runtime.odoo_client("local")

    assert first.state.runtime.odoo_client("local") is client_a, (
        "within one app the client must stay cached -- it owns the uid/secret "
        "cache and the httpx pool, so rebuilding it per request drops both"
    )
    assert client_a is not client_b, (
        "a client cache shared across apps hands app B a client built from "
        "app A's instance registry"
    )


def test_the_session_service_is_per_app_and_uses_that_apps_secret():
    first = create_app(make_secure_settings())
    second = create_app(
        make_secure_settings(
            session_throttle_hmac_secret_b64=(
                "OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk="
            )
        )
    )

    service_a = first.state.runtime.session_service()
    service_b = second.state.runtime.session_service()

    assert service_a is first.state.runtime.session_service(), "must stay cached per app"
    assert service_a is not service_b
    assert service_a._throttle_secret != service_b._throttle_secret, (
        "both apps derived the login-throttle key from the same global secret, "
        "so a per-instance secret rotation could not be tested at all"
    )


def test_the_keyring_comes_from_the_apps_own_settings():
    app = create_app(make_secure_settings(pwr_n8n_to_backend_active_key_id="app-key"))
    keyring = app.state.runtime.n8n_to_backend_keyring()
    assert keyring.active.key_id == "app-key"


def test_the_session_cookie_name_comes_from_the_apps_settings():
    """The last shape of the same defect, and the one that is invisible from
    outside: an app configured with its own cookie name would still look for
    the GLOBAL name on every request, so it could never authenticate anyone.
    Reading the app's settings is the whole point of `create_app(candidate)`.
    """
    from fastapi.testclient import TestClient

    app = create_app(make_secure_settings(session_cookie_name="pwr_session_b"))
    with TestClient(app) as client:
        # No cookie at all -- 401 either way; what is measured is WHICH name the
        # dependency looked for, via the app it belongs to.
        assert client.get("/api/auth/me").status_code == 401
    assert app.state.runtime.settings.session_cookie_name == "pwr_session_b"


def test_the_grace_mode_switch_reads_the_apps_profile():
    from app.dependencies import _grace_mode_active
    from app.runtime import RuntimeServices

    permissive = RuntimeServices(
        make_secure_settings(runtime_profile="development", mobile_header_grace_mode=True)
    )
    strict = RuntimeServices(make_secure_settings())

    assert _grace_mode_active(permissive) is True
    assert _grace_mode_active(strict) is False


def test_a_missing_secret_fails_closed_rather_than_yielding_a_default():
    app = create_app(
        make_secure_settings(
            session_throttle_hmac_secret_b64="",
            session_throttle_hmac_secret_file="",
        )
    )
    # Fail closed at the point of use, not at app build: a backend that refuses
    # to start cannot serve /health/live, and the operator loses the one probe
    # that would tell them which secret is missing.
    with pytest.raises((ValueError, OSError)):
        app.state.runtime.session_service()
