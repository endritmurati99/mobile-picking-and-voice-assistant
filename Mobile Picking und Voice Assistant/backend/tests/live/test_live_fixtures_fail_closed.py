"""Selbsttests der Live-Fixtures.

Diese laufen OHNE Live-Stack -- sie pruefen die Fixtures selbst, nicht die
Anlage. Sie sind der Grund, warum man dem Live-Gate glauben darf: sie zeigen,
dass es scheitert, wenn die Umgebung fehlt oder luegt, statt still gruen zu
werden. Ein Waechter, den man nicht hat scheitern sehen, ist kein Waechter.

Sie tragen bewusst KEINEN Live-Marker: sie brauchen weder Odoo noch n8n und
sollen genau dann laufen, wenn niemand einen Stack hat.
"""
import json
import os
import stat
from pathlib import Path

import pytest

from tests.live import conftest as live_conftest

# `pytest.fail` raises `Failed`, which does NOT inherit from `Exception` -- it is
# an outcome, not an error, so that a stray `except Exception` in a fixture
# cannot swallow it. That is exactly the property these tests rely on, so they
# name it explicitly instead of catching something broader.
Failed = pytest.fail.Exception


def _clear_live_env(monkeypatch):
    for name in live_conftest.REQUIRED:
        monkeypatch.delenv(name, raising=False)


def _full_env(tmp_path, monkeypatch, **overrides):
    password = tmp_path / "service-password"
    password.write_text("s3cret", encoding="utf-8")
    password.chmod(0o600)
    secret = tmp_path / "n2b-secret"
    secret.write_text("MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=", encoding="utf-8")
    secret.chmod(0o600)
    metadata = tmp_path / "seed.json"
    metadata.write_text(
        json.dumps(
            {
                "instances": [],
                "twenty_event_ids": [],
                "restart_event": {},
            }
        ),
        encoding="utf-8",
    )
    values = {
        "ODOO19_LIVE_URL": "http://127.0.0.1:8069/jsonrpc",
        "ODOO19_LIVE_DB_A": "o19_a",
        "ODOO19_LIVE_DB_B": "o19_b",
        "ODOO19_LIVE_USER": "live-service",
        "ODOO19_LIVE_PASSWORD_FILE": str(password),
        "FOUNDATION_API_URL": "http://127.0.0.1:8000",
        "FOUNDATION_CA_FILE": str(tmp_path / "ca.pem"),
        "FOUNDATION_N2B_KEY_ID": "n2b-live",
        "FOUNDATION_N2B_SECRET_FILE": str(secret),
        "FOUNDATION_SEED_METADATA": str(metadata),
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def _run_fixture(fixture, **kwargs):
    """Ruft die undekorierte Fixture-Funktion direkt auf."""
    return fixture.__wrapped__(**kwargs)


def test_missing_environment_fails_and_names_every_variable(monkeypatch):
    """Der wichtigste Selbsttest: ein SKIP waere hier ein bestandener Lauf.

    Zusaetzlich muss die Meldung ALLE fehlenden Namen nennen -- sonst faehrt
    man das Gate zehnmal und lernt jedes Mal genau eine Variable dazu.
    """
    _clear_live_env(monkeypatch)
    with pytest.raises(Failed) as excinfo:
        _run_fixture(live_conftest.live_config)
    message = str(excinfo.value)
    assert "live gate requires environment" in message
    for name in live_conftest.REQUIRED:
        assert name in message, f"the failure does not name {name}"


def test_a_single_missing_variable_is_still_fatal(tmp_path, monkeypatch):
    _full_env(tmp_path, monkeypatch)
    monkeypatch.delenv("ODOO19_LIVE_DB_B")
    with pytest.raises(Failed) as excinfo:
        _run_fixture(live_conftest.live_config)
    assert "ODOO19_LIVE_DB_B" in str(excinfo.value)


def test_the_two_databases_may_not_be_the_same(tmp_path, monkeypatch):
    """Sonst vergleicht die Isolationspruefung eine Datenbank mit sich selbst
    und besteht immer."""
    _full_env(tmp_path, monkeypatch, ODOO19_LIVE_DB_B="o19_a")
    with pytest.raises(Failed) as excinfo:
        _run_fixture(live_conftest.live_config)
    assert "same database" in str(excinfo.value)


def test_a_non_loopback_plain_http_target_is_refused(tmp_path, monkeypatch):
    """Der Live-Backend-Port ist loopback-only. Ein Gate, das versehentlich
    gegen einen LAN-Host laeuft, misst eine andere Anlage."""
    _full_env(tmp_path, monkeypatch, FOUNDATION_API_URL="http://picking.warehouse.test")
    with pytest.raises(Failed) as excinfo:
        _run_fixture(live_conftest.live_config)
    assert "loopback" in str(excinfo.value)


def test_a_world_readable_password_file_is_refused(tmp_path, monkeypatch):
    config = _full_env(tmp_path, monkeypatch)
    Path(config["ODOO19_LIVE_PASSWORD_FILE"]).chmod(0o644)
    with pytest.raises(Failed) as excinfo:
        live_conftest._read_restricted_secret(
            config["ODOO19_LIVE_PASSWORD_FILE"], "ODOO19_LIVE_PASSWORD_FILE"
        )
    assert "too broad" in str(excinfo.value)


def test_a_short_signing_secret_is_refused(tmp_path, monkeypatch):
    import base64

    config = _full_env(tmp_path, monkeypatch)
    short = Path(config["FOUNDATION_N2B_SECRET_FILE"])
    short.write_text(base64.b64encode(b"0" * 16).decode(), encoding="utf-8")
    short.chmod(0o600)
    with pytest.raises(Failed) as excinfo:
        _run_fixture(
            live_conftest.n2b_signing_key,
            live_config=_run_fixture(live_conftest.live_config),
        )
    assert "at least 32" in str(excinfo.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"instances": [], "twenty_event_ids": []},
        {"instances": [], "twenty_event_ids": [], "restart_event": {}, "extra": 1},
        [],
    ],
    ids=["missing-key", "extra-key", "not-an-object"],
)
def test_a_corrupt_seed_schema_is_refused(tmp_path, monkeypatch, payload):
    """Genau das Schema, nicht "mindestens" das Schema.

    Ein zusaetzlicher Schluessel heisst, dass Seed und Gate verschiedene
    Vorstellungen von der Ausgabe haben -- und dann ist unklar, welche Haelfte
    veraltet ist.
    """
    config = _full_env(tmp_path, monkeypatch)
    Path(config["FOUNDATION_SEED_METADATA"]).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    with pytest.raises(Failed) as excinfo:
        _run_fixture(live_conftest.seed_metadata, live_config=config)
    assert "schema mismatch" in str(excinfo.value)


