"""Pytest-Konfiguration und Fixtures."""
from datetime import datetime, timezone

import pytest

from app.dependencies import get_current_principal, get_session_service
from app.main import app
from app.models.auth import Principal
from app.services.auth_sessions import CsrfFailed

# --- Task 16: das App-weite Browser-Gate in Routen-Tests ------------------
#
# Seit Task 16 haengen die Browser-Router an
# `get_current_principal` + `require_csrf_on_browser_mutation` +
# `require_domain_idempotency`. Fachliche Routen-Tests wollen dieses Gate
# nicht jedes Mal neu nachbauen, sie wollen dahinter stehen -- deshalb genau
# ein Helfer, statt in jeder Datei eine eigene Variante.
#
# Bewusst NICHT autouse: eine automatisch installierte Autorisierung wuerde
# jede kuenftige Sicherheitsaussage in dieser Suite still entwerten.

GATE_ORIGIN = "https://localhost"
GATE_CSRF_TOKEN = "test-csrf"
GATE_IDEMPOTENCY_KEY = "test-idempotency-key"

BROWSER_GATE_HEADERS = {
    "Origin": GATE_ORIGIN,
    "X-CSRF-Token": GATE_CSRF_TOKEN,
    "Idempotency-Key": GATE_IDEMPOTENCY_KEY,
}


class GateSessions:
    """Session-Service-Stub mit der EXAKTEN Origin-/Token-Semantik des echten
    Dienstes (exakter Vergleich, kein Praefix). Er ist absichtlich nicht
    grosszuegiger -- sonst wuerde ein Test gruen, den die Produktion ablehnt.
    """

    async def validate_csrf(self, principal, token, origin):
        if origin != GATE_ORIGIN:
            raise CsrfFailed("Origin ist nicht erlaubt.")
        if token != GATE_CSRF_TOKEN:
            raise CsrfFailed("CSRF-Token ist ungueltig.")


GATE_PRINCIPAL = Principal(
    picker_user_id=7,
    picker_name="Mina Muster",
    device_id="device-42",
    odoo_instance="o19",
    roles=frozenset({"picker"}),
    session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
)


def install_browser_gate(target_app, principal=GATE_PRINCIPAL) -> None:
    """Setzt Principal + Session-Service fuer das App-weite Gate."""
    target_app.dependency_overrides[get_current_principal] = lambda: principal
    target_app.dependency_overrides[get_session_service] = lambda: GateSessions()


@pytest.fixture
def sample_principal() -> Principal:
    """Der eine, in Task 7 eingefrorene Test-Principal (siehe test_auth_dependencies.py)."""
    return GATE_PRINCIPAL


@pytest.fixture
def as_sample_principal(sample_principal):
    """Ueberschreibt `get_current_principal` fuer die Dauer eines Tests, damit
    Routen-Tests die Principal-Identitaet direkt setzen koennen statt
    (nicht mehr autoritative) Header zu senden.
    """
    app.dependency_overrides[get_current_principal] = lambda: sample_principal
    try:
        yield sample_principal
    finally:
        app.dependency_overrides.pop(get_current_principal, None)
