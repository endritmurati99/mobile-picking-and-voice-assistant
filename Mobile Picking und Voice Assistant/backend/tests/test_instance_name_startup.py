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
