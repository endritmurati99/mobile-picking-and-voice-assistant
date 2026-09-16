"""Misst den Speicherbedarf bei drei gleichzeitig geladenen Modellen.

Laedt sie einzeln mit den PRODUKTIV-Kontextgroessen und liest nach jedem
Schritt den Speicherstand. Die Modellgroesse aus `ollama ps` ist NICHT der
Speicherbedarf -- der Kontext kommt hinzu.

Aufruf im Backend-Container:  python /tmp/mess_speicher.py
"""
from __future__ import annotations

import json
import time
import urllib.request

ENDPOINT = "http://ollama:11434"
MODELLE = [
    ("qwen2.5:1.5b", 4096, "Sprache"),
    ("qwen2.5:7b", 4096, "Text"),
    ("gemma4:12b", 8192, "Bild"),
]


def laden(modell: str, num_ctx: int) -> float:
    koerper = {
        "model": modell, "prompt": "Sag OK.", "stream": False,
        "options": {"num_predict": 4, "temperature": 0, "num_thread": 8, "num_ctx": num_ctx},
    }
    begonnen = time.time()
    antwort = urllib.request.urlopen(
        urllib.request.Request(
            f"{ENDPOINT}/api/generate", json.dumps(koerper).encode(),
            {"Content-Type": "application/json"},
        ), timeout=900,
    )
    daten = json.loads(antwort.read())
    return time.time() - begonnen, daten.get("load_duration", 0) / 1e9


def geladen() -> list[dict]:
    antwort = urllib.request.urlopen(f"{ENDPOINT}/api/ps", timeout=30)
    return json.loads(antwort.read()).get("models", [])


if __name__ == "__main__":
    for modell, ctx, rolle in MODELLE:
        wanduhr, load = laden(modell, ctx)
        drin = geladen()
        summe = sum(m.get("size", 0) for m in drin) / 1e9
        print(
            f"{rolle:<8} {modell:<14} ctx={ctx:<5} wanduhr={wanduhr:6.1f}s "
            f"laden={load:5.1f}s | geladen: {len(drin)} Modelle, "
            f"Summe {summe:.1f} GB -> " + ", ".join(m["name"] for m in drin),
            flush=True,
        )
