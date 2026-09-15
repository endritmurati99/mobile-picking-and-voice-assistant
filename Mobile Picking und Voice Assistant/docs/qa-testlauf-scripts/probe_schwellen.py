"""Fragt den Einbettungsdienst mit einer Reihe von Fotos ab und sammelt die
Spitzenwerte -- die Datengrundlage fuer jede Diskussion ueber `FREMD_SCHWELLE`.

Jede Zeile der Eingabe: <pfad>;<erwartete_sku>;<bildwelt>
`bildwelt` ist frei, dient nur der Gruppierung in der Auswertung.

Aufruf im Backend-Container:
    PYTHONPATH=/app python /tmp/probe_schwellen.py /tmp/liste.txt
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.request

ENDPOINT = "http://embed:8000"


def abgleich(pfad: str, erwartet: str) -> dict:
    b64 = base64.b64encode(open(pfad, "rb").read()).decode("ascii")
    anfrage = {"bild_b64": b64, "erwartet": erwartet}
    antwort = urllib.request.urlopen(
        urllib.request.Request(
            f"{ENDPOINT}/abgleich",
            json.dumps(anfrage).encode(),
            {"Content-Type": "application/json"},
        ),
        timeout=300,
    )
    return json.loads(antwort.read())


def main() -> None:
    zeilen = [z.strip() for z in open(sys.argv[1], encoding="utf-8") if z.strip()]
    gruppen: dict[str, list[float]] = {}
    print(f"{'Datei':<28}{'Welt':<14}{'Urteil':<10}{'Platz1':<10}{'Wert':>8}{'Abstand':>9}  erwartet")
    for zeile in zeilen:
        pfad, erwartet, welt = zeile.split(";")
        erg = abgleich(pfad, erwartet)
        rang = erg.get("rang") or []
        spitze = rang[0] if rang else {}
        wert = float(spitze.get("wert", 0.0))
        platz_erwartet = next(
            (i + 1 for i, r in enumerate(rang) if r.get("kennung") == erwartet), None
        )
        name = pfad.rsplit("/", 1)[-1]
        print(
            f"{name:<28}{welt:<14}{erg.get('urteil',''):<10}"
            f"{str(spitze.get('kennung','')):<10}{wert:8.4f}"
            f"{float(erg.get('abstand',0)):9.4f}  "
            f"{erwartet} auf Platz {platz_erwartet}",
            flush=True,
        )
        gruppen.setdefault(welt, []).append(wert)

    print("\nSpitzenwerte je Bildwelt:")
    for welt, werte in gruppen.items():
        print(
            f"  {welt:<14} n={len(werte):<3} min={min(werte):.4f} "
            f"max={max(werte):.4f} schnitt={sum(werte)/len(werte):.4f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
