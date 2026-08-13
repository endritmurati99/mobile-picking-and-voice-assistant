#!/usr/bin/env python3
"""Jedes Teil gegen jedes andere -- Bild gegen Bild, nicht Satz gegen Satz.

**Warum es diese Datei gibt.** Der Artikelabgleich der Bewertungskette hat nie
zwei Bilder verglichen. Er liess `qwen2.5vl:7b` jedes Bild EINZELN in Prosa
beschreiben und legte die beiden Saetze dann `qwen2.5:7b` zum Urteil vor. Damit
entscheidet Wortwahl ueber Warenannahme: "square block with rounded arched top"
gegen "cube with rounded top" ist derselbe Klotz in zwei Formulierungen, und das
Textmodell las daraus eine Formdifferenz (QA/0321, QA/0227, QA/0233, QA/0234).

Der naheliegende Ausweg -- beide Bilder in EINEN Aufruf -- ist versperrt.
Gemessen am 2026-08-11 gegen `qwen2.5vl:7b` ueber Ollama, `/api/generate` und
`/api/chat`, jeweils mit `images: [a, b]`:

    zwei VERSCHIEDENE (49s)  Image 1: A single yellow LEGO brick ...
                             Image 2: Not applicable; there is only one image.
    ZWEIMAL dasselbe   (5s)  ... wortgleich dieselbe Antwort ...
    nur EIN Bild       (5s)  ... wortgleich dieselbe Antwort ...

Alle drei Faelle antworten identisch, und die 5 Sekunden der letzten beiden
zeigen, dass gar kein zweites Bild kodiert wurde: Ollama reicht dem Modell nur
das erste durch. Ein `same_part`-Urteil aus so einem Aufruf ist geraten.

Deshalb der Umweg, der mit jedem Einbild-Modell funktioniert: beide Teile
werden VORHER zu einem Bild montiert, links das Katalogbild, rechts das
gelieferte Teil, dazwischen ein schwarzer Balken. Das Modell sieht dann
tatsaechlich beide Teile nebeneinander. Erste Probe ueber sechs gelbe Bricks:
4 von 4 richtig, darunter `4648231` gegen `6294939` -- zwei hellgelbe Bricks,
die sich nur in der Noppenzahl unterscheiden.

**Was hier gemessen wird.** Zwei Durchgaenge, beide aus vorhandenen Daten, kein
einziges neues Foto:

`--katalog`  Alle 47 bebilderten Artikel gegen alle. Das Katalogbild eines
             Artikels gegen sich selbst MUSS `gleich` ergeben, gegen jeden
             anderen Artikel `verschieden`. 1081 Kreuzpaare, 47 Selbstpaare.

`--fotos`    Die echten Meldefotos aus `quality.alert.custom` gegen das
             Katalogbild ihres eigenen Artikels (MUSS `gleich` ergeben) und
             gegen `--koeder N` fremde Artikel (MUSS `verschieden` ergeben).
             Das ist der Fall aus dem Betrieb: ein Foto vom Lagerplatz gegen
             ein Katalogrendering, verschiedene Beleuchtung, verschiedene Lage,
             teils beschaedigt.

Ohne die Selbstpaare misst man nichts: ein Modell, das immer `verschieden`
sagt, kaeme im Katalogdurchgang auf 1081 von 1128.

**Ergebnisse werden zwischengespeichert.** Jedes Urteil landet unter seinem
Schluessel in `ERGEBNISSE`; ein Abbruch kostet hoechstens den laufenden Aufruf.
Fehlgeschlagene Aufrufe werden NICHT gespeichert, sonst friert ein
Netzwerkfehler als Messwert ein.

**Aufruf.** Laeuft IM Backend-Container -- dort stehen Zugangsdaten,
Bildaufbereiter und der Weg zu Ollama. Das Repository ist dort nicht
eingehaengt, deshalb wird die Datei hineingereicht:

    D=mobilepickingundvoiceassistant-backend-1
    docker exec -i $D python - --fotos --koeder 4 < infrastructure/bildkorpus/paarmatrix.py
    docker exec -i $D python - --katalog                < infrastructure/bildkorpus/paarmatrix.py
    docker exec -i $D python - --bericht                < infrastructure/bildkorpus/paarmatrix.py

Ein Vergleich dauert auf dieser Maschine (CPU, kein Grafikbeschleuniger) rund
eine Minute. Der Katalogdurchgang ist damit ein Nachtlauf; `--fotos` ohne
Koeder ist in einer Stunde durch.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import xmlrpc.client
from pathlib import Path

from PIL import Image

sys.path.insert(0, "/app")

from app.services.assessment_media import prepare_image  # noqa: E402

ARBEIT = Path("/tmp/paarmatrix")
ERGEBNISSE = ARBEIT / "urteile.json"
BILDER = ARBEIT / "bilder"

MODELL = os.environ.get("PAAR_MODELL", "qwen2.5vl:7b")
KANTE = int(os.environ.get("PAAR_KANTE", "448"))
OLLAMA = os.environ.get("LLM_ENDPOINT", "http://ollama:11434")

# Die Frage nennt links und rechts beim Namen und laesst das Modell erst
# beschreiben, dann urteilen -- derselbe Grundsatz, der am 2026-08-05 fuer die
# Einzelbeschreibung gemessen wurde. Ohne die beiden Beschreibungsfelder faellt
# die Trefferquote, und man hat ausserdem keine Handhabe zu pruefen, WORAN das
# Modell ein Fehlurteil festgemacht hat.
FRAGE = (
    "This picture shows TWO warehouse parts side by side, separated by a black "
    "bar. LEFT is the reference part from the catalogue. RIGHT is the delivered "
    "part. Ignore differences in lighting, background, viewing angle, scale and "
    "any damage such as cracks, scratches or missing corners -- a damaged part "
    "is still the same part. Decide only whether LEFT and RIGHT are the same "
    "article. Answer as JSON and nothing else: "
    '{"left":"<max 10 words>","right":"<max 10 words>",'
    '"same_part":true|false,"why":"<max 12 words>"}'
)


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
    modelle = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def kw(model, methode, args, kwargs=None):
        return modelle.execute_kw(db, uid, secret, model, methode, args, kwargs or {})

    return kw


def gespeichert() -> dict:
    if ERGEBNISSE.exists():
        return json.loads(ERGEBNISSE.read_text())
    return {}


def sichern(urteile: dict) -> None:
    ARBEIT.mkdir(parents=True, exist_ok=True)
    ERGEBNISSE.write_text(json.dumps(urteile, ensure_ascii=False, indent=1))


def bild_holen(kennung: str, lader) -> bytes:
    """Aufbereitetes Bild, einmal geholt und dann von Platte.

    Ein Katalogbild wird im Katalogdurchgang 94-mal gebraucht. Es jedes Mal
    ueber XML-RPC zu ziehen und neu zu skalieren kostet mehr Zeit als der
    Modellaufruf selbst.
    """
    BILDER.mkdir(parents=True, exist_ok=True)
    ablage = BILDER / f"{kennung}.jpg"
    if not ablage.exists():
        ablage.write_bytes(prepare_image(lader()))
    return ablage.read_bytes()


def montage(links: bytes, rechts: bytes) -> bytes:
    """Zwei Teile in ein Bild -- der einzige Weg, auf dem das Modell beide sieht.

    Beide Haelften bekommen dieselbe quadratische Flaeche, damit die Groesse im
    Bild nichts ueber den Artikel aussagt: sonst lernt das Modell, dass das
    groessere Teil das andere ist. Der schwarze Balken trennt sie sichtbar; ohne
    ihn hat das Modell in der Vorprobe beide Haelften als EIN Objekt gelesen.
    """
    haelften = []
    for roh in (links, rechts):
        teil = Image.open(io.BytesIO(roh)).convert("RGB")
        teil.thumbnail((KANTE, KANTE), Image.LANCZOS)
        flaeche = Image.new("RGB", (KANTE, KANTE), (255, 255, 255))
        flaeche.paste(teil, ((KANTE - teil.width) // 2, (KANTE - teil.height) // 2))
        haelften.append(flaeche)
    zusammen = Image.new("RGB", (KANTE * 2 + 8, KANTE), (0, 0, 0))
    zusammen.paste(haelften[0], (0, 0))
    zusammen.paste(haelften[1], (KANTE + 8, 0))
    puffer = io.BytesIO()
    zusammen.save(puffer, format="JPEG", quality=88)
    return puffer.getvalue()


def urteilen(bild: bytes) -> tuple[dict | None, float]:
    nutzlast = json.dumps(
        {
            "model": MODELL,
            "prompt": FRAGE,
            "images": [base64.b64encode(bild).decode()],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
    ).encode()
    anfrage = urllib.request.Request(
        f"{OLLAMA}/api/generate", data=nutzlast,
        headers={"Content-Type": "application/json"},
    )
    begonnen = time.monotonic()
    try:
        antwort = json.load(urllib.request.urlopen(anfrage, timeout=400))
        return json.loads(antwort.get("response") or "{}"), time.monotonic() - begonnen
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None, time.monotonic() - begonnen


def durchlauf(paare, hole_bild, titel: str) -> None:
    """Paare abarbeiten, Zwischenstand nach jedem Urteil sichern."""
    urteile = gespeichert()
    offen = [p for p in paare if p[0] not in urteile]
    print(f"{titel}: {len(paare)} Paare, {len(paare) - len(offen)} schon bewertet, "
          f"{len(offen)} offen.\n", flush=True)
    if not offen:
        return

    gesamtzeit = 0.0
    for nummer, (schluessel, links, rechts, soll) in enumerate(offen, start=1):
        bild = montage(hole_bild(links), hole_bild(rechts))
        ergebnis, dauer = urteilen(bild)
        gesamtzeit += dauer
        if ergebnis is None:
            # Nicht speichern: ein Zeitueberlauf ist kein Messwert. Beim
            # naechsten Lauf wird das Paar erneut versucht.
            print(f"[{nummer}/{len(offen)}] {schluessel}: kein Urteil ({dauer:.0f}s)",
                  flush=True)
            continue
        ist = bool(ergebnis.get("same_part"))
        urteile[schluessel] = {
            "links": links, "rechts": rechts, "soll_gleich": soll, "ist_gleich": ist,
            "links_text": ergebnis.get("left"), "rechts_text": ergebnis.get("right"),
            "grund": ergebnis.get("why"), "dauer": round(dauer, 1),
            "modell": MODELL, "kante": KANTE,
        }
        sichern(urteile)
        rest = (len(offen) - nummer) * gesamtzeit / nummer
        marke = "  " if ist == soll else "XX"
        print(f"[{nummer}/{len(offen)}] {marke} {schluessel:34s} "
              f"soll={'gleich' if soll else 'anders':7s} ist={'gleich' if ist else 'anders':7s} "
              f"({dauer:.0f}s, Rest {rest/3600:.1f}h)", flush=True)


def katalogpaare(kw):
    artikel = kw(
        "product.template", "search_read", [[("image_1920", "!=", False)]],
        {"fields": ["id", "default_code", "name"], "order": "default_code asc"},
    )
    nach_kennung = {}
    for eintrag in artikel:
        kennung = eintrag.get("default_code") or f"id{eintrag['id']}"
        nach_kennung.setdefault(kennung, eintrag)
    kennungen = sorted(nach_kennung)

    def hole(kennung):
        eintrag = nach_kennung[kennung]
        return bild_holen(
            f"kat_{kennung}",
            lambda: base64.b64decode(
                kw("product.template", "read", [[eintrag["id"]]],
                   {"fields": ["image_1920"]})[0]["image_1920"]
            ),
        )

    paare = [(f"kat:{k}|{k}", k, k, True) for k in kennungen]
    for i, links in enumerate(kennungen):
        for rechts in kennungen[i + 1:]:
            paare.append((f"kat:{links}|{rechts}", links, rechts, False))
    return paare, hole, len(kennungen)


def fotopaare(kw, koeder: int):
    meldungen = kw(
        "quality.alert.custom", "search_read",
        [[("photo", "!=", False), ("product_id", "!=", False)]],
        {"fields": ["id", "name", "product_id"], "order": "id asc"},
    )
    artikel = kw(
        "product.template", "search_read", [[("image_1920", "!=", False)]],
        {"fields": ["id", "default_code", "name"], "order": "default_code asc"},
    )
    nach_id = {a["id"]: (a.get("default_code") or f"id{a['id']}") for a in artikel}
    nach_kennung = {}
    for eintrag in artikel:
        nach_kennung.setdefault(
            eintrag.get("default_code") or f"id{eintrag['id']}", eintrag
        )
    kennungen = sorted(nach_kennung)

    def hole(kennung):
        if kennung.startswith("foto:"):
            melde_id = int(kennung.split(":", 1)[1])
            return bild_holen(
                f"foto_{melde_id}",
                lambda: base64.b64decode(
                    kw("quality.alert.custom", "read", [[melde_id]],
                       {"fields": ["photo"]})[0]["photo"]
                ),
            )
        eintrag = nach_kennung[kennung]
        return bild_holen(
            f"kat_{kennung}",
            lambda: base64.b64decode(
                kw("product.template", "read", [[eintrag["id"]]],
                   {"fields": ["image_1920"]})[0]["image_1920"]
            ),
        )

    paare = []
    for meldung in meldungen:
        eigen = nach_id.get(meldung["product_id"][0])
        if eigen is None or eigen not in nach_kennung:
            continue  # Der gemeldete Artikel hat kein Katalogbild -- nichts zu vergleichen.
        foto = f"foto:{meldung['id']}"
        paare.append((f"fot:{meldung['name']}|{eigen}", eigen, foto, True))
        # Koeder deterministisch und ueber die ganze Liste verteilt, damit nicht
        # nur Nachbarn derselben Farbfamilie geprueft werden.
        fremde = [k for k in kennungen if k != eigen]
        schritt = max(1, len(fremde) // max(1, koeder))
        for nummer in range(koeder):
            stelle = (meldung["id"] * 7 + nummer * schritt) % len(fremde)
            fremd = fremde[stelle]
            paare.append((f"fot:{meldung['name']}|{fremd}", fremd, foto, False))
    return paare, hole, len(meldungen)


def bericht() -> int:
    urteile = gespeichert()
    if not urteile:
        print("Noch keine Urteile.")
        return 0
    for vorsatz, name in (("kat:", "Katalog gegen Katalog"),
                          ("fot:", "Meldefoto gegen Katalog")):
        teil = {k: v for k, v in urteile.items() if k.startswith(vorsatz)}
        if not teil:
            continue
        gleich = [v for v in teil.values() if v["soll_gleich"]]
        anders = [v for v in teil.values() if not v["soll_gleich"]]
        richtig_g = sum(1 for v in gleich if v["ist_gleich"])
        richtig_a = sum(1 for v in anders if not v["ist_gleich"])
        print(f"\n=== {name} ({len(teil)} Paare) ===")
        if gleich:
            print(f"  derselbe Artikel erkannt : {richtig_g}/{len(gleich)}"
                  f"  ({100*richtig_g/len(gleich):.0f}%)")
        if anders:
            print(f"  fremder Artikel erkannt  : {richtig_a}/{len(anders)}"
                  f"  ({100*richtig_a/len(anders):.0f}%)")
        gesamt = richtig_g + richtig_a
        print(f"  gesamt                   : {gesamt}/{len(teil)}")
        if anders:
            print(f"  (Vergleich: wer immer 'anders' sagt, kaeme auf "
                  f"{len(anders)}/{len(teil)})")
        schnitt = sum(v["dauer"] for v in teil.values()) / len(teil)
        print(f"  Zeit je Paar             : {schnitt:.0f}s")

        fehler = [v for v in teil.values() if v["ist_gleich"] != v["soll_gleich"]]
        if fehler:
            print(f"\n  {len(fehler)} Fehlurteile:")
            for v in fehler[:40]:
                art = "durchgewinkt" if v["ist_gleich"] else "abgelehnt   "
                print(f"    {art} {v['links']:12s} gegen {v['rechts']:12s} "
                      f"| {v['links_text']} || {v['rechts_text']} | {v['grund']}")
            if len(fehler) > 40:
                print(f"    ... und {len(fehler)-40} weitere")
    return 0


def main() -> int:
    zerleger = argparse.ArgumentParser(description=__doc__)
    zerleger.add_argument("--katalog", action="store_true",
                          help="alle bebilderten Artikel gegen alle")
    zerleger.add_argument("--fotos", action="store_true",
                          help="echte Meldefotos gegen Katalogbilder")
    zerleger.add_argument("--koeder", type=int, default=3, metavar="N",
                          help="fremde Artikel je Meldefoto (Vorgabe 3)")
    zerleger.add_argument("--bericht", action="store_true",
                          help="nur auswerten, nichts rechnen")
    argumente = zerleger.parse_args()

    if argumente.bericht:
        return bericht()
    if not (argumente.katalog or argumente.fotos):
        zerleger.error("--katalog, --fotos oder --bericht angeben")

    kw = odoo()
    print(f"Modell {MODELL}, Kante {KANTE} px je Haelfte.\n")
    if argumente.fotos:
        paare, hole, anzahl = fotopaare(kw, argumente.koeder)
        durchlauf(paare, hole, f"Meldefoto gegen Katalog ({anzahl} Meldungen)")
    if argumente.katalog:
        paare, hole, anzahl = katalogpaare(kw)
        durchlauf(paare, hole, f"Katalog gegen Katalog ({anzahl} Artikel)")
    return bericht()


if __name__ == "__main__":
    raise SystemExit(main())
