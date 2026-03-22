"""Pytest-Konfiguration und Fixtures."""
import pytest


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
