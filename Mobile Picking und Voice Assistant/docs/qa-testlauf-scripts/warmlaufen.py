"""Laedt beide Modelle mit den PRODUKTIV-Kontextgroessen vor.

Ohne das misst der Testlauf Ladezeiten statt Inferenz. Die Kontextgroesse muss
stimmen: `vision_client` ruft mit `num_ctx 8192`, `llm_client` mit der Vorgabe
4096. Waermt man mit der falschen Groesse, laedt ollama beim ersten echten
Aufruf neu -- und der Lauf beginnt mit 25-90 s Ladezeit.

Aufruf im Backend-Container:
    python /tmp/warmlaufen.py
"""
from __future__ import annotations

import json
import time
import urllib.request

ENDPOINT = "http://ollama:11434"

MODELLE = [
    ("qwen2.5:7b", 4096),
    ("gemma4:12b", 8192),
]


def warm(modell: str, num_ctx: int) -> None:
    koerper = {
        "model": modell,
        "prompt": "Sag OK.",
        "stream": False,
        "options": {
            "num_predict": 4,
            "temperature": 0,
            "num_thread": 8,
            "num_ctx": num_ctx,
        },
    }
    begonnen = time.time()
    antwort = urllib.request.urlopen(
        urllib.request.Request(
            f"{ENDPOINT}/api/generate",
            json.dumps(koerper).encode(),
            {"Content-Type": "application/json"},
        ),
        timeout=900,
    )
    daten = json.loads(antwort.read())
    print(
        f"{modell} ctx={num_ctx}: wanduhr={time.time()-begonnen:.1f}s "
        f"laden={daten.get('load_duration', 0)/1e9:.1f}s",
        flush=True,
    )


if __name__ == "__main__":
    for modell, ctx in MODELLE:
        warm(modell, ctx)
