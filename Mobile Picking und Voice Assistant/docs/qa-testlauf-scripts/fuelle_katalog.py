"""Schiebt den Artikelkatalog aus Odoo in den Einbettungsdienst.

Der Dienst haelt den Katalog nur im Speicher; nach einem Neustart antwortet
`/abgleich` mit HTTP 409 (`kein_katalog`). Im Betrieb schiebt das Backend ihn
beim ersten Abgleich nach -- wer aber OHNE Kettenlauf misst (`probe_schwellen.py`),
loest das nie aus und laeuft in das 409.

Gleiche Regeln wie `backend/app/services/embed_catalogue.py`: nur bebilderte
Artikel, Kennung ist `default_code` (sonst `id<N>`), Bilder in Haeppchen von 5,
weil eine Antwort ueber alle Bilder zweistellige Megabyte base64 waere.

Aufruf im Backend-Container:
    python /tmp/fuelle_katalog.py
"""
from __future__ import annotations

import json
import time
import urllib.request

ODOO = "http://odoo:8069/jsonrpc"
EMBED = "http://embed:8000"
DB = "lager1"
USER = "admin"
PW = "admin"
HAPPEN = 5


def call(service: str, method: str, *args):
    koerper = {"jsonrpc": "2.0", "method": "call",
               "params": {"service": service, "method": method, "args": list(args)}}
    antwort = urllib.request.urlopen(
        urllib.request.Request(ODOO, json.dumps(koerper).encode(),
                               {"Content-Type": "application/json"}),
        timeout=120,
    )
    daten = json.loads(antwort.read())
    if "error" in daten:
        raise SystemExit(json.dumps(daten["error"])[:400])
    return daten["result"]


def main() -> None:
    begonnen = time.monotonic()
    uid = call("common", "login", DB, USER, PW)
    artikel = call("object", "execute_kw", DB, uid, PW,
                   "product.template", "search_read",
                   [[["image_1920", "!=", False]]],
                   {"fields": ["id", "default_code"], "order": "id asc"})
    gesammelt = []
    for start in range(0, len(artikel), HAPPEN):
        teil = artikel[start:start + HAPPEN]
        bilder = call("object", "execute_kw", DB, uid, PW,
                      "product.template", "read",
                      [[e["id"] for e in teil], ["id", "image_1920"]])
        nach_id = {e["id"]: e for e in teil}
        for bild in bilder:
            roh = bild.get("image_1920")
            if roh:
                eintrag = nach_id[bild["id"]]
                kennung = (eintrag.get("default_code") or "").strip() or f"id{eintrag['id']}"
                gesammelt.append({"kennung": kennung, "bild_b64": roh})

    antwort = urllib.request.urlopen(
        urllib.request.Request(f"{EMBED}/katalog",
                               json.dumps({"artikel": gesammelt}).encode(),
                               {"Content-Type": "application/json"}),
        timeout=600,
    )
    daten = json.loads(antwort.read())
    print(f"artikel={daten.get('artikel')} dauer_s={time.monotonic() - begonnen:.1f}")


if __name__ == "__main__":
    main()
