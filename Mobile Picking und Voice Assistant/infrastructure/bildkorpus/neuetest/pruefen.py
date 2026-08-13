#!/usr/bin/env python3
"""Neue, selbst aufgenommene Fotos gegen den Odoo-Katalog halten.

**Warum dieses Skript.** Der Beleg fuer den Einbettungsweg stand bisher auf
sechs echten Fotos an zwei Artikeln plus 44 abgeleiteten Bildern -- also auf
Aufnahmen, die entweder aus derselben Handvoll Motive stammen oder aus dem
Katalogbild selbst errechnet wurden. Beides zeigt, dass das Verfahren Artikel
TRENNEN kann. Keines zeigt, dass es das auf frisch aufgenommenen Fotos tut:
andere Beleuchtung, Hand im Bild, Karton, Schraegwinkel.

Dieses Skript nimmt genau solche frischen Aufnahmen entgegen. Es laeuft IM
Einbettungscontainer, weil dort die DINOv2-Gewichte liegen und `core-net`
`internal: true` ist -- von aussen gibt es keinen Weg zu Odoo.

Ablauf: Katalog aus Odoo ziehen -> einbetten -> jedes neue Foto abrufen.
Kein Bildsprachmodell, kein Ollama. Rechenzeit je Foto unter zwei Sekunden.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.request
import xmlrpc.client
from pathlib import Path

FOTOS = Path("/neu")
DIENST = "http://127.0.0.1:8000"

# Die Aufnahmen tragen den erwarteten Artikel im Dateinamen: `<kennung>_*.jpg`.
# Ohne Praefix laeuft das Foto als offene Frage ("welcher Artikel ist das"),
# mit Praefix als gerichtete ("ist das WIRKLICH der bestellte Artikel") -- nur
# die gerichtete kann ein `mismatch` ergeben.
NAMENSMUSTER = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*?)_")


def odoo():
    url = os.environ.get("ODOO_URL", "http://odoo:8069").rstrip("/")
    db = os.environ["ODOO_DB"]
    nutzer = os.environ.get("ODOO_USER", "admin")
    geheim = os.environ.get("ODOO_API_KEY") or os.environ.get("ODOO_PASSWORD") or ""
    uid = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common").authenticate(
        db, nutzer, geheim, {})
    if not uid:
        raise SystemExit("Odoo-Anmeldung fehlgeschlagen -- ODOO_DB/ODOO_API_KEY pruefen.")
    modelle = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def kw(model, methode, args, kwargs=None):
        return modelle.execute_kw(db, uid, geheim, model, methode, args, kwargs or {})

    return kw


def senden(pfad: str, nutzlast: dict, frist: int = 900) -> dict:
    anfrage = urllib.request.Request(
        f"{DIENST}{pfad}",
        data=json.dumps(nutzlast).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(anfrage, timeout=frist) as antwort:
        return json.load(antwort)


def katalog_laden(kw) -> dict[str, str]:
    """Jeden bebilderten Artikel einmal aus Odoo holen.

    `default_code` ist die Kennung, die auch im Pickschein steht; faellt sie
    aus, dient die Datenbank-ID als Notnagel, damit kein Artikel stillschweigend
    aus dem Katalog faellt.
    """
    zeilen = kw("product.template", "search_read",
                [[("image_1920", "!=", False)]],
                {"fields": ["id", "default_code", "name"]})
    katalog = {}
    for zeile in zeilen:
        rohbild = kw("product.template", "read", [[zeile["id"]]],
                     {"fields": ["image_1920"]})[0]["image_1920"]
        if not rohbild:
            continue
        kennung = (zeile.get("default_code") or "").strip() or f"id{zeile['id']}"
        katalog[kennung] = rohbild
    return katalog


def main() -> int:
    bilder = sorted(p for p in FOTOS.iterdir()
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if not bilder:
        print(f"Keine Bilder in {FOTOS}.")
        return 1

    print("Katalog aus Odoo holen ...", flush=True)
    katalog = katalog_laden(odoo())
    print(f"{len(katalog)} bebilderte Artikel.", flush=True)

    begonnen = time.monotonic()
    antwort = senden("/katalog", {"artikel": [{"kennung": k, "bild_b64": b}
                                              for k, b in katalog.items()]})
    print(f"eingebettet: {antwort['artikel']} Artikel in {antwort['sekunden']}s "
          f"({antwort['je_bild']}s je Bild)\n", flush=True)

    ergebnisse = []
    for pfad in bilder:
        treffer = NAMENSMUSTER.match(pfad.stem)
        erwartet = treffer.group(1) if treffer and treffer.group(1) in katalog else None
        nutzlast = {"bild_b64": base64.b64encode(pfad.read_bytes()).decode()}
        if erwartet:
            nutzlast["erwartet"] = erwartet
        e = senden("/abgleich", nutzlast)
        e["datei"] = pfad.name
        e["erwartet"] = erwartet
        ergebnisse.append(e)

        rang = "  ".join(f"{r['kennung']}={r['wert']:.3f}" for r in e["rang"][:3])
        print(f"{pfad.name:32s} {e['urteil']:9s} {e['sekunden']:5.2f}s  "
              f"Abstand {e['abstand']:.3f}", flush=True)
        print(f"{'':32s} {rang}", flush=True)
        print(f"{'':32s} {e['grund']}\n", flush=True)

    ziel = FOTOS / "ergebnis.json"
    ziel.write_text(json.dumps(ergebnisse, indent=2, ensure_ascii=False))
    print(f"{len(ergebnisse)} Fotos in {time.monotonic() - begonnen:.0f}s. -> {ziel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
