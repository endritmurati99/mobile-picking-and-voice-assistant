"""Startpruefung: jede Odoo-Instanz muss sich so nennen, wie das Backend sie kennt.

Der Name im Envelope (`source.odoo_instance`) entscheidet, in welche Datenbank
ein Callback zurueckschreibt. Waere er falsch, landete die Bewertung von Lager 2
stillschweigend in Lager 1 -- kein Fehler, den man spaeter noch sieht.
"""
import pytest

from app.main import verify_instance_names


class FakeOdoo:
    def __init__(self, reported):
        self.reported = reported
        self.calls = []

    async def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method))
        if isinstance(self.reported, Exception):
            raise self.reported
        return self.reported


def factory_for(mapping):
    clients = {name: FakeOdoo(value) for name, value in mapping.items()}
    return clients.__getitem__, clients


@pytest.mark.asyncio
async def test_matching_names_pass():
    factory, clients = factory_for({"local": "local", "lager-2": "lager-2"})
    await verify_instance_names(factory, ["local", "lager-2"])
    assert clients["local"].calls == [
        ("picking.assistant.api.mixin", "api_instance_name")
    ]


@pytest.mark.asyncio
async def test_swapped_name_is_a_startup_error():
    factory, _ = factory_for({"local": "lager-2"})
    with pytest.raises(RuntimeError, match="local"):
        await verify_instance_names(factory, ["local"])


@pytest.mark.asyncio
async def test_unreachable_parameter_is_a_startup_error():
    factory, _ = factory_for({"local": RuntimeError("parameter missing")})
    with pytest.raises(RuntimeError, match="local"):
        await verify_instance_names(factory, ["local"])


@pytest.mark.asyncio
async def test_every_instance_is_checked_not_just_the_first():
    factory, clients = factory_for({"local": "local", "lager-2": "verwechselt"})
    with pytest.raises(RuntimeError, match="lager-2"):
        await verify_instance_names(factory, ["local", "lager-2"])
    assert clients["lager-2"].calls


class SlowStartingOdoo:
    """Antwortet die ersten `failures` Male gar nicht -- so verhaelt sich Odoo,
    solange es nach einem Neustart noch Registry und Addons laedt."""

    def __init__(self, failures, then):
        self.failures = failures
        self.then = then
        self.calls = 0

    async def execute_kw(self, model, method, args, kwargs=None):
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("All connection attempts failed")
        return self.then


@pytest.mark.asyncio
async def test_cold_start_waits_for_a_late_odoo():
    """Der Fall vom 2026-08-06: Docker Desktop startet alles gleichzeitig neu,
    das Backend ist vor Odoo da. Ohne Wartezeit brach der Start ab und der
    Stack blieb liegen."""
    client = SlowStartingOdoo(failures=2, then="local")
    await verify_instance_names(lambda _: client, ["local"], wait_seconds=30)
    assert client.calls == 3


@pytest.mark.asyncio
async def test_wrong_name_fails_at_once_even_with_a_long_wait():
    """Die Zusage, die die Wartezeit NICHT aufweichen darf: eine Instanz, die
    sich falsch nennt, ist falsch konfiguriert. Warten macht das nicht besser,
    und ein Envelope mit falschem `source.odoo_instance` schreibt in die
    falsche Datenbank zurueck."""
    factory, clients = factory_for({"local": "lager-2"})
    with pytest.raises(RuntimeError, match="nennt sich selbst"):
        await verify_instance_names(factory, ["local"], wait_seconds=3600)
    assert len(clients["local"].calls) == 1


@pytest.mark.asyncio
async def test_wait_is_bounded():
    """Wer nie antwortet, bringt den Start trotzdem zu Fall -- sonst haengt das
    Backend still statt sichtbar zu scheitern."""
    factory, _ = factory_for({"local": ConnectionError("nichts da")})
    with pytest.raises(RuntimeError, match="meldet keinen Instanznamen"):
        await verify_instance_names(factory, ["local"], wait_seconds=0.05)
