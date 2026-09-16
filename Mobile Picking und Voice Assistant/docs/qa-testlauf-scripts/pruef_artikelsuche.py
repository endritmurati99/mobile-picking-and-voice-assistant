"""Prueft die Artikelsuche ueber mehrere Fotos und den Soll-Befund-Cache.

Ohne Ollama, ohne Einbettungsdienst, ohne Odoo: beide Wege werden gestellt, es
geht nur um die Verzweigung. Vier Zusagen:

1. `zu_dicht` auf Foto 1 sucht weiter -- das ist der Fall aus den Laeufen 15
   und 16, in denen Foto 1 unsicher und Foto 2 eindeutig war.
2. `kein_treffer` auf Foto 1 sucht NICHT weiter. Die Aussage gehoert zum Foto
   und traegt den Hundefall (QA/0340-0342); ein zweites Foto darf sie nicht
   wegsuchen.
3. Sagt kein Foto etwas, uebernimmt der Textweg -- und zwar mit Foto 1, nicht
   mit dem letzten probierten.
4. Der Soll-Befund-Cache uebersteht einen Prozesswechsel.

Aufruf im Backend-Container:
    PYTHONPATH=/app python /tmp/pruef_artikelsuche.py
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from app.routers import n8n_v2
from app.services.vision_client import DamageCheck

FOTOS = [b"foto-eins", b"foto-zwei", b"foto-drei"]


def _stelle_einbettung(antworten: dict[bytes, tuple]):
    """Ersetzt den Einbettungsweg durch eine Tabelle Foto -> Antwort."""
    gesehen: list[bytes] = []

    async def gestellt(runtime, odoo, instanz, media, candidate, lines, deadline):
        gesehen.append(candidate)
        return antworten.get(candidate, (None, None, False))

    return gestellt, gesehen


def _stelle_text():
    gesehen: list[bytes] = []

    async def gestellt(vision, llm, media, candidate, lines, deadline):
        gesehen.append(candidate)
        return "unavailable"

    return gestellt, gesehen


def _lauf(antworten: dict[bytes, tuple]) -> tuple[str, list[bytes], list[bytes]]:
    einbettung, gesehen_bild = _stelle_einbettung(antworten)
    text, gesehen_text = _stelle_text()
    echt_bild = n8n_v2._abgleich_ueber_einbettung
    echt_text = n8n_v2._artikel_ueber_text
    n8n_v2._abgleich_ueber_einbettung = einbettung
    n8n_v2._artikel_ueber_text = text
    try:
        ergebnis = asyncio.run(
            n8n_v2._check_article(
                None, None, {}, list(FOTOS), [], deadline=1e18,
                runtime=object(), odoo=object(), instanz="lager1",
            )
        )
    finally:
        n8n_v2._abgleich_ueber_einbettung = echt_bild
        n8n_v2._artikel_ueber_text = echt_text
    return ergebnis, gesehen_bild, gesehen_text


def pruefe_weitersuche() -> None:
    # Foto 1 zu dicht (hinweis gesetzt, fremd=False), Foto 2 eindeutig.
    ergebnis, bild, text = _lauf({
        FOTOS[0]: (None, "Bildabstand: zwei Artikel zu aehnlich", False),
        FOTOS[1]: ("match", None, False),
    })
    assert ergebnis == "match", ergebnis
    assert bild == FOTOS[:2], bild
    assert text == [], "Textweg darf gar nicht erst anspringen"
    print("1. zu_dicht sucht weiter und findet auf Foto 2            ok")


def pruefe_fremd_bricht_ab() -> None:
    ergebnis, bild, text = _lauf({
        FOTOS[0]: (None, "Bildabstand: kein bekannter Artikel", True),
        FOTOS[1]: ("match", None, False),
    })
    assert bild == FOTOS[:1], bild
    assert text == FOTOS[:1], text
    # `mismatch` ist hier KEIN Urteil ueber das Teil, sondern die Uebergabe an
    # einen Menschen: kein Weg konnte das Foto zuordnen, also setzt die Kette
    # `contradiction` und damit `review_required`. Das ist der Zweig, der die
    # drei Hundefotos vom 2026-08-14 heute abfangen wuerde.
    assert ergebnis == "mismatch", ergebnis
    print("2. kein_treffer sucht NICHT weiter, Fall geht an Menschen ok")


def pruefe_textweg_nimmt_foto_eins() -> None:
    ergebnis, bild, text = _lauf({
        f: (None, "Bildabstand: zwei Artikel zu aehnlich", False) for f in FOTOS
    })
    assert bild == FOTOS, bild
    assert text == FOTOS[:1], "Textweg muss Foto 1 sehen, nicht das letzte"
    assert ergebnis == "unavailable", ergebnis
    print("3. Textweg uebernimmt mit Foto 1                          ok")


def pruefe_cache() -> None:
    with tempfile.TemporaryDirectory() as ordner:
        pfad = Path(ordner) / "soll.json"
        echt_pfad, echt_flag = n8n_v2._SOLL_CACHE_PFAD, n8n_v2._SOLL_GELADEN
        n8n_v2._SOLL_CACHE_PFAD = pfad
        try:
            n8n_v2._SOLL_BEFUNDE.clear()
            n8n_v2._SOLL_BEFUNDE["abc"] = DamageCheck(
                ok=True, damaged=False, anomalies=("riss",), description="glatt"
            )
            n8n_v2._soll_cache_schreiben()
            assert pfad.exists(), "Cache wurde nicht geschrieben"

            # Prozesswechsel nachstellen: Speicher leeren, Ladeflagge zuruecksetzen.
            n8n_v2._SOLL_BEFUNDE.clear()
            n8n_v2._SOLL_GELADEN = False
            n8n_v2._soll_cache_laden()
            wieder = n8n_v2._SOLL_BEFUNDE.get("abc")
            assert wieder is not None, "Cache kam nicht zurueck"
            assert wieder.damaged is False and wieder.description == "glatt"
            assert wieder.anomalies == ("riss",), wieder.anomalies

            # Kaputte Datei darf nichts stoppen und nichts einschleusen.
            pfad.write_text("{kein json", encoding="utf-8")
            n8n_v2._SOLL_BEFUNDE.clear()
            n8n_v2._SOLL_GELADEN = False
            n8n_v2._soll_cache_laden()
            assert n8n_v2._SOLL_BEFUNDE == {}, "kaputte Datei darf nichts laden"

            # Ein gescheiterter Befund (`ok=False`) darf nie aus dem Cache kommen.
            pfad.write_text(json.dumps({"x": {"ok": False, "damaged": True}}), encoding="utf-8")
            n8n_v2._SOLL_GELADEN = False
            n8n_v2._soll_cache_laden()
            assert n8n_v2._SOLL_BEFUNDE == {}, "ok=False gehoert nicht in den Speicher"
        finally:
            n8n_v2._SOLL_CACHE_PFAD = echt_pfad
            n8n_v2._SOLL_GELADEN = echt_flag
            n8n_v2._SOLL_BEFUNDE.clear()
    print("4. Soll-Befund-Cache uebersteht den Prozesswechsel        ok")


if __name__ == "__main__":
    pruefe_weitersuche()
    pruefe_fremd_bricht_ab()
    pruefe_textweg_nimmt_foto_eins()
    pruefe_cache()
    print("\nAlle vier Zusagen gehalten.")
