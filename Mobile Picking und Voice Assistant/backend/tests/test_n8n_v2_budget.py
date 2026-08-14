"""Das Zeitbudget muss WAEHREND eines Bildaufrufs binden, nicht nur davor.

Bis zum 2026-08-14 wurde die Grenze ausschliesslich VOR jedem Aufruf geprueft.
Danach lief nur noch die Lesegrenze des einzelnen Aufrufs (200 s), und die
kennt das Gesamtbudget nicht. An QA/0323 live vorgefuehrt: die Schadenspruefung
startete mit 69 s Restbudget -- die Pruefung davor war also korrekt -- und lief
dann 125 s. Das Budget riss mit dem Aufruf in der Luft, n8n schnitt nach 270 s
die Verbindung, und `_collect_photo_finding` kam nie zurueck. Der bereits
FERTIGE Artikelbefund ging mit unter; in Odoo stand "assessment unavailable"
ueber einer leeren Fotoanalyse.

Geprueft wird hier auf Funktionsebene und mit kurzen Zeiten. Die Zeitgrenze ist
Verhalten, kein Zahlenwert -- ein Test, der 200 s wartet, prueft die Geduld des
Rechners und nicht den Code.
"""
import asyncio
import base64
import io
import time

import pytest
from PIL import Image

from app.routers import n8n_v2
from app.services.vision_client import ArticleDescription, DamageCheck

SIEHT_TEIL = ArticleDescription(
    ok=True, text="toy building brick, yellow, 2x2 studs", is_a_product=True
)
HEIL = DamageCheck(ok=True, damaged=False, anomalies=(), description="smooth")


def _jpeg_b64() -> str:
    puffer = io.BytesIO()
    Image.new("RGB", (32, 32), (255, 200, 0)).save(puffer, format="JPEG")
    return base64.b64encode(puffer.getvalue()).decode()


def _jpeg() -> bytes:
    return base64.b64decode(_jpeg_b64())


class LangsameVision:
    """Antwortet erst nach `haengt` Sekunden -- ab dem `ab_aufruf`-ten Aufruf."""

    def __init__(self, haengt: float = 5.0, ab_aufruf: int = 1):
        self._haengt = haengt
        self._ab = ab_aufruf
        self.damage_calls = 0
        self.describe_calls = 0

    async def _vielleicht_warten(self, nummer: int) -> None:
        if nummer >= self._ab:
            await asyncio.sleep(self._haengt)

    async def describe(self, image):
        self.describe_calls += 1
        await self._vielleicht_warten(self.describe_calls)
        return SIEHT_TEIL

    async def inspect_damage(self, candidate):
        self.damage_calls += 1
        await self._vielleicht_warten(self.damage_calls)
        return HEIL


class StummesTextmodell:
    async def compare_articles(self, **_):
        raise AssertionError("darf nach einem Budgetriss nicht mehr gefragt werden")

    async def compare_condition(self, **_):
        raise AssertionError("darf nach einem Budgetriss nicht mehr gefragt werden")


@pytest.mark.anyio
async def test_a_damage_call_that_overruns_the_budget_is_cut_off():
    """Der Fall QA/0323: der Aufruf laeuft, das Budget reisst, niemand schaut hin."""
    vision = LangsameVision(haengt=30.0)
    lines: list[str] = []
    begonnen = time.monotonic()

    damage, ungeprueft = await n8n_v2._check_damage(
        vision, StummesTextmodell(), [_jpeg()], lines,
        deadline=time.monotonic() + 0.05, garantiert=False,
    )

    assert damage == "unavailable"
    assert ungeprueft == 1
    assert any("Zeitbudget erschoepft" in zeile for zeile in lines)
    # Zurueck, sobald die Grenze reisst -- nicht erst, wenn das Modell fertig ist.
    assert time.monotonic() - begonnen < 5


@pytest.mark.anyio
async def test_the_guaranteed_first_call_is_never_cut_off():
    """Ein Budget, das gar keinen Bildaufruf zulaesst, waere eine abgeschaltete
    Bildpruefung unter anderem Namen. Der garantierte Aufruf laeuft auch bei
    laengst abgelaufener Grenze -- und zwar zu Ende."""
    vision = LangsameVision(haengt=0.05)
    lines: list[str] = []

    damage, ungeprueft = await n8n_v2._check_damage(
        vision, StummesTextmodell(), [_jpeg()], lines,
        deadline=time.monotonic() - 10, garantiert=True,
    )

    assert vision.damage_calls == 1
    assert damage == "intact"
    assert ungeprueft == 0


@pytest.mark.anyio
async def test_a_hanging_catalogue_description_does_not_swallow_the_photo():
    """Reisst die Zeit beim ZWEITEN Bild, bleibt wenigstens im Klartext stehen,
    was auf dem Meldefoto zu sehen war."""
    vision = LangsameVision(haengt=30.0, ab_aufruf=2)
    lines: list[str] = []
    media = {"reference_image_b64": _jpeg_b64(), "product_label": "[6023350] Brick"}
    begonnen = time.monotonic()

    article = await n8n_v2._check_article(
        vision, StummesTextmodell(), media, _jpeg(), lines,
        deadline=time.monotonic() + 0.2,
    )

    assert article == "unavailable"
    assert any("Zeitbudget" in zeile for zeile in lines)
    assert any(SIEHT_TEIL.text in zeile for zeile in lines)
    assert time.monotonic() - begonnen < 5


@pytest.mark.anyio
async def test_a_hanging_reference_condition_leaves_the_damage_verdict_alone():
    """Der Zustandsvergleich darf beim Budgetriss nichts drehen. Ein
    ausgefallener Vergleich ist kein Freispruch -- dieselbe Regel wie bei jedem
    anderen Fehlerpfad in `_zustandsvergleich`."""
    n8n_v2._SOLL_BEFUNDE.clear()
    vision = LangsameVision(haengt=30.0)
    beschaedigt = DamageCheck(
        ok=True, damaged=True, anomalies=("torn",), description="a torn corner"
    )

    damage, zeile = await n8n_v2._zustandsvergleich(
        vision=vision, llm=StummesTextmodell(), reference=_jpeg(),
        befunde=[beschaedigt], damage="damaged",
        deadline=time.monotonic() + 0.05, product_label="[6023350] Brick",
    )

    assert damage == "damaged"
    assert zeile is not None and "Zeitbudget erschoepft" in zeile
