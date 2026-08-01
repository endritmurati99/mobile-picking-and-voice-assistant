#!/usr/bin/env python3
"""Ein einzelner geführter JSON-RPC-Aufruf gegen eine Live-Odoo-Datenbank.

Existiert, damit die Gate-Skripte nicht `curl | python -c` aneinanderreihen und
dabei einen RPC-Fehler als leeres Ergebnis missdeuten. Regeln wie in
`backend/tests/live/conftest.py`:

* HTTP != 200 ist ein Fehler.
* Ein `error`-Member ist ein Fehler, kein leeres Ergebnis.
* `False` (Odoos "nicht gefunden") ist ein Fehler, kein stilles ``null``.

Das Passwort kommt aus einer Datei, niemals aus der Kommandozeile: Argumente
stehen in `ps` und in der Shell-History.

    python3 infrastructure/scripts/live_rpc.py DB MODEL METHOD 'JSON-ARGS'
"""
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import NoReturn
from uuid import uuid4


def fail(message: str) -> NoReturn:
    print(f"live_rpc: {message}", file=sys.stderr)
    raise SystemExit(2)


def _call(url: str, service: str, method: str, args: list):
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "id": str(uuid4()),
        "params": {"service": service, "method": method, "args": args},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 200:
            fail(f"{service}.{method} returned HTTP {response.status}")
        body = json.loads(response.read().decode("utf-8"))
    if "error" in body:
        fail(f"{service}.{method} failed: {body['error']}")
    if "result" not in body:
        fail(f"{service}.{method} returned no result member")
    return body["result"]


def main(argv: list) -> int:
    if len(argv) != 5:
        fail("usage: live_rpc.py DATABASE MODEL METHOD JSON_ARGS")
    _, database, model, method, raw_args = argv

    def required(name: str) -> str:
        value = os.environ.get(name)
        if not value:
            fail(f"{name} is required")
        return value

    url = required("ODOO19_LIVE_URL")
    user = required("ODOO19_LIVE_USER")
    password_file = required("ODOO19_LIVE_PASSWORD_FILE")
    path = Path(password_file)
    if path.stat().st_mode & 0o077:
        fail(f"{password_file} permissions are too broad")
    password = path.read_text(encoding="utf-8").strip()

    try:
        args = json.loads(raw_args)
    except ValueError as exc:
        fail(f"JSON_ARGS is not valid JSON: {exc}")
    if not isinstance(args, list):
        args = [args]

    uid = _call(url, "common", "authenticate", [database, user, password, {}])
    if not uid:
        fail(f"authentication failed for {database}")

    result = _call(
        url,
        "object",
        "execute_kw",
        [database, uid, password, model, method, args, {}],
    )
    if result is False:
        fail(f"{model}.{method} returned False (not found) for {args}")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
