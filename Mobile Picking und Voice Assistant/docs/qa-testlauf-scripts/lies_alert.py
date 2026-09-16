"""Liest einen Quality Alert samt aller `ai_*`-Felder aus Odoo.

Das Odoo-Formular rendert im versteckten Browser-Tab oft leer; ausserdem heisst
das Modell `quality.alert.custom`, nicht `quality.alert` -- wer den falschen
Namen nimmt, bekommt "Object quality.alert doesn't exist".

Aufruf im Backend-Container:
    python /tmp/lies_alert.py QA/0374
"""
from __future__ import annotations

import json
import sys
import urllib.request

URL = "http://odoo:8069/jsonrpc"
DB = "lager1"
USER = "admin"
PW = "admin"
MODELL = "quality.alert.custom"


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
    name = sys.argv[1]
    uid = call("common", "login", DB, USER, PW)
    felder = call("object", "execute_kw", DB, uid, PW, MODELL, "fields_get", [[], ["string"]], {})
    gewuenscht = [f for f in felder if f.startswith("ai_")] + [
        "name", "create_date", "write_date",
    ]
    treffer = call(
        "object", "execute_kw", DB, uid, PW, MODELL, "search_read",
        [[["name", "=", name]], gewuenscht], {"limit": 1},
    )
    if not treffer:
        raise SystemExit(f"{name} nicht gefunden")
    for schluessel, wert in treffer[0].items():
        if wert not in (False, "", None):
            print(f"{schluessel}: {str(wert)[:1200]}")


if __name__ == "__main__":
    main()
