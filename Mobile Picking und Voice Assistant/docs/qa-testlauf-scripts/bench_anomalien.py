"""Misst die Laenge der `anomalies`-Eintraege der Schadenspruefung.

Ruft `gemma4:12b` mit dem Produktiv-Prompt und der Produktiv-Bildaufbereitung
aus dem Backend gegen eine Reihe von Fotos auf und zaehlt, aus wievielen
Woertern jeder Einzelbefund besteht. Damit laesst sich eine Aenderung am
`DAMAGE_PROMPT` pruefen, ohne die ganze Kette zu fahren.

Wichtig: Das Modell ist hier NICHT stabil. Am 2026-09-15 lieferte es auf
dasselbe Foto einmal fuenf ganze Saetze (Lauf 8, QA/0373) und einmal zwei
Woerter -- bei `temperature: 0`. Ein einzelner Messpunkt taugt deshalb nicht
als Beleg; immer mehrere Fotos messen und die Verteilung ansehen.

Aufruf im Backend-Container:
    PYTHONPATH=/app python /tmp/bench_anomalien.py /tmp/foto1.jpg /tmp/foto2.jpg ...
"""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.request

from app.services.assessment_media import DAMAGE_MAX_EDGE, prepare_image
from app.services.vision_client import DAMAGE_PROMPT

ENDPOINT = "http://ollama:11434"


def eine_datei(pfad: str) -> list[int]:
    roh = open(pfad, "rb").read()
    bild = base64.b64encode(prepare_image(roh, max_edge=DAMAGE_MAX_EDGE)).decode("ascii")
    payload = {
        "model": "gemma4:12b",
        "prompt": DAMAGE_PROMPT,
        "images": [bild],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_ctx": 8192, "num_thread": 8},
    }
    begonnen = time.monotonic()
    antwort = urllib.request.urlopen(
        urllib.request.Request(
            f"{ENDPOINT}/api/generate",
            json.dumps(payload).encode(),
            {"Content-Type": "application/json"},
        ),
        timeout=600,
    )
    daten = json.loads(antwort.read())
    dauer = time.monotonic() - begonnen
    parsed = json.loads(daten.get("response") or "{}")
    anomalien = [str(a) for a in (parsed.get("anomalies") or [])]
    woerter = [len(a.split()) for a in anomalien]

    name = pfad.rsplit("/", 1)[-1]
    print(
        f"{name:<24} dauer={dauer:5.1f}s damaged={str(parsed.get('damaged')):<5} "
        f"befunde={len(anomalien)} woerter={woerter}",
        flush=True,
    )
    for a in anomalien:
        print(f"    - {a}", flush=True)
    return woerter


def main() -> None:
    alle: list[int] = []
    for pfad in sys.argv[1:]:
        alle.extend(eine_datei(pfad))
    if alle:
        lang = [w for w in alle if w > 3]
        print(
            f"\nZUSAMMEN: {len(alle)} Befunde, laengster {max(alle)} Woerter, "
            f"Schnitt {sum(alle)/len(alle):.1f}, ueber drei Woertern: {len(lang)}",
            flush=True,
        )


if __name__ == "__main__":
    main()
