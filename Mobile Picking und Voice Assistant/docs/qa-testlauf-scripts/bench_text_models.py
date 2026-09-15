"""Misst Textmodelle unter den Bedingungen der Produktivkette.

Nimmt Systemprompt, Nutzerprompt und Optionen aus
`backend/app/services/llm_client.py`, damit die Zahlen mit den Testlaeufen
vergleichbar sind. Nur das Modell wird variiert.

Aufruf im Backend-Container:
    python /tmp/bench_text_models.py qwen2.5:7b gemma4:12b
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx

from app.services.llm_client import LlmClient, _SYSTEM_PROMPT

ENDPOINT = "http://ollama:11434"
NUM_THREAD = 8
# Gleiche Kontextgroesse wie der geladene Runner, sonst laedt ollama das Modell
# neu und die Messung enthaelt 90 s Ladezeit statt Inferenz.
NUM_CTX = 8192

# Meldung aus Lauf 3, damit die Messung an einem echten Fall haengt.
MELDUNG = {
    "description": (
        "Artikel beschaedigt: Brick 1x2x2 weiss (SKU 6101121), Regal A-02. "
        "Noppe abgebrochen, Riss in der Seitenwand. Nicht versandfaehig. "
        "Foto angehaengt."
    ),
    "priority": "0",
    "photo_count": 1,
    "product_id": 72,
    "location_id": 14,
}


async def messen(model: str) -> None:
    client = LlmClient(endpoint=ENDPOINT, model=model)
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_thread": NUM_THREAD, "num_ctx": NUM_CTX},
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": client._build_user_prompt(**MELDUNG)},
        ],
    }
    begonnen = time.monotonic()
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as http:
        antwort = await http.post(f"{ENDPOINT}/api/chat", json=payload)
    antwort.raise_for_status()
    daten = antwort.json()
    wanduhr = time.monotonic() - begonnen

    laden = daten.get("load_duration", 0) / 1e9
    erzeugen = daten.get("eval_duration", 0) / 1e9
    token = daten.get("eval_count", 0)
    inhalt = json.loads(daten["message"]["content"])

    print(
        f"{model}: wanduhr={wanduhr:.1f}s laden={laden:.1f}s "
        f"erzeugen={erzeugen:.1f}s token={token} "
        f"rate={token / erzeugen if erzeugen else 0:.2f} tok/s",
        flush=True,
    )
    print(f"  urteil={inhalt.get('disposition')} konfidenz={inhalt.get('confidence')}", flush=True)
    print(f"  begruendung={str(inhalt.get('reason'))[:120]}", flush=True)


async def main() -> None:
    for model in sys.argv[1:] or ["qwen2.5:7b", "gemma4:12b"]:
        await messen(model)


if __name__ == "__main__":
    asyncio.run(main())
