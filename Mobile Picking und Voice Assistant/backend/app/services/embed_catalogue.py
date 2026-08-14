"""Den Artikelkatalog aus Odoo in den Einbettungsdienst schieben.

Der Dienst haelt den Katalog nur im Speicher -- bewusst: er ist aus Odoo
jederzeit neu herstellbar und soll nach einem Neustart nicht veraltet
weiterleben. Also muss jemand ihn hinschieben, und das ist das Backend, weil
nur es die Odoo-Zugaenge hat (`core-net` ist `internal: true`, der
Einbettungsdienst haengt gar nicht daran).

Aufgebaut wird traege und hoechstens einmal gleichzeitig. Der Aufbau kostet
gemessen 26,5 s fuer 47 Bilder; danach kostet eine Meldung eine Einbettung
plus so viele Skalarprodukte, wie es Artikel gibt.
"""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

# Bilder in Haeppchen nachladen statt in einem Zug. Ein einzelner Lesevorgang
# ueber alle bebilderten Artikel ist ein zweistelliger Megabyte-Block base64 in
# EINER JSON-RPC-Antwort, und der Odoo-Client liest mit 30 s Zeitgrenze.
_HAPPEN = 5


def _kennung(eintrag: dict) -> str:
    """Dieselbe Schluesselregel wie im Messstand (`neuetest/pruefen.py`).

    Ohne Artikelnummer die interne Kennung -- sonst kollidieren alle Artikel
    ohne `default_code` auf dem leeren Schluessel und ueberschreiben sich
    gegenseitig im Katalog.
    """
    code = (eintrag.get("default_code") or "").strip()
    return code or f"id{eintrag['id']}"


async def katalog_sicherstellen(runtime, odoo, instanz: str) -> frozenset[str]:
    """Gibt die Kennungen zurueck, die im Dienst stehen. Leer heisst: kein Katalog.

    Ein leeres Ergebnis ist kein Fehler, den der Aufrufer melden muesste -- es
    heisst nur, dass der Einbettungsweg fuer diese Meldung ausfaellt und der
    bisherige Weg uebernimmt.
    """
    if runtime.katalog_gueltig(instanz):
        return runtime.katalog_kennungen

    embed = runtime.embed_client()
    if embed is None:
        return frozenset()

    async with runtime.katalog_sperre:
        # Zweite Pruefung unter der Sperre: waehrend wir gewartet haben, kann
        # ein anderer Aufruf den Katalog bereits gebaut haben.
        if runtime.katalog_gueltig(instanz):
            return runtime.katalog_kennungen

        begonnen = time.monotonic()
        try:
            artikel = await odoo.execute_kw(
                "product.template",
                "search_read",
                [[["image_1920", "!=", False]]],
                {"fields": ["id", "default_code"], "order": "id asc"},
            )
        except Exception as exc:  # noqa: BLE001 - kein Katalog ist kein Absturz
            logger.warning(json.dumps({
                "event_type": "embed_katalog_failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "stufe": "artikelliste",
            }, ensure_ascii=False))
            return frozenset()

        gesammelt: list[tuple[str, str]] = []
        for start in range(0, len(artikel), _HAPPEN):
            teil = artikel[start:start + _HAPPEN]
            try:
                bilder = await odoo.execute_kw(
                    "product.template",
                    "read",
                    [[e["id"] for e in teil], ["id", "image_1920"]],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(json.dumps({
                    "event_type": "embed_katalog_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "stufe": "bilder",
                }, ensure_ascii=False))
                return frozenset()
            nach_id = {e["id"]: e for e in teil}
            for bild in bilder:
                roh = bild.get("image_1920")
                if roh:
                    gesammelt.append((_kennung(nach_id[bild["id"]]), roh))

        if not gesammelt:
            return frozenset()

        gezaehlt = await embed.katalog_setzen(gesammelt)
        if gezaehlt is None:
            return frozenset()

        kennungen = frozenset(k for k, _ in gesammelt)
        runtime.katalog_merken(instanz, kennungen)
        logger.info(json.dumps({
            "event_type": "embed_katalog_bereit",
            "instanz": instanz,
            "artikel": len(kennungen),
            "duration_ms": int((time.monotonic() - begonnen) * 1000),
        }, ensure_ascii=False))
        return kennungen
