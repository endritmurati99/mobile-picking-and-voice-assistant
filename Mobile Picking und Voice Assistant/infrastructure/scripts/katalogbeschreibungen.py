#!/usr/bin/env python3
"""Erzeugt die SOLL-Beschreibungen der Katalogbilder -- zum Durchsehen.

**Wofuer.** Der Artikelabgleich der Bewertungskette vergleicht zwei
Beschreibungen, nicht zwei Bilder. Die SOLL-Seite entstand bisher bei jedem
Lauf neu aus dem Katalogbild -- und fuer `[6023350] Brick 2x2x2 R=15 gelb` an
drei Tagen wortgleich falsch ("plastic corner protector, yellow, cube with
rounded top"; QA/0227, QA/0233, QA/0234). Dieses Skript erzeugt denselben Satz
EINMAL, schreibt ihn nach Odoo und legt ihn damit einem Menschen zum Lesen
vor. Was dort steht, gilt danach -- und der zweite Bildaufruf je Bewertung
faellt weg.

**Es entscheidet nichts.** Es setzt `ai_reference_reviewed` nie auf True. Der
Haken gehoert an den Menschen, der den Satz gegen den echten Artikel gelesen
hat; ein Skript, das sich selbst als geprueft markiert, macht das Feld
wertlos.

**Laufzeit.** Ein Bildaufruf dauert 20 bis 60 Sekunden, die Artikel laufen
nacheinander. Fuer alle 47 bebilderten Artikel sind 25 bis 50 Minuten
einzuplanen. Waehrenddessen ist das Bildmodell belegt; eine gleichzeitige
echte Bewertung wird langsam oder laeuft in ihre Zeitgrenze.

**Aufruf.** Das Skript laeuft IM Backend-Container -- dort stehen Zugangsdaten,
Bildaufbereiter und der Weg zu Ollama. Das Repository ist dort nicht
eingehaengt (das Backend-Image baut nur aus `backend/`), deshalb wird die
Datei hineingereicht:

    D=mobilepickingundvoiceassistant-backend-1
    docker exec -i $D python - --probe 3 \
        < infrastructure/scripts/katalogbeschreibungen.py

    ... - --schreiben              alle bebilderten Artikel, Ergebnis nach Odoo
    ... - --schreiben --nur-neue   ueberspringt Artikel mit vorhandenem Satz
    ... - --artikel 6023350        nur dieser eine
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
import time
import xmlrpc.client

sys.path.insert(0, "/app")

from app.services.assessment_media import MediaError, prepare_image  # noqa: E402
from app.services.vision_client import VisionClient  # noqa: E402


def odoo_verbindung():
    url = os.environ.get("ODOO_URL", "http://odoo:8069").rstrip("/")
    db = os.environ["ODOO_DB"]
    user = os.environ.get("ODOO_USER", "admin")
    # Der API-Key geht vor: das Backend meldet sich im Betrieb genauso an, und
    # zwei verschiedene Anmeldewege waeren zwei verschiedene Rechtelagen.
    secret = os.environ.get("ODOO_API_KEY") or os.environ.get("ODOO_PASSWORD") or ""
    uid = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common").authenticate(
        db, user, secret, {}
    )
    if not uid:
        raise SystemExit("Anmeldung an Odoo fehlgeschlagen.")
    modelle = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def kw(model, methode, args, kwargs=None):
        return modelle.execute_kw(db, uid, secret, model, methode, args, kwargs or {})

    return kw


async def hauptlauf(argumente) -> int:
    kw = odoo_verbindung()
    bereich = [("image_1920", "!=", False)]
    if argumente.artikel:
        bereich = [("default_code", "=", argumente.artikel)]
    artikel = kw(
        "product.template",
        "search_read",
        [bereich],
        {"fields": ["id", "default_code", "name", "ai_reference_description"],
         "order": "default_code asc"},
    )
    if argumente.nur_neue:
        artikel = [a for a in artikel if not a.get("ai_reference_description")]
    if argumente.probe:
        artikel = artikel[: argumente.probe]
    if not artikel:
        print("Nichts zu tun.")
        return 0

    # Dasselbe Modell wie `describe()` in der Kette, seit Artikelabgleich und
    # Schadenspruefung getrennt sind (`config.vision_article_model`). Die SOLL-
    # Beschreibung wird spaeter gegen die Beschreibung des Meldefotos gehalten;
    # stammen die zwei Saetze aus verschiedenen Modellen, misst der Vergleich
    # den Modellunterschied mit. Genau dieses Vokabularproblem hat QA/0227
    # ausgeloest ("plastic corner protector" fuer einen Duplo-Stein).
    vision = VisionClient(
        endpoint=os.environ.get("LLM_ENDPOINT", "http://ollama:11434"),
        model=os.environ.get("VISION_MODEL", "gemma4:12b"),
        timeout_ms=int(os.environ.get("VISION_TIMEOUT_MS", "200000")),
    )

    print(f"{len(artikel)} Artikel, ein Bildaufruf je Artikel.\n")
    geschrieben = ohne_befund = 0
    for nummer, eintrag in enumerate(artikel, start=1):
        kennung = eintrag.get("default_code") or f"id{eintrag['id']}"
        # Das Bild wird EINZELN nachgeladen: 47 Bilder in einem Rutsch sind
        # mehrere Megabyte an einem XML-RPC-Aufruf, und ein Abbruch mittendrin
        # verloere alles.
        roh = kw(
            "product.template", "read", [[eintrag["id"]]], {"fields": ["image_1920"]}
        )[0]["image_1920"]
        begonnen = time.monotonic()
        try:
            # Dieselbe Aufbereitung wie in der Kette. Ein Satz, der auf einer
            # anderen Kantenlaenge entstand, beschriebe ein anderes Bild als
            # das, gegen das spaeter verglichen wird.
            bild = prepare_image(base64.b64decode(roh))
        except (MediaError, ValueError) as fehler:
            print(f"[{nummer}/{len(artikel)}] {kennung}: Bild unlesbar -- {fehler}")
            ohne_befund += 1
            continue
        gesehen = await vision.describe(bild)
        dauer = time.monotonic() - begonnen
        if not gesehen.ok:
            print(f"[{nummer}/{len(artikel)}] {kennung}: kein Befund ({dauer:.0f}s)")
            ohne_befund += 1
            continue
        print(f"[{nummer}/{len(artikel)}] {kennung} ({dauer:.0f}s)")
        print(f"    Artikel:      {eintrag['name']}")
        print(f"    Bildmodell:   {gesehen.text}")
        if argumente.schreiben:
            kw(
                "product.template",
                "api_set_reference_description",
                [eintrag["id"], gesehen.text],
            )
            geschrieben += 1
        print()

    print(
        f"Fertig. {geschrieben} geschrieben, {ohne_befund} ohne Befund, "
        f"{len(artikel) - geschrieben - ohne_befund} nur angezeigt."
    )
    if argumente.schreiben:
        print(
            "\nAlle geschriebenen Saetze stehen als UNGEPRUEFT in Odoo.\n"
            "Artikel -> Reiter Lager -> Bildbewertung: Satz lesen, gegen den\n"
            "echten Artikel pruefen, bei Bedarf berichtigen, Haken setzen."
        )
    return 0


def main() -> int:
    zerleger = argparse.ArgumentParser(description=__doc__)
    zerleger.add_argument(
        "--schreiben", action="store_true",
        help="Ergebnis nach Odoo schreiben (ohne das: nur anzeigen)",
    )
    zerleger.add_argument(
        "--nur-neue", action="store_true", dest="nur_neue",
        help="Artikel ueberspringen, die schon eine Beschreibung haben",
    )
    zerleger.add_argument(
        "--probe", type=int, default=0, metavar="N",
        help="nur die ersten N Artikel -- zum Ausprobieren",
    )
    zerleger.add_argument(
        "--artikel", metavar="ARTIKELNUMMER",
        help="nur diesen einen Artikel (default_code)",
    )
    return asyncio.run(hauptlauf(zerleger.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
