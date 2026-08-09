#!/usr/bin/env python3
"""Messstand fuer den Artikelabgleich und die Schadenspruefung.

**Warum er ohne neue Fotos auskommt.** Das Soll-Urteil muss nicht fotografiert
werden, es folgt aus der HERKUNFT des Bildes: nehme ich das Katalogbild von
Artikel X, verzerre es und lege es als Meldefoto zu X, MUSS "derselbe Artikel"
herauskommen. Lege ich dasselbe Bild zu Artikel Y, muss "anderer Artikel"
herauskommen. Schneide ich eine Kerbe hinein, muss ein Schaden gefunden
werden. Das ergibt einen gelabelten Korpus aus Daten, die laengst da sind.

**Was er NICHT misst.** Kein Bild hier ist fotografiert. Eine synthetische
Kerbe in einem 192-px-Render ist kein Riss in einem echten Stein unter
Hallenlicht. Die Messung sagt etwas ueber die Empfindlichkeit der Kette --
ueber die Trefferquote im Lager sagt sie nur so viel, wie die Bilder den
echten aehneln. Die wenigen ECHTEN Fotos laufen deshalb mit und stehen in der
Auswertung getrennt.

**Warum die Kandidaten immer verzerrt werden.** `prepare_image` skaliert nicht
hoch; ein unveraendert uebernommenes 192-px-Katalogbild waere nach der
Aufbereitung BYTEGLEICH mit dem Katalogbild und traefe in llama.cpp den
Prompt-Cache -- gemessen am 2026-08-08, `cached n_tokens = 1239`, dreimal
dieselbe Antwort auf drei verschiedene Fragen. Jede Kandidatenfassung wird
darum gedreht, skaliert und neu kodiert.

**Drei Phasen, damit der teure Teil nur einmal laeuft.** Die Bildaufrufe
(20-60 s je Bild) landen in einem Zwischenspeicher, der an der Pruefsumme des
Bildes haengt. Der Textvergleich (3-5 s) kann danach beliebig oft mit
verschiedenen SOLL-Quellen wiederholt werden -- genau das ist der Vergleich
"heutiger Stand gegen gepruefte Katalogbeschreibung", der bisher fehlte.

Aufruf im Backend-Container (das Repo ist dort nicht eingehaengt):

    D=mobilepickingundvoiceassistant-backend-1
    docker cp <quellbilder> $D:/tmp/korpus_quellen
    docker exec -i $D python - --sehen < infrastructure/bildkorpus/messreihe.py
    docker exec -i $D python - --vergleichen < infrastructure/bildkorpus/messreihe.py
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
import sys
import time
import xmlrpc.client
from pathlib import Path

sys.path.insert(0, "/app")

from PIL import Image, ImageDraw, ImageEnhance  # noqa: E402

from app.services.assessment_media import DAMAGE_MAX_EDGE, prepare_image  # noqa: E402
from app.services.llm_client import LlmClient  # noqa: E402
from app.services.vision_client import VisionClient  # noqa: E402

ARBEIT = Path("/tmp/korpus")
QUELLEN = Path("/tmp/korpus_quellen")
BEFUNDE = ARBEIT / "befunde.json"
ERGEBNIS = ARBEIT / "ergebnis.json"

# Acht gelbe Bausteine unterschiedlicher Bauform. Das ist die Klasse, an der
# im Lager wirklich etwas schiefgeht -- WH/OUT/00050 enthaelt "Brick 2x3 W.
# Inv. Bow gelb" und "Brick 2x4 W. Inv. Bows gelb" im selben Auftrag.
GELB = ["343724", "4648231", "6023350", "6167549", "6171865", "6294939", "6380873"]
# Dieselbe Bauform in verschiedenen Farben: hier darf NUR die Farbe entscheiden.
FARBFAMILIE = ["343724", "343701", "343721", "4166960", "4183780", "4159527", "6294237"]


# ---------------------------------------------------------------------------
# Odoo
# ---------------------------------------------------------------------------

def odoo():
    url = os.environ.get("ODOO_URL", "http://odoo:8069").rstrip("/")
    db = os.environ["ODOO_DB"]
    user = os.environ.get("ODOO_USER", "admin")
    secret = os.environ.get("ODOO_API_KEY") or os.environ.get("ODOO_PASSWORD") or ""
    uid = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common").authenticate(
        db, user, secret, {}
    )
    if not uid:
        raise SystemExit("Anmeldung an Odoo fehlgeschlagen.")
    proxy = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def kw(model, methode, args, kwargs=None):
        return proxy.execute_kw(db, uid, secret, model, methode, args, kwargs or {})

    return kw


def artikel_laden(kw):
    """Alle bebilderten Artikel mit Bild, Name und hinterlegter Beschreibung."""
    zeilen = kw(
        "product.template",
        "search_read",
        [[("image_1920", "!=", False)]],
        {"fields": ["id", "default_code", "name", "ai_reference_description"],
         "order": "default_code asc"},
    )
    for zeile in zeilen:
        roh = kw("product.template", "read", [[zeile["id"]]],
                 {"fields": ["image_1920"]})[0]["image_1920"]
        zeile["bild"] = base64.b64decode(roh)
    return {z["default_code"]: z for z in zeilen if z["default_code"]}


# ---------------------------------------------------------------------------
# Die Verzerrungen
# ---------------------------------------------------------------------------

def _oeffnen(rohbytes: bytes) -> Image.Image:
    bild = Image.open(io.BytesIO(rohbytes))
    if bild.mode in ("RGBA", "LA", "P"):
        # Auf WEISS legen, nicht auf Schwarz: die Katalogbilder sind
        # freigestellt, und ein schwarzer Grund macht aus jedem hellen Stein
        # ein Kontrastproblem, das mit dem Artikel nichts zu tun hat.
        weiss = Image.new("RGB", bild.size, (255, 255, 255))
        bild = bild.convert("RGBA")
        weiss.paste(bild, mask=bild.split()[-1])
        return weiss
    return bild.convert("RGB")


def als_kandidat(rohbytes: bytes, winkel: float = 12.0, faktor: float = 0.8,
                 helligkeit: float = 1.08) -> bytes:
    """Macht aus einem Katalogbild ein plausibles "Meldefoto".

    Drehen, skalieren, aufhellen, neu als JPEG kodieren -- damit die Bytes
    sich vom Katalogbild unterscheiden und der Prompt-Cache nicht antwortet.
    """
    bild = _oeffnen(rohbytes)
    breite, hoehe = bild.size
    bild = bild.resize((max(32, int(breite / faktor)), max(32, int(hoehe / faktor))),
                       Image.LANCZOS)
    bild = bild.rotate(winkel, expand=True, fillcolor=(255, 255, 255),
                       resample=Image.BICUBIC)
    bild = ImageEnhance.Brightness(bild).enhance(helligkeit)
    puffer = io.BytesIO()
    bild.save(puffer, "JPEG", quality=92)
    return puffer.getvalue()


def mit_kerbe(rohbytes: bytes, anteil: float) -> bytes:
    """Schlaegt eine ausgefranste Kerbe in die Silhouette.

    `anteil` ist die Kantenlaenge der Kerbe im Verhaeltnis zur Bildkante:
    0.28 ist deutlich, 0.10 ist gerade noch zu sehen. Die Kerbe wird in
    WEISS gesetzt, also aus dem Teil herausgenommen -- ein aufgemalter
    dunkler Strich waere ein Aufdruck und kein Bruch.

    Der Rand wird gezackt gefuehrt: eine glatte Schnittkante ist genau der
    Fall, den die absolute Schadenspruefung bekanntlich durchlaesst (siehe
    `_check_damage`), und dieser Korpus soll die Kette pruefen, nicht sie
    austricksen.
    """
    bild = _oeffnen(rohbytes)
    breite, hoehe = bild.size
    kante = int(min(breite, hoehe) * anteil)
    if kante < 3:
        kante = 3
    stift = ImageDraw.Draw(bild)
    # Kerbe an der rechten oberen Flanke, zackig gefuehrt.
    x0, y0 = int(breite * 0.62), int(hoehe * 0.18)
    zacken = [(x0, y0)]
    for schritt in range(6):
        versatz = kante // 3 if schritt % 2 else -kante // 4
        zacken.append((x0 + kante * schritt // 5 + versatz,
                       y0 + kante * schritt // 5))
    zacken.append((x0 + kante, y0))
    stift.polygon(zacken, fill=(255, 255, 255))
    puffer = io.BytesIO()
    bild.save(puffer, "JPEG", quality=92)
    return puffer.getvalue()


# ---------------------------------------------------------------------------
# Der Korpus
# ---------------------------------------------------------------------------

def korpus_bauen(katalog):
    """Baut die Faelle. Jeder Fall traegt sein Soll-Urteil aus der Herkunft."""
    faelle = []

    def dazu(kennung, klasse, artikel, bytes_, artikel_soll, schaden_soll, herkunft):
        faelle.append({
            "id": kennung, "klasse": klasse, "artikel": artikel,
            "erwartet_artikel": artikel_soll, "erwartet_schaden": schaden_soll,
            "herkunft": herkunft, "bytes": bytes_,
        })

    vorhanden = [c for c in GELB + FARBFAMILIE if c in katalog]
    breit = [c for c in katalog if c not in vorhanden][:6] + vorhanden[:6]

    # A -- derselbe Artikel, nur verzerrt. Muss durchgehen.
    for nummer, code in enumerate(breit[:12]):
        dazu(f"A{nummer:02d}", "A identisch verzerrt", code,
             als_kandidat(katalog[code]["bild"], winkel=8 + nummer * 3,
                          faktor=0.7 + (nummer % 3) * 0.1),
             "match", "intact", f"Katalogbild {code}, gedreht/skaliert")

    # B -- anderer Artikel, GLEICHE Farbe. Der Fall aus dem Lager.
    gelb = [c for c in GELB if c in katalog]
    for nummer in range(min(8, len(gelb))):
        kandidat = gelb[(nummer + 1) % len(gelb)]
        ziel = gelb[nummer]
        dazu(f"B{nummer:02d}", "B verwechselbar gleiche Farbe", ziel,
             als_kandidat(katalog[kandidat]["bild"], winkel=10, faktor=0.75),
             "mismatch", None,
             f"Katalogbild {kandidat} gemeldet zu {ziel}")

    # C -- gleiche Bauform, andere Farbe. Hier darf nur die Farbe entscheiden.
    familie = [c for c in FARBFAMILIE if c in katalog]
    for nummer in range(min(6, len(familie))):
        kandidat = familie[(nummer + 2) % len(familie)]
        ziel = familie[nummer]
        if kandidat == ziel:
            continue
        dazu(f"C{nummer:02d}", "C andere Farbe", ziel,
             als_kandidat(katalog[kandidat]["bild"], winkel=15, faktor=0.85),
             "mismatch", None,
             f"Katalogbild {kandidat} gemeldet zu {ziel}")

    # D -- gar kein Artikel.
    fremd = sorted(QUELLEN.glob("fremd_*"))
    ziel_fuer_fremd = breit[0]
    for nummer, pfad in enumerate(fremd):
        dazu(f"D{nummer:02d}", "D kein Artikel", ziel_fuer_fremd,
             pfad.read_bytes(), "mismatch", None, f"Fremdbild {pfad.name}")

    # E/F -- derselbe Artikel MIT Kerbe, deutlich und leicht.
    for nummer, code in enumerate(breit[:8]):
        dazu(f"E{nummer:02d}", "E Kerbe deutlich", code,
             als_kandidat(mit_kerbe(katalog[code]["bild"], 0.30), winkel=6, faktor=0.75),
             "match", "damaged", f"Katalogbild {code} mit grosser Kerbe")
    for nummer, code in enumerate(breit[:6]):
        dazu(f"F{nummer:02d}", "F Kerbe leicht", code,
             als_kandidat(mit_kerbe(katalog[code]["bild"], 0.11), winkel=6, faktor=0.75),
             "match", "damaged", f"Katalogbild {code} mit kleiner Kerbe")

    # G -- ECHTE Fotos. Sie stehen in der Auswertung getrennt.
    echte = [
        ("T1-gelber-stein-riss.png", "6023350", "match", "damaged"),
        ("T2-gelber-stein-heil.png", "6023350", "match", "intact"),
        ("T3-anderer-stein-gebrochen.png", "6023350", "mismatch", None),
        ("T4-hund.webp", "6023350", "mismatch", None),
        ("T5-essen.jpg", "6023350", "mismatch", None),
    ]
    for nummer, (name, code, artikel_soll, schaden_soll) in enumerate(echte):
        pfad = QUELLEN / name
        if pfad.exists() and code in katalog:
            dazu(f"G{nummer:02d}", "G echtes Foto", code, pfad.read_bytes(),
                 artikel_soll, schaden_soll, f"echtes Meldefoto {name}")

    return faelle


# ---------------------------------------------------------------------------
# Phase 1: sehen (teuer, wird zwischengespeichert)
# ---------------------------------------------------------------------------

async def phase_sehen(faelle, katalog):
    vision = VisionClient(
        endpoint=os.environ.get("LLM_ENDPOINT", "http://ollama:11434"),
        model=os.environ.get("VISION_MODEL", "qwen2.5vl:7b"),
        timeout_ms=int(os.environ.get("VISION_TIMEOUT_MS", "200000")),
    )
    speicher = json.loads(BEFUNDE.read_text()) if BEFUNDE.exists() else {}
    gesamt = len(faelle)
    for nummer, fall in enumerate(faelle, start=1):
        klein = prepare_image(fall["bytes"])
        schluessel = hashlib.sha1(klein).hexdigest()
        fall["schluessel"] = schluessel
        eintrag = speicher.setdefault(schluessel, {})
        if "beschreibung" not in eintrag:
            # Ein Fehlschlag wird NICHT gespeichert. Der Zwischenspeicher soll
            # teure Arbeit sparen, nicht einen Zeitgrenzenfehler verewigen --
            # am 2026-08-09 lief D03 in eine ReadTimeout, und `None` im Cache
            # haette den Fall dauerhaft aus der Messung genommen, ohne dass es
            # in der Auswertung als Ausfall sichtbar geworden waere.
            for versuch in (1, 2):
                begonnen = time.monotonic()
                gesehen = await vision.describe(klein)
                if gesehen.ok:
                    eintrag["beschreibung"] = gesehen.text
                    eintrag["ist_artikel"] = gesehen.is_a_product
                    eintrag["dauer_beschreibung"] = round(time.monotonic() - begonnen, 1)
                    BEFUNDE.write_text(json.dumps(speicher, ensure_ascii=False, indent=1))
                    break
                print(f"    Bildmodell ohne Antwort, Versuch {versuch}", flush=True)
        # Die Schadenspruefung nur dort, wo ein Soll-Urteil dafuer existiert.
        if fall["erwartet_schaden"] and "schaden" not in eintrag:
            gross = prepare_image(fall["bytes"], max_edge=DAMAGE_MAX_EDGE)
            begonnen = time.monotonic()
            befund = await vision.inspect_damage(gross)
            if befund.ok:
                eintrag["schaden"] = befund.damaged
                eintrag["auffaelligkeiten"] = list(befund.anomalies)
                eintrag["dauer_schaden"] = round(time.monotonic() - begonnen, 1)
                BEFUNDE.write_text(json.dumps(speicher, ensure_ascii=False, indent=1))
            else:
                print("    Schadenspruefung ohne Antwort", flush=True)
        print(f"[{nummer}/{gesamt}] {fall['id']} {fall['klasse']}: "
              f"{eintrag.get('beschreibung')!r} schaden={eintrag.get('schaden')}",
              flush=True)
    return speicher


# ---------------------------------------------------------------------------
# Phase 2: vergleichen (billig, beliebig oft)
# ---------------------------------------------------------------------------

async def phase_vergleichen(faelle, katalog, speicher, soll_quelle):
    """`soll_quelle`: "odoo" nimmt die hinterlegte Beschreibung, "modell"
    laesst das Bildmodell das Katalogbild beschreiben (der Stand vor dem
    Festschreiben). Beides auf DEMSELBEN Korpus -- das ist der A/B-Vergleich,
    den es bisher nicht gab."""
    llm = LlmClient(
        endpoint=os.environ.get("LLM_ENDPOINT", "http://ollama:11434"),
        model=os.environ.get("LLM_MODEL", "qwen2.5:7b"),
        timeout_ms=int(os.environ.get("LLM_TIMEOUT_MS", "90000")),
    )
    vision = VisionClient(
        endpoint=os.environ.get("LLM_ENDPOINT", "http://ollama:11434"),
        model=os.environ.get("VISION_MODEL", "qwen2.5vl:7b"),
        timeout_ms=int(os.environ.get("VISION_TIMEOUT_MS", "200000")),
    )
    soll_texte = {}
    ergebnisse = []
    for fall in faelle:
        eintrag = speicher.get(fall["schluessel"], {})
        kandidat_text = eintrag.get("beschreibung")
        code = fall["artikel"]
        if code not in soll_texte:
            if soll_quelle == "odoo":
                soll_texte[code] = (katalog[code].get("ai_reference_description")
                                    or "").strip()
            else:
                klein = prepare_image(katalog[code]["bild"])
                schluessel = "soll:" + hashlib.sha1(klein).hexdigest()
                zwischen = speicher.setdefault(schluessel, {})
                if "beschreibung" not in zwischen:
                    gesehen = await vision.describe(klein)
                    zwischen["beschreibung"] = gesehen.text if gesehen.ok else None
                    BEFUNDE.write_text(json.dumps(speicher, ensure_ascii=False, indent=1))
                soll_texte[code] = zwischen["beschreibung"] or ""
        soll = soll_texte[code]
        if not kandidat_text or not soll:
            ergebnisse.append(dict(fall, bytes=None, ist_artikel_urteil="unavailable",
                                   soll_text=soll, kandidat_text=kandidat_text))
            continue
        urteil = await llm.compare_articles(
            reference_text=soll, candidate_text=kandidat_text,
            product_label=katalog[code]["name"],
        )
        ergebnisse.append(dict(
            fall, bytes=None,
            soll_text=soll, kandidat_text=kandidat_text,
            ist_artikel_urteil=("unavailable" if not urteil.ok
                                else "match" if urteil.same_article else "mismatch"),
            begruendung=urteil.reason, unterschied=urteil.differs,
            ist_schaden_urteil=eintrag.get("schaden"),
            auffaelligkeiten=eintrag.get("auffaelligkeiten"),
        ))
        print(f"  {fall['id']} soll={fall['erwartet_artikel']} "
              f"ist={ergebnisse[-1]['ist_artikel_urteil']}", flush=True)
    return ergebnisse


def auswerten(ergebnisse, titel):
    print(f"\n===== {titel} =====")
    klassen = {}
    for zeile in ergebnisse:
        klassen.setdefault(zeile["klasse"], []).append(zeile)
    artikel_richtig = artikel_gesamt = 0
    for klasse in sorted(klassen):
        zeilen = klassen[klasse]
        treffer = sum(1 for z in zeilen
                      if z["ist_artikel_urteil"] == z["erwartet_artikel"])
        artikel_richtig += treffer
        artikel_gesamt += len(zeilen)
        schadenzeilen = [z for z in zeilen if z["erwartet_schaden"]]
        schadentreffer = sum(
            1 for z in schadenzeilen
            if (z.get("ist_schaden_urteil") is True) == (z["erwartet_schaden"] == "damaged")
        )
        zusatz = (f"  Schaden {schadentreffer}/{len(schadenzeilen)}"
                  if schadenzeilen else "")
        print(f"{klasse:34s} Artikel {treffer}/{len(zeilen)}{zusatz}")
    print(f"{'GESAMT Artikelabgleich':34s} {artikel_richtig}/{artikel_gesamt}")
    fehler = [z for z in ergebnisse if z["ist_artikel_urteil"] != z["erwartet_artikel"]]
    if fehler:
        print("\nFehlurteile:")
        for zeile in fehler:
            print(f"  {zeile['id']} {zeile['herkunft']}")
            print(f"      soll={zeile['erwartet_artikel']} ist={zeile['ist_artikel_urteil']}"
                  f" ({zeile.get('unterschied')})")
            print(f"      SOLL:  {zeile['soll_text']}")
            print(f"      FOTO:  {zeile['kandidat_text']}")
            print(f"      Grund: {zeile.get('begruendung')}")


async def hauptlauf(argumente):
    ARBEIT.mkdir(exist_ok=True)
    kw = odoo()
    katalog = artikel_laden(kw)
    faelle = korpus_bauen(katalog)
    print(f"{len(faelle)} Faelle aus {len(katalog)} bebilderten Artikeln.\n")
    if argumente.nur_bauen:
        # Trockenlauf: zeigt den Korpus, ohne ein Modell anzufassen. Ein
        # Korpus, dessen Zusammensetzung man erst nach einer Stunde
        # Modellzeit sieht, laesst sich nicht pruefen.
        zaehler = {}
        for fall in faelle:
            zaehler[fall["klasse"]] = zaehler.get(fall["klasse"], 0) + 1
            probe = ARBEIT / "proben" / f"{fall['id']}.jpg"
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_bytes(fall["bytes"])
        for klasse in sorted(zaehler):
            print(f"  {klasse:34s} {zaehler[klasse]}")
        print(f"\nProbebilder in {ARBEIT / 'proben'}")
        return 0
    speicher = await phase_sehen(faelle, katalog)
    if argumente.nur_sehen:
        return 0
    alle = {}
    for quelle in argumente.soll:
        ergebnisse = await phase_vergleichen(faelle, katalog, speicher, quelle)
        auswerten(ergebnisse, f"SOLL-Quelle: {quelle}")
        alle[quelle] = ergebnisse
    ERGEBNIS.write_text(json.dumps(alle, ensure_ascii=False, indent=1, default=str))
    print(f"\nErgebnis in {ERGEBNIS}")
    return 0


def main() -> int:
    zerleger = argparse.ArgumentParser(description=__doc__)
    zerleger.add_argument("--nur-bauen", action="store_true", dest="nur_bauen",
                          help="Korpus bauen und anzeigen, keine Modellaufrufe")
    zerleger.add_argument("--nur-sehen", action="store_true", dest="nur_sehen",
                          help="nur die teuren Bildaufrufe, dann anhalten")
    zerleger.add_argument("--soll", nargs="+", default=["modell", "odoo"],
                          choices=["modell", "odoo"],
                          help="welche SOLL-Quellen gegeneinander gemessen werden")
    return asyncio.run(hauptlauf(zerleger.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