def test_missing_seed_metadata_is_refused(tmp_path, monkeypatch):
    config = _full_env(tmp_path, monkeypatch)
    Path(config["FOUNDATION_SEED_METADATA"]).unlink()
    with pytest.raises(Failed) as excinfo:
        _run_fixture(live_conftest.seed_metadata, live_config=config)
    assert "seed metadata missing" in str(excinfo.value)


@pytest.mark.asyncio
async def test_an_rpc_error_member_fails_instead_of_returning_none():
    """Der gefaehrlichste stille Ausfall.

    Kaeme ein RPC-Fehler als `None` zurueck, wuerde `assert counts == before`
    im Isolationstest bestehen, ohne dass jemals etwas gezaehlt wurde.
    """

    class ErrorClient:
        async def post(self, url, json):  # noqa: A002 - httpx-Signatur
            return _Response(200, {"jsonrpc": "2.0", "error": {"message": "boom"}})

    with pytest.raises(Failed) as excinfo:
        await live_conftest.json_rpc(
            ErrorClient(), "http://odoo/jsonrpc", "object", "execute_kw", []
        )
    assert "boom" in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_result_less_response_fails():
    class EmptyClient:
        async def post(self, url, json):  # noqa: A002
            return _Response(200, {"jsonrpc": "2.0"})

    with pytest.raises(Failed) as excinfo:
        await live_conftest.json_rpc(
            EmptyClient(), "http://odoo/jsonrpc", "object", "execute_kw", []
        )
    assert "no result member" in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_non_200_rpc_response_fails():
    class BadStatusClient:
        async def post(self, url, json):  # noqa: A002
            return _Response(500, {})

    with pytest.raises(Failed) as excinfo:
        await live_conftest.json_rpc(
            BadStatusClient(), "http://odoo/jsonrpc", "object", "execute_kw", []
        )
    assert "HTTP 500" in str(excinfo.value)


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def test_the_live_suite_is_not_collected_by_the_ordinary_run():
    """`pytest.ini` schliesst `tests/live` per PFAD aus, nicht per Marker.

    Ein `-m "not odoo19_live"` wuerde die Live-Tests still abwaehlen, und eine
    Live-Suite, die gar nicht mehr sammelt, laese sich in jedem gewoehnlichen
    Lauf als gruen. Der Pfadausschluss macht ihr Fehlen sichtbar.
    """
    ini = Path(__file__).resolve().parents[2] / "pytest.ini"
    text = ini.read_text(encoding="utf-8")
    assert "norecursedirs" in text, "pytest.ini does not exclude the live suite by path"
    assert "tests/live" in text.split("norecursedirs", 1)[1]
    assert "addopts" not in text, (
        "an addopts marker expression would deselect the live suite silently; "
        "the exclusion must stay a path exclusion"
    )


def test_every_live_test_carries_a_live_marker():
    """Ein Live-Test ohne Marker wuerde beim Sammeln der Live-Suite mitlaufen,
    aber bei einem gezielten `-m foundation_live` fehlen -- und niemand
    bemerkte, dass er nie gelaufen ist."""
    import re

    here = Path(__file__).resolve().parent
    for path in sorted(here.glob("test_odoo19_*.py")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^async def (test_\w+)", source, re.MULTILINE):
            prefix = source[: match.start()]
            tail = prefix.rsplit("\n\n", 1)[-1]
            assert "@pytest.mark.odoo19_live" in tail or "@pytest.mark.foundation_live" in tail, (
                f"{path.name}::{match.group(1)} carries no live marker"
            )


def test_the_fixtures_never_fall_back_to_the_local_instance():
    """Ein `local`-Default waere der eine Fehler, der die ganze Suite wertlos
    macht: jede Zwei-Datenbank-Behauptung wuerde dann gegen dieselbe Instanz
    laufen und bestehen."""
    source = Path(live_conftest.__file__).read_text(encoding="utf-8")
    body = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert '"local"' not in body and "'local'" not in body


def test_the_environment_stays_clean_for_other_suites():
    """Gegenprobe zu den monkeypatch-Tests oben: keine Live-Variable bleibt
    gesetzt, sonst faenden andere Suiten eine halb konfigurierte Umgebung."""
    assert not [name for name in live_conftest.REQUIRED if os.environ.get(name)]


def test_a_restricted_file_mode_is_actually_checked(tmp_path):
    secret = tmp_path / "ok-secret"
    secret.write_text("value", encoding="utf-8")
    secret.chmod(0o600)
    assert live_conftest._read_restricted_secret(str(secret), "TEST") == "value"
    assert not stat.S_IMODE(secret.stat().st_mode) & 0o077
