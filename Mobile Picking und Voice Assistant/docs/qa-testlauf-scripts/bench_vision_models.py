"""Misst Vision-Modelle unter denselben Bedingungen wie die Produktivkette.

Verwendet die Prompts, Optionen und den Endpunkt aus
`backend/app/services/vision_client.py`, damit die Zahlen mit den Werten aus
den Testlaeufen vergleichbar sind.

Aufruf im Backend-Container:
    python /tmp/bench_vision_models.py /tmp/foto.jpg modell_a modell_b ...
"""

from __future__ import annotations

import base64
import json
import sys
import time

import httpx

ENDPOINT = "http://ollama:11434"
NUM_CTX = 8192

DESCRIBE_PROMPT = (
    "Describe the single object in this image factually. Ignore the background, "
    "the lighting and any hand holding it.\n"
    "Answer strictly as JSON with these keys, in this order:\n"
    '  "object_type": what kind of thing it is in two or three words '
    "(for example \"toy building brick\", \"cardboard box\", \"dog\", \"person\"),\n"
    '  "colour": the dominant colour or colours,\n'
    '  "shape": size and shape in one short phrase,\n'
    '  "markings": printed images, logos, letters or studs, or "none",\n'
    '  "is_a_product": true if this is a manufactured article, false if it is a '
    "living being, a person, a room or a landscape\n\n"
    "Do not guess and do not compare with anything - describe only what you see."
)

DAMAGE_PROMPT = (
    "You inspect a moulded plastic part before shipping.\n"
    "Answer strictly as JSON with these keys, in this order:\n"
    '  "surface_description": describe the surface: is it smooth and continuous '
    "everywhere, or is there a region that looks torn, split, gouged, ragged or "
    "broken open?,\n"
    '  "anomalies": array of short strings, ONE TO THREE WORDS EACH, for '
    "every region that breaks the smooth surface "
    '(for example "crack", "broken edge", "missing stud"). '
    "Empty array if the surface is continuous everywhere.,\n"
    '  "damaged": true or false,\n'
    '  "confidence": number 0.0 to 1.0\n\n'
    "Decisive rule: a ragged, torn or gouged area on an otherwise smooth moulded "
    "surface is DAMAGE, never decoration or a design feature. Printed logos, "
    "smooth colour changes and reflections are NOT damage. "
    "An item whose surface is continuous everywhere must get damaged false."
)


def ask(model: str, prompt: str, bild_b64: str, timeout_s: float) -> dict:
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [bild_b64],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_ctx": NUM_CTX},
    }
    begonnen = time.monotonic()
    ergebnis: dict = {"model": model}
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=5.0, read=timeout_s, write=30.0, pool=5.0)) as client:
            antwort = client.post(f"{ENDPOINT}/api/generate", json=payload)
            antwort.raise_for_status()
            daten = antwort.json()
        ergebnis["ok"] = True
        ergebnis["antwort"] = daten.get("response", "")[:600]
        # Ollama liefert Nanosekunden
        for feld in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration"):
            wert = daten.get(feld)
            if wert is not None:
                ergebnis[feld + "_ms"] = round(wert / 1_000_000)
        for feld in ("prompt_eval_count", "eval_count"):
            if daten.get(feld) is not None:
                ergebnis[feld] = daten[feld]
    except Exception as fehler:  # noqa: BLE001 - Messlauf, jeder Fehler ist ein Ergebnis
        ergebnis["ok"] = False
        ergebnis["fehler"] = f"{type(fehler).__name__}: {fehler}"[:300]
    ergebnis["wanduhr_ms"] = round((time.monotonic() - begonnen) * 1000)
    return ergebnis


def main() -> None:
    bild_pfad = sys.argv[1]
    modelle = sys.argv[2:]
    timeout_s = 600.0  # bewusst hoeher als die 200 s der Kette, damit auch Ueberschreitungen messbar sind

    with open(bild_pfad, "rb") as datei:
        bild_b64 = base64.b64encode(datei.read()).decode("ascii")

    alle = []
    for modell in modelle:
        for name, prompt in (("artikel", DESCRIBE_PROMPT), ("schaden", DAMAGE_PROMPT)):
            ergebnis = ask(modell, prompt, bild_b64, timeout_s)
            ergebnis["aufgabe"] = name
            alle.append(ergebnis)
            print(json.dumps(ergebnis, ensure_ascii=False), flush=True)

    print("=== ZUSAMMENFASSUNG ===", flush=True)
    for e in alle:
        if e.get("ok"):
            print(
                f"{e['model']:<20} {e['aufgabe']:<8} "
                f"gesamt {e['wanduhr_ms']/1000:7.1f}s  "
                f"laden {e.get('load_duration_ms', 0)/1000:6.1f}s  "
                f"eval {e.get('eval_duration_ms', 0)/1000:6.1f}s  "
                f"tokens {e.get('eval_count', 0)}",
                flush=True,
            )
        else:
            print(f"{e['model']:<20} {e['aufgabe']:<8} FEHLER {e.get('fehler')}", flush=True)


if __name__ == "__main__":
    main()
