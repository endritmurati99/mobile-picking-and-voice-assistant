"""Holt das Katalogbild eines Artikels direkt aus Odoo.

Der Weg ueber die PWA (`/api/products/<id>/image`) braucht eine Browser-Sitzung
und scheitert per PowerShell mit "Ungueltige oder abgelaufene Sitzung."; der
Download ueber die Seite wiederum schlaegt manchmal still fehl, wenn Chrome
mehrere Downloads hintereinander blockt. Dieser Weg umgeht beides.

Aufruf im Backend-Container:
    python /tmp/hol_katalogbild.py 6138111 /tmp/vorlage.png
Danach herausholen:
    docker cp mobilepickingundvoiceassistant-backend-1:/tmp/vorlage.png <ziel>
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.request

URL = "http://odoo:8069/jsonrpc"
DB = "lager1"
USER = "admin"
PW = "admin"


def call(service: str, method: str, *args):
    koerper = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {"service": service, "method": method, "args": list(args)},
    }
    antwort = urllib.request.urlopen(
        urllib.request.Request(
            URL, json.dumps(koerper).encode(), {"Content-Type": "application/json"}
        ),
        timeout=60,
    )
    daten = json.loads(antwort.read())
    if "error" in daten:
        raise SystemExit(json.dumps(daten["error"])[:400])
    return daten["result"]


def main() -> None:
    sku, ziel = sys.argv[1], sys.argv[2]
    uid = call("common", "login", DB, USER, PW)
    treffer = call(
        "object", "execute_kw", DB, uid, PW,
        "product.product", "search_read",
        [[["default_code", "=", sku]], ["id", "name", "default_code", "image_1920"]],
        {"limit": 1},
    )
    if not treffer:
        raise SystemExit(f"kein Artikel mit default_code {sku}")
    artikel = treffer[0]
    open(ziel, "wb").write(base64.b64decode(artikel["image_1920"]))
    print(f'{artikel["id"]} {artikel["default_code"]} {artikel["name"]} -> {ziel}')


if __name__ == "__main__":
    main()
