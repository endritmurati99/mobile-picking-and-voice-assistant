"""Tests fuer das Odoo-Profil-Register (config)."""
import pytest

from app import config
from app.config import OdooProfile, Settings, get_instance_registry


@pytest.fixture(autouse=True)
def _reset_instances(monkeypatch):
    # Default: kein Zusatz-JSON, bekannte local-Werte.
    monkeypatch.setattr(config.settings, "odoo_url", "http://odoo:8069")
    monkeypatch.setattr(config.settings, "odoo_db", "picking")
    monkeypatch.setattr(config.settings, "odoo_user", "admin")
    monkeypatch.setattr(config.settings, "odoo_api_key", "k")
    monkeypatch.setattr(config.settings, "odoo_password", "p")
    monkeypatch.setattr(config.settings, "odoo_instances_json", "")


def test_local_profile_always_present_from_settings():
    reg = get_instance_registry()
    assert "local" in reg
    local = reg["local"]
    assert isinstance(local, OdooProfile)
    assert local.url == "http://odoo:8069"
    assert local.db == "picking"
    assert local.display_name == "Lager 1"


def test_extra_profile_parsed_from_json(monkeypatch):
    monkeypatch.setattr(
        config.settings, "odoo_instances_json",
        '{"logilab": {"url": "https://logilab:8069", "db": "logilab", '
        '"user": "admin", "api_key": "x", "display_name": "LogILab"}}',
    )
    reg = get_instance_registry()
    assert set(reg) == {"local", "logilab"}
    assert reg["logilab"].url == "https://logilab:8069"
    assert reg["logilab"].display_name == "LogILab"


def test_local_key_in_json_is_ignored(monkeypatch):
    monkeypatch.setattr(
        config.settings, "odoo_instances_json",
        '{"local": {"url": "https://evil:8069", "db": "evil"}}',
    )
    reg = get_instance_registry()
    assert reg["local"].url == "http://odoo:8069"  # bleibt kanonisch aus odoo_*


def test_display_name_falls_back_to_name(monkeypatch):
    monkeypatch.setattr(
        config.settings, "odoo_instances_json",
        '{"logilab": {"url": "https://logilab:8069", "db": "logilab"}}',
    )
    assert get_instance_registry()["logilab"].display_name == "logilab"


def test_invalid_json_raises(monkeypatch):
    monkeypatch.setattr(config.settings, "odoo_instances_json", "{not json")
    with pytest.raises(ValueError):
        get_instance_registry()


def test_profile_missing_url_or_db_raises(monkeypatch):
    monkeypatch.setattr(
        config.settings, "odoo_instances_json", '{"x": {"db": "only-db"}}',
    )
    with pytest.raises(ValueError):
        get_instance_registry()


def test_odoo19_named_profile_must_not_target_live_database(monkeypatch):
    monkeypatch.setattr(
        config.settings,
        "odoo_instances_json",
        '{"o19-trial": {"url": "http://odoo19-trial:8069", "db": "masterfischer"}}',
    )

    with pytest.raises(ValueError, match="masterfischer_o19_trial"):
        get_instance_registry()


def test_registries_from_different_settings_do_not_share_profiles():
    first = Settings(
        odoo_db="picking-a",
        odoo_instances_json='{"extra-a": {"url": "https://a:8069", "db": "db-a"}}',
    )
    second = Settings(
        odoo_db="picking-b",
        odoo_instances_json='{"extra-b": {"url": "https://b:8069", "db": "db-b"}}',
    )

    registry_a = get_instance_registry(first)
    registry_b = get_instance_registry(second)

    assert registry_a["local"].db == "picking-a"
    assert registry_b["local"].db == "picking-b"
    assert set(registry_a) == {"local", "extra-a"}
    assert set(registry_b) == {"local", "extra-b"}
    assert "extra-a" not in registry_b
    assert "extra-b" not in registry_a


def test_production_with_authoritative_json_has_no_implicit_local():
    candidate = Settings(
        runtime_profile="production",
        odoo_instances_json=(
            '{"o19-a": {"url": "https://o19-a:8069", "db": "o19-a-db", '
            '"api_key": "key-a"}, '
            '"o19-b": {"url": "https://o19-b:8069", "db": "o19-b-db", '
            '"api_key": "key-b"}}'
        ),
    )

    registry = get_instance_registry(candidate)

    assert set(registry) == {"o19-a", "o19-b"}
    assert "local" not in registry
