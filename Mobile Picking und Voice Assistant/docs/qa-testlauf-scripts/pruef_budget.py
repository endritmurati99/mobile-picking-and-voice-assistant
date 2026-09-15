"""Selbstpruefung der Zeitschranken der Schadenspruefung.

Laeuft ohne Modelle, ohne Odoo, ohne n8n -- nur `_check_damage` gegen ein
Bildmodell aus Papier. Sie beantwortet die eine Frage, an der Lauf 9
gescheitert ist: wird ein Bildaufruf noch GESTARTET, der nicht mehr
hineinpasst?

    docker cp .claude/skills/qa-testlauf/scripts/pruef_budget.py mobilepickingundvoiceassistant-backend-1:/tmp/
    docker exec -e PYTHONPATH=/app mobilepickingundvoiceassistant-backend-1 python /tmp/pruef_budget.py
"""

import asyncio
import time

from app.config import settings
from app.routers.n8n_v2 import _check_damage
from app.services.vision_client import (
    DamageCheck,
    _DAUERN,
    geschaetzte_schadensdauer,
    notiere_schadensdauer,
)

SCHAETZUNG = settings.vision_call_estimate_ms / 1000.0


class PapierModell:
    """Zaehlt Aufrufe und braucht dafuer `dauer` Sekunden."""

    def __init__(self, dauer: float = 0.0, damaged: bool = True):
        self.dauer = dauer
        self.damaged = damaged
        self.aufrufe = 0

    async def inspect_damage(self, _candidate):
        self.aufrufe += 1
        await asyncio.sleep(self.dauer)
        return DamageCheck(
            ok=True, damaged=self.damaged, anomalies=("Riss",), description="Riss"
        )


async def lauf(anzahl: int, rest: float, dauer: float = 0.0, garantiert: bool = False):
    vision = PapierModell(dauer=dauer)
    lines: list[str] = []
    damage, ungeprueft = await _check_damage(
        vision,
        llm=None,
        candidates=[b"x"] * anzahl,
        lines=lines,
        deadline=time.monotonic() + rest,
        garantiert=garantiert,
    )
    return vision.aufrufe, damage, ungeprueft, lines


async def main() -> None:
    # 1. Reichlich Zeit: jedes Foto wird angesehen.
    aufrufe, damage, ungeprueft, _ = await lauf(3, rest=SCHAETZUNG * 5)
    assert aufrufe == 3, aufrufe
    assert damage == "damaged", damage
    assert ungeprueft == 0, ungeprueft

    # 2. DER FALL AUS LAUF 9: die Restzeit ist positiv, reicht aber nicht fuer
    #    einen ganzen Aufruf. Frueher startete er trotzdem. Jetzt nicht mehr.
    knapp = SCHAETZUNG / 2
    aufrufe, damage, ungeprueft, lines = await lauf(2, rest=knapp)
    assert aufrufe == 0, f"Aufruf gestartet, der nicht hineinpasst: {aufrufe}"
    assert ungeprueft == 2, ungeprueft
    assert damage == "unavailable", damage
    assert any("Zeitbudget" in zeile for zeile in lines), lines

    # 3. Das erste Foto reicht, das zweite nicht mehr: einer laeuft, einer
    #    bleibt liegen und wird GENANNT. Der erste Aufruf verbraucht dafuer
    #    0,4 s echte Zeit -- genau die fehlen dem zweiten.
    aufrufe, damage, ungeprueft, lines = await lauf(
        2, rest=SCHAETZUNG + 0.2, dauer=0.4
    )
    assert aufrufe == 1, aufrufe
    assert ungeprueft == 1, ungeprueft
    assert damage == "damaged", damage
    # Die Zeile "N weitere ungeprueft." schreibt `_collect_photo_finding` aus
    # dieser Zahl -- hier zaehlt nur, dass die Zahl stimmt.

    # 4. Der garantierte Aufruf startet auch bei zu knapper Restzeit -- eine
    #    Bildpruefung, die stillschweigend gar nichts ansieht, waere schlimmer.
    aufrufe, _, _, _ = await lauf(1, rest=knapp, garantiert=True)
    assert aufrufe == 1, aufrufe

    # 5. Aber auch er ueberlebt die Frist nicht: ein Aufruf, der laenger
    #    braucht als die Restzeit, wird gekappt statt in einen abgeschnittenen
    #    Kanal hinein zu rechnen (Lauf 9: 65,6 s Rechenzeit ohne Ergebnis).
    aufrufe, damage, ungeprueft, lines = await lauf(
        1, rest=0.2, dauer=1.0, garantiert=True
    )
    assert aufrufe == 1, aufrufe
    assert damage == "unavailable", damage
    assert ungeprueft == 1, ungeprueft

    # 6. Der gleitende Schaetzwert. Ohne Messungen gilt die Vorgabe; ab drei
    #    Messungen der 80-%-Wert der letzten acht.
    _DAUERN.pop("pruefmodell", None)
    assert geschaetzte_schadensdauer("pruefmodell", 60.0) == 60.0
    for wert in (42.0, 59.0):
        notiere_schadensdauer("pruefmodell", wert)
    assert geschaetzte_schadensdauer("pruefmodell", 60.0) == 60.0, "zwei Werte genuegen nicht"
    notiere_schadensdauer("pruefmodell", 83.0)
    # sortiert 42, 59, 83 -> ceil(0.8*3)-1 = 2 -> 83
    assert geschaetzte_schadensdauer("pruefmodell", 60.0) == 83.0

    # 7. DER FALL AUS LAUF 11: ein einzelner Ausreisser darf die Schaetzung
    #    nicht dauerhaft bestimmen. Nach fuenf normalen Aufrufen liegt sie
    #    wieder im Band, nicht auf dem Hoechstwert.
    for wert in (59.0, 47.0, 44.0, 52.0, 58.0):
        notiere_schadensdauer("pruefmodell", wert)
    schaetzung = geschaetzte_schadensdauer("pruefmodell", 60.0)
    assert schaetzung < 83.0, f"Ausreisser bestimmt die Schaetzung weiter: {schaetzung}"
    assert schaetzung >= 58.0, f"Schaetzung zu tief: {schaetzung}"

    # 8. Nur die letzten acht zaehlen.
    assert len(_DAUERN["pruefmodell"]) == 8, len(_DAUERN["pruefmodell"])
    _DAUERN.pop("pruefmodell", None)

    print(
        f"alle Pruefungen bestanden (Vorgabe je Aufruf: {SCHAETZUNG:.0f} s, "
        f"gleitender Wert ab {3} Messungen)"
    )


if __name__ == "__main__":
    asyncio.run(main())
