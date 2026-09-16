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

# Beschrifteter Satz statt eines Einzelfalls: ein Modellwechsel laesst sich an
# EINER Meldung nicht entscheiden, und `_SYSTEM_PROMPT` ist auf genau die
# Grenzfaelle getrimmt, die hier stehen. Die vier Beispiele AUS dem Prompt
# fehlen bewusst -- wer sie mitmisst, misst das Auswendiglernen.
#
# Erwartet wird auch `grundlage`: `reconcile` haengt daran. Ein richtiges
# Urteil mit falscher Grundlage laeuft an der Totalschaden-Regel vorbei.
FAELLE = [
    # Schwere nur behauptet, nicht ausgesprochen -> quarantine/annahme.
    ("Stein kaputt, liegt lose im Fach.", "quarantine", "annahme"),
    ("Ware defekt.", "quarantine", "annahme"),
    ("Teil beschaedigt, keine naeheren Angaben.", "quarantine", "annahme"),
    ("Feuchtigkeitsflecken am Karton, Inhalt nicht geprueft.", "quarantine", "annahme"),
    ("Fremdkoerper im Beutel gefunden.", "quarantine", "annahme"),
    # Unbrauchbarkeit ausgesprochen -> scrap/wortlaut.
    ("Stein in mehrere Teile zerbrochen, nicht mehr zu retten.", "scrap", "wortlaut"),
    ("Baustein zersplittert, Bruchstuecke im Karton verteilt.", "scrap", "wortlaut"),
    # Mangel benannt und mit einem Handgriff zu beheben -> rework/wortlaut.
    ("Umverpackung eingedrueckt, Ware selbst unversehrt.", "rework", "wortlaut"),
    ("Etikett fehlt, Artikel einwandfrei.", "rework", "wortlaut"),
    ("Kleinteil fehlt in der Tuete, Rest vollstaendig.", "rework", "wortlaut"),
    # Kein Mangel -> sellable/wortlaut.
    ("Sichtpruefung ohne Befund, Ware einwandfrei.", "sellable", "wortlaut"),
    ("Artikel vollstaendig und ohne Mangel, Meldung war ein Irrtum.", "sellable", "wortlaut"),
]

KONTEXT = {"priority": "0", "photo_count": 1, "product_id": 72, "location_id": 14}


async def einen_fall(
    http: httpx.AsyncClient, client: LlmClient, model: str, beschreibung: str
) -> tuple[dict, float]:
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_thread": NUM_THREAD, "num_ctx": NUM_CTX},
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": client._build_user_prompt(description=beschreibung, **KONTEXT),
            },
        ],
    }
    begonnen = time.monotonic()
    antwort = await http.post(f"{ENDPOINT}/api/chat", json=payload)
    antwort.raise_for_status()
    daten = antwort.json()
    return daten, time.monotonic() - begonnen


async def messen(model: str) -> None:
    client = LlmClient(endpoint=ENDPOINT, model=model)
    treffer = grundlagen = 0
    dauern: list[float] = []
    print(f"\n=== {model} ===", flush=True)
    async with httpx.AsyncClient(timeout=httpx.Timeout(900.0)) as http:
        for beschreibung, soll, soll_grund in FAELLE:
            try:
                daten, wanduhr = await einen_fall(http, client, model, beschreibung)
                inhalt = json.loads(daten["message"]["content"])
            except Exception as exc:  # noqa: BLE001 - ein Ausfall ist ein Messwert
                print(f"  FEHLER  {beschreibung[:48]!r}: {exc}", flush=True)
                continue
            # Die erste Messung enthaelt die Ladezeit; sie gehoert nicht in den
            # Median der Inferenz, aber sehr wohl ins Protokoll.
            laden = daten.get("load_duration", 0) / 1e9
            dauern.append(wanduhr - laden)
            ist = str(inhalt.get("disposition"))
            ist_grund = str(inhalt.get("grundlage"))
            ok = ist == soll
            treffer += ok
            grundlagen += ist_grund == soll_grund
            marke = "ok  " if ok else "FALSCH"
            print(
                f"  {marke} {ist:<10} (soll {soll:<10}) grundlage={ist_grund:<8}"
                f"(soll {soll_grund:<8}) {wanduhr:5.1f}s laden={laden:4.1f}s  "
                f"{beschreibung[:44]}",
                flush=True,
            )
            if not ok:
                print(f"         beleg={inhalt.get('belegstelle')!r}", flush=True)
    dauern.sort()
    median = dauern[len(dauern) // 2] if dauern else 0.0
    print(
        f"  ERGEBNIS {model}: Disposition {treffer}/{len(FAELLE)}, "
        f"Grundlage {grundlagen}/{len(FAELLE)}, Median ohne Laden {median:.1f}s",
        flush=True,
    )


async def main() -> None:
    for model in sys.argv[1:] or ["qwen2.5:7b", "gemma4:12b"]:
        await messen(model)


if __name__ == "__main__":
    asyncio.run(main())
