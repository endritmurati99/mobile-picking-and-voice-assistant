"""Pytest-Konfiguration und Fixtures."""
from datetime import datetime, timezone

import pytest

from app.dependencies import get_current_principal
from app.main import app
from app.models.auth import Principal


@pytest.fixture
def sample_principal() -> Principal:
    """Der eine, in Task 7 eingefrorene Test-Principal (siehe test_auth_dependencies.py)."""
    return Principal(
        picker_user_id=7,
        picker_name="Mina Muster",
        device_id="device-42",
        odoo_instance="o19",
        roles=frozenset({"picker"}),
        session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
        expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
    )


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


@pytest.fixture
def sample_picking():
    """Beispiel-Picking-Daten für Tests."""
    return {
        "id": 1,
        "name": "WH/INT/00001",
        "state": "assigned",
        "move_ids": [1, 2, 3],
        "location_id": [1, "WH/Stock"],
        "location_dest_id": [2, "WH/Output"],
    }


@pytest.fixture
def sample_voice_text():
    """Beispiel-Vosk-Transkripte."""
    return {
        "confirm": "bestätigt",
        "next": "nächster",
        "number": "vier sieben",
        "problem": "problem hier",
        "unknown": "blablabla",
    }
