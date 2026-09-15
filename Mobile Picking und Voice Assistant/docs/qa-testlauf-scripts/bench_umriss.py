"""Misst, ob ein Umriss-Feld im Schadensprompt die fehlende Ecke sichtbar macht.

Lauf 15 hat die Luecke gezeigt: `surface_description` fragt nur nach der
OBERFLAECHE. Ein sauber abgebrochenes Eck laesst jede Oberflaeche glatt, also
sagen Katalogbild und Meldefoto beide "glatt" -- und `compare_condition`
vergleicht genau diese beiden Texte. Der Zustandsvergleich kann nicht sehen,
was die Beschreibung nie erfasst hat.

Dieses Skript stellt den Produktiv-Prompt gegen einen Prompt mit einem
zusaetzlichen Feld `outline_description` und faehrt beide ueber dieselben
Fotos. Zwei Fragen:

  1. Nennt das neue Feld die fehlende Ecke (Fotos aus Lauf 15)?
  2. Bleibt `damaged` auf den beschaedigten Teilen unveraendert true
     (Fotos aus den Laeufen 11 bis 14)? Ein Prompt, der die Schadenserkennung
     verschlechtert, ist den Gewinn nicht wert.

Aufruf im Backend-Container:
    python /tmp/bench_umriss.py /tmp/fotos/run15_01.jpg /tmp/fotos/run13_01.jpg ...
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/app")

from app.services.assessment_media import prepare_image  # noqa: E402
from app.services.vision_client import DAMAGE_PROMPT  # noqa: E402

ENDPOINT = "http://ollama:11434"
MODELL = "gemma4:12b"
NUM_CTX = 8192

# Der Produktiv-Prompt mit EINEM zusaetzlichen Feld. Die Entscheidungsregel
# darunter bleibt Wort fuer Wort stehen -- geaendert wird nur, WAS beschrieben
# wird, nicht WANN etwas als Schaden gilt.
UMRISS_PROMPT = DAMAGE_PROMPT.replace(
    '  "anomalies": array of short strings',
    '  "outline_description": describe the outline and completeness of the part: '
    "is the body complete with all corners and edges present, or is a corner, "
    "edge or section missing? A cleanly broken-off corner leaves a smooth face "
    "but an incomplete outline.,\n"
    '  "anomalies": array of short strings',
)


def frage(bild: bytes, prompt: str) -> tuple[dict | None, float]:
    import base64

    koerper = {
        "model": MODELL,
        "prompt": prompt,
        "images": [base64.b64encode(bild).decode("ascii")],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_thread": 8, "num_ctx": NUM_CTX},
    }
    begonnen = time.time()
    antwort = urllib.request.urlopen(
        urllib.request.Request(
            f"{ENDPOINT}/api/generate",
            json.dumps(koerper).encode(),
            {"Content-Type": "application/json"},
        ),
        timeout=600,
    )
    daten = json.loads(antwort.read())
    dauer = time.time() - begonnen
    try:
        return json.loads(daten.get("response") or ""), dauer
    except json.JSONDecodeError:
        return None, dauer


async def main() -> None:
    pfade = [Path(p) for p in sys.argv[1:]]
    if not pfade:
        raise SystemExit("Aufruf: bench_umriss.py <foto> [<foto> ...]")

    for pfad in pfade:
        roh = pfad.read_bytes()
        bild = prepare_image(roh, max_edge=1024)
        print(f"\n=== {pfad.name}")
        for name, prompt in (("PRODUKTIV", DAMAGE_PROMPT), ("MIT UMRISS", UMRISS_PROMPT)):
            parsed, dauer = frage(bild, prompt)
            if parsed is None:
                print(f"  {name:10} keine verwertbare Antwort ({dauer:.1f}s)")
                continue
            print(
                f"  {name:10} damaged={str(parsed.get('damaged')):5} "
                f"anomalies={parsed.get('anomalies')} ({dauer:.1f}s)"
            )
            print(f"             surface: {str(parsed.get('surface_description'))[:150]}")
            if "outline_description" in parsed:
                print(f"             outline: {str(parsed.get('outline_description'))[:150]}")


if __name__ == "__main__":
    asyncio.run(main())
