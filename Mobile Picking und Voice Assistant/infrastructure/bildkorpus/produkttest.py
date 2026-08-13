#!/usr/bin/env python3
"""Ein Bild je Produkt, alle Produkte, in Minuten statt Stunden.

**Warum es diese Datei neben `paarmatrix.py` gibt.** Der Lauf vom 2026-08-11
hat 103 Urteile gekostet und rund vier Stunden gebraucht, und darin steckten
nur 66 verschiedene Bildpaare -- der Rest war dasselbe Motiv mehrfach, weil an
Produkt 85 allein 33 Anhaenge haengen. Ausserdem war die Beschriftung an 13
Stellen falsch: `soll=gleich` auf einem Hundefoto, weil die Meldung am
richtigen Produkt haengt, das Foto aber ein Testbild ist. Gemessen wurde damit
zum Teil der Korpus, nicht das Modell.

Hier steht der einfache Gegenentwurf: **je Produkt genau ein abgeleitetes
Bild**, aus dem Katalogbild selbst erzeugt (gedreht, verkleinert, neu
komprimiert). Kein neues Foto, keine fremde Beschriftung, kein Anhang, der zum
falschen Artikel gehoert. Das SOLL steht damit per Konstruktion fest.

**Die Laufzeit kommt aus der Kantenlaenge, nicht aus weniger Paaren.** Gemessen
am 2026-08-13 gegen `qwen2.5vl:7b`, dasselbe Paar, dasselbe Urteil:

    Kante 448   69.3s
    Kante 336   66.6s
    Kante 224    6.8s     <- Faktor 10

Der Sprung liegt an der Kachelung des Sehmodells: unterhalb der Schwelle
braucht die Montage nur noch eine Kachel. `--tempo` prueft nach, ob 224 dieselben
Urteile faellt wie die 448er Messreihe -- ohne diesen Nachweis ist die schnelle
Einstellung wertlos.

**Beide Haelften werden bildfuellend skaliert.** `paarmatrix.montage` benutzt
`thumbnail()`, das nie hochskaliert. Katalogbilder sind im Median 192 px, Fotos
512 px -- links sass also immer ein kleines Objekt in weisser Flaeche, rechts
ein bildfuellendes. Der Kommentar dort behauptet das Gegenteil. Achtung: die
Normierung allein behebt den Riss-Fehler NICHT (am 2026-08-13 gegengeprueft,
Urteil blieb bei allen drei Kantenlaengen gleich falsch).

**Aufruf** (Repository ist im Backend-Container nicht eingehaengt):

    D=mobilepickingundvoiceassistant-backend-1
    docker exec -i $D python - --tempo 224   < infrastructure/bildkorpus/produkttest.py
    docker exec -i $D python - --produkte    < infrastructure/bildkorpus/produkttest.py
    docker exec -i $D python - --prompt      < infrastructure/bildkorpus/produkttest.py
    docker exec -i $D python - --bericht     < infrastructure/bildkorpus/produkttest.py
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

ARBEIT = Path("/tmp/produkttest")
BILDER = Path("/tmp/paarmatrix/bilder")  # vorhandene Bilder mitbenutzen
ALT = Path("/tmp/paarmatrix/urteile.json")

MODELL = os.environ.get("PAAR_MODELL", "qwen2.5vl:7b")
OLLAMA = os.environ.get("LLM_ENDPOINT", "http://ollama:11434")

# Fassung A ist der Wortlaut, der am 2026-08-11 gelaufen ist. Er nennt Schaden
# bereits ausdruecklich -- und das Modell haelt sich trotzdem nicht daran.
# Deshalb stehen hier Gegenfassungen, die den Schaden nicht bloss ausnehmen,
# sondern die Frage anders stellen.
PROMPTS = {
    "A_original": (
        "This picture shows TWO warehouse parts side by side, separated by a black "
        "bar. LEFT is the reference part from the catalogue. RIGHT is the delivered "
        "part. Ignore differences in lighting, background, viewing angle, scale and "
        "any damage such as cracks, scratches or missing corners -- a damaged part "
        "is still the same part. Decide only whether LEFT and RIGHT are the same "
        "article. Answer as JSON and nothing else: "
        '{"left":"<max 10 words>","right":"<max 10 words>",'
        '"same_part":true|false,"why":"<max 12 words>"}'
    ),
    # Trennt die beiden Fragen sichtbar: erst Schaden benennen, DANN die
    # Identitaet -- damit das Modell den Riss loswird, bevor es urteilt.
    "B_schaden_zuerst": (
        "This picture shows TWO warehouse parts side by side, separated by a black "
        "bar. LEFT is the catalogue reference. RIGHT is the delivered part. "
        "Work in two steps. Step 1: name any damage on the right part (crack, chip, "
        "dirt, missing piece) -- or 'none'. Step 2: imagine the right part REPAIRED "
        "and CLEAN, then decide whether it is the same article as the left one. "
        "Judge the article by shape, number of studs or holes, and colour only. "
        "Answer as JSON and nothing else: "
        '{"damage":"<max 6 words>","left":"<max 10 words>","right_repaired":"<max 10 words>",'
        '"same_part":true|false,"why":"<max 12 words>"}'
    ),
    # Zwingt zur Merkmalsliste vor dem Urteil. Die Fehlurteile vom 2026-08-11
    # ("differing only in color", "same number of holes" bei 4 gegen 6 Noppen)
    # zeigen, dass das Modell die Merkmale gar nicht erst zaehlt.
    "C_merkmale": (
        "This picture shows TWO warehouse parts side by side, separated by a black "
        "bar. LEFT is the catalogue reference, RIGHT is the delivered part. "
        "First count and name, for EACH side separately: the dominant colour, the "
        "number of studs or holes visible on top, and the overall body shape. "
        "Cracks, chips, dirt and scratches are damage, NOT article features -- never "
        "let them influence the article decision. Two parts are the same article "
        "only if colour, count and shape all agree. "
        "Answer as JSON and nothing else: "
        '{"left_colour":"<1 word>","left_count":<int>,"left_shape":"<max 4 words>",'
        '"right_colour":"<1 word>","right_count":<int>,"right_shape":"<max 4 words>",'
        '"same_part":true|false,"why":"<max 12 words>"}'
    ),
}


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


def fuellend(roh: bytes, kante: int) -> Image.Image:
    """Objekt auf die volle Kachel ziehen -- auch nach OBEN.

    `Image.thumbnail` verkleinert nur. Ein 192-px-Katalogrender blieb damit ein
    kleiner Fleck neben einem bildfuellenden 512-px-Foto.
    """
    teil = Image.open(io.BytesIO(roh)).convert("RGB")
    faktor = min(kante / teil.width, kante / teil.height)
    teil = teil.resize(
        (max(1, int(teil.width * faktor)), max(1, int(teil.height * faktor))),
        Image.LANCZOS,
    )
    flaeche = Image.new("RGB", (kante, kante), (255, 255, 255))
    flaeche.paste(teil, ((kante - teil.width) // 2, (kante - teil.height) // 2))
    return flaeche


def montage(links: bytes, rechts: bytes, kante: int) -> bytes:
    zusammen = Image.new("RGB", (kante * 2 + 8, kante), (0, 0, 0))
    zusammen.paste(fuellend(links, kante), (0, 0))
    zusammen.paste(fuellend(rechts, kante), (kante + 8, 0))
    puffer = io.BytesIO()
    zusammen.save(puffer, format="JPEG", quality=88)
    return puffer.getvalue()


def abgeleitet(roh: bytes) -> bytes:
    """Aus dem Katalogbild ein 'geliefertes Teil' machen -- ohne neue Aufnahme.

    Gedreht, verkleinert, aufgehellt, neu komprimiert. Das ist der Fall, den die
    Kette koennen MUSS: dasselbe Teil, anders im Bild. Wer hier durchfaellt,
    braucht ueber echte Lagerfotos nicht zu reden.
    """
    teil = Image.open(io.BytesIO(roh)).convert("RGB")
    teil = teil.rotate(25, expand=True, fillcolor=(255, 255, 255), resample=Image.BICUBIC)
    teil = teil.resize((int(teil.width * 0.8), int(teil.height * 0.8)), Image.LANCZOS)
    rand = Image.new("RGB", (int(teil.width * 1.2), int(teil.height * 1.2)), (250, 250, 248))
    rand.paste(teil, ((rand.width - teil.width) // 2, (rand.height - teil.height) // 2))
    puffer = io.BytesIO()
    rand.save(puffer, format="JPEG", quality=80)
    return puffer.getvalue()


def urteilen(bild: bytes, frage: str) -> tuple[dict | None, float]:
    nutzlast = json.dumps(
        {
            "model": MODELL,
            "prompt": frage,
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
        antwort = json.load(urllib.request.urlopen(anfrage, timeout=600))
        return json.loads(antwort.get("response") or "{}"), time.monotonic() - begonnen
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as fehler:
        print(f"    Aufruf gescheitert: {type(fehler).__name__}", flush=True)
        return None, time.monotonic() - begonnen


def laden(pfad: Path) -> dict:
    return json.loads(pfad.read_text()) if pfad.exists() else {}


def sichern(pfad: Path, daten: dict) -> None:
    ARBEIT.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=1))


def quelldatei(kennung: str) -> Path:
    if kennung.startswith("foto:"):
        return BILDER / f"foto_{kennung.split(':', 1)[1]}.jpg"
    return BILDER / f"kat_{kennung}.jpg"


# --------------------------------------------------------------------------- #
# --tempo: ist die schnelle Kantenlaenge ehrlich?
# --------------------------------------------------------------------------- #
def tempo(kante: int) -> None:
    alt = laden(ALT)
    if not alt:
        raise SystemExit("Keine 448er Messreihe unter /tmp/paarmatrix/urteile.json.")
    ziel = ARBEIT / f"tempo_{kante}.json"
    neu = laden(ziel)
    offen = [k for k in alt if k not in neu]
    print(f"Gegenprobe bei Kante {kante}: {len(alt)} Urteile, {len(offen)} offen.\n", flush=True)

    zeit = 0.0
    for nummer, schluessel in enumerate(offen, start=1):
        v = alt[schluessel]
        pl, pr = quelldatei(v["links"]), quelldatei(v["rechts"])
        if not pl.exists() or not pr.exists():
            continue
        ergebnis, dauer = urteilen(montage(pl.read_bytes(), pr.read_bytes(), kante),
                                   PROMPTS["A_original"])
        zeit += dauer
        if ergebnis is None:
            continue
        ist = bool(ergebnis.get("same_part"))
        neu[schluessel] = {
            "ist_gleich": ist, "soll_gleich": v["soll_gleich"],
            "wie_448": v["ist_gleich"], "einig": ist == v["ist_gleich"],
            "links_text": ergebnis.get("left"), "rechts_text": ergebnis.get("right"),
            "grund": ergebnis.get("why"), "dauer": round(dauer, 1), "kante": kante,
        }
        sichern(ziel, neu)
        rest = (len(offen) - nummer) * zeit / nummer
        marke = "  " if ist == v["ist_gleich"] else "!!"
        print(f"[{nummer}/{len(offen)}] {marke} {schluessel:30s} "
              f"224={'gleich' if ist else 'anders':7s} 448={'gleich' if v['ist_gleich'] else 'anders':7s} "
              f"({dauer:.0f}s, Rest {rest/60:.0f}min)", flush=True)

    einig = sum(1 for v in neu.values() if v["einig"])
    print(f"\nUEBEREINSTIMMUNG mit 448 px: {einig}/{len(neu)} = {100*einig/max(1,len(neu)):.1f}%", flush=True)


# --------------------------------------------------------------------------- #
# --produkte: ein abgeleitetes Bild je Produkt, alle Produkte
# --------------------------------------------------------------------------- #
def produkte(kante: int, fassung: str) -> None:
    kw = odoo()
    artikel = kw(
        "product.template", "search_read", [[("image_1920", "!=", False)]],
        {"fields": ["id", "default_code", "name"], "order": "default_code asc"},
    )
    nach_kennung = {}
    for eintrag in artikel:
        kennung = eintrag.get("default_code") or f"id{eintrag['id']}"
        nach_kennung.setdefault(kennung, eintrag)
    kennungen = sorted(nach_kennung)
    print(f"{len(kennungen)} bebilderte Artikel.\n", flush=True)

    BILDER.mkdir(parents=True, exist_ok=True)

    def katalog(kennung: str) -> bytes:
        ablage = BILDER / f"kat_{kennung}.jpg"
        if not ablage.exists():
            eintrag = nach_kennung[kennung]
            roh = kw("product.template", "read", [[eintrag["id"]]],
                     {"fields": ["image_1920"]})[0]["image_1920"]
            ablage.write_bytes(prepare_image(base64.b64decode(roh)))
        return ablage.read_bytes()

    def variante(kennung: str) -> bytes:
        ablage = ARBEIT / "abgeleitet" / f"{kennung}.jpg"
        if not ablage.exists():
            ablage.parent.mkdir(parents=True, exist_ok=True)
            ablage.write_bytes(abgeleitet(katalog(kennung)))
        return ablage.read_bytes()

    # Gegenstueck = der Artikel, dessen Name die meisten Anfangsworte teilt.
    # Ein zufaelliges Gegenstueck macht die Aufgabe zu leicht: "Brick gelb"
    # gegen "Tuer rot" trennt jedes Modell, "Brick 2x3 gelb" gegen
    # "Brick 2x4 gelb" ist die Verwechslung, die im Lager wirklich passiert.
    def gegenstueck(kennung: str) -> str:
        worte = (nach_kennung[kennung]["name"] or "").lower().split()
        beste, punkte = None, -1
        for andere in kennungen:
            if andere == kennung:
                continue
            fremd = (nach_kennung[andere]["name"] or "").lower().split()
            gleich = 0
            for a, b in zip(worte, fremd):
                if a != b:
                    break
                gleich += 1
            if gleich > punkte:
                beste, punkte = andere, gleich
        return beste

    paare = []
    for kennung in kennungen:
        paare.append((f"selbst:{kennung}", kennung, kennung, True))
        andere = gegenstueck(kennung)
        if andere:
            paare.append((f"fremd:{kennung}|{andere}", kennung, andere, False))

    ziel = ARBEIT / f"produkte_{fassung}_{kante}.json"
    urteile = laden(ziel)
    offen = [p for p in paare if p[0] not in urteile]
    print(f"{len(paare)} Tests ({len(kennungen)} selbst + {len(paare)-len(kennungen)} fremd), "
          f"{len(offen)} offen. Fassung {fassung}, Kante {kante}.\n", flush=True)

    zeit = 0.0
    for nummer, (schluessel, links, rechts, soll) in enumerate(offen, start=1):
        # links = Katalogbild, rechts = ABGELEITETES Bild (gedreht/skaliert).
        # Auch beim Selbstpaar, sonst vergleicht man Datei gegen sich selbst.
        bild = montage(katalog(links), variante(rechts), kante)
        ergebnis, dauer = urteilen(bild, PROMPTS[fassung])
        zeit += dauer
        if ergebnis is None:
            continue
        ist = bool(ergebnis.get("same_part"))
        urteile[schluessel] = {
            "links": links, "rechts": rechts, "soll_gleich": soll, "ist_gleich": ist,
            "roh": ergebnis, "dauer": round(dauer, 1), "kante": kante, "fassung": fassung,
            "links_name": nach_kennung[links]["name"], "rechts_name": nach_kennung[rechts]["name"],
        }
        sichern(ziel, urteile)
        rest = (len(offen) - nummer) * zeit / nummer
        marke = "  " if ist == soll else "XX"
        print(f"[{nummer}/{len(offen)}] {marke} {schluessel:32s} "
              f"soll={'gleich' if soll else 'anders':7s} ist={'gleich' if ist else 'anders':7s} "
              f"({dauer:.0f}s, Rest {rest/60:.0f}min)", flush=True)

    treffer = sum(1 for v in urteile.values() if v["ist_gleich"] == v["soll_gleich"])
    print(f"\nTREFFER {fassung}: {treffer}/{len(urteile)} = {100*treffer/max(1,len(urteile)):.1f}%", flush=True)


# --------------------------------------------------------------------------- #
# --prompt: die drei Fassungen auf den Schadensfaellen
# --------------------------------------------------------------------------- #
def prompt_vergleich(kante: int) -> None:
    """Nur die Paare, an denen Fassung A gescheitert ist -- plus Gegenproben.

    Ohne die richtig geloesten Paare misst man nur, ob eine Fassung lockerer
    ist: 'immer gleich' wuerde alle Schadensfaelle gewinnen und die
    Verwechslungen alle verlieren.
    """
    alt = laden(ALT)
    if not alt:
        raise SystemExit("Keine Messreihe unter /tmp/paarmatrix/urteile.json.")

    gesehen, auswahl = set(), []
    for schluessel, v in alt.items():
        pl, pr = quelldatei(v["links"]), quelldatei(v["rechts"])
        if not pl.exists() or not pr.exists():
            continue
        marke = (pl.read_bytes()[:64], pr.read_bytes()[:64], pl.stat().st_size, pr.stat().st_size)
        if marke in gesehen:
            continue
        gesehen.add(marke)
        auswahl.append((schluessel, v))

    ziel = ARBEIT / f"prompt_{kante}.json"
    urteile = laden(ziel)
    aufgaben = [(f, s, v) for f in PROMPTS for s, v in auswahl if f"{f}|{s}" not in urteile]
    print(f"{len(auswahl)} verschiedene Bildpaare x {len(PROMPTS)} Fassungen, "
          f"{len(aufgaben)} offen.\n", flush=True)

    zeit = 0.0
    for nummer, (fassung, schluessel, v) in enumerate(aufgaben, start=1):
        bild = montage(quelldatei(v["links"]).read_bytes(),
                       quelldatei(v["rechts"]).read_bytes(), kante)
        ergebnis, dauer = urteilen(bild, PROMPTS[fassung])
        zeit += dauer
        if ergebnis is None:
            continue
        ist = bool(ergebnis.get("same_part"))
        urteile[f"{fassung}|{schluessel}"] = {
            "fassung": fassung, "paar": schluessel, "soll_gleich": v["soll_gleich"],
            "ist_gleich": ist, "roh": ergebnis, "dauer": round(dauer, 1), "kante": kante,
        }
        sichern(ziel, urteile)
        rest = (len(aufgaben) - nummer) * zeit / nummer
        marke = "  " if ist == v["soll_gleich"] else "XX"
        print(f"[{nummer}/{len(aufgaben)}] {marke} {fassung:16s} {schluessel:30s} "
              f"({dauer:.0f}s, Rest {rest/60:.0f}min)", flush=True)

    bericht_prompt(urteile)


def bericht_prompt(urteile: dict) -> None:
    print("\n%-18s %6s %8s %8s" % ("Fassung", "gesamt", "gleich", "anders"), flush=True)
    for fassung in PROMPTS:
        teil = [v for v in urteile.values() if v["fassung"] == fassung]
        if not teil:
            continue
        gl = [v for v in teil if v["soll_gleich"]]
        an = [v for v in teil if not v["soll_gleich"]]
        rg = sum(1 for v in gl if v["ist_gleich"])
        ra = sum(1 for v in an if not v["ist_gleich"])
        gesamt = (rg + ra) / max(1, len(teil))
        print("%-18s %5.1f%% %4d/%-3d %4d/%-3d" % (
            fassung, 100 * gesamt, rg, len(gl), ra, len(an)), flush=True)


def bericht() -> None:
    for pfad in sorted(ARBEIT.glob("*.json")):
        daten = laden(pfad)
        if not daten:
            continue
        print(f"\n=== {pfad.name} ({len(daten)}) ===", flush=True)
        if pfad.name.startswith("prompt"):
            bericht_prompt(daten)
            continue
        if pfad.name.startswith("tempo"):
            einig = sum(1 for v in daten.values() if v.get("einig"))
            print(f"einig mit 448 px: {einig}/{len(daten)} = {100*einig/len(daten):.1f}%", flush=True)
            continue
        treffer = sum(1 for v in daten.values() if v["ist_gleich"] == v["soll_gleich"])
        gl = [v for v in daten.values() if v["soll_gleich"]]
        an = [v for v in daten.values() if not v["soll_gleich"]]
        print(f"Treffer {treffer}/{len(daten)} = {100*treffer/len(daten):.1f}% | "
              f"gleich {sum(1 for v in gl if v['ist_gleich'])}/{len(gl)} | "
              f"anders {sum(1 for v in an if not v['ist_gleich'])}/{len(an)}", flush=True)


def main() -> None:
    zerleger = argparse.ArgumentParser()
    zerleger.add_argument("--tempo", type=int, metavar="KANTE")
    zerleger.add_argument("--produkte", action="store_true")
    zerleger.add_argument("--prompt", action="store_true")
    zerleger.add_argument("--bericht", action="store_true")
    zerleger.add_argument("--kante", type=int, default=224)
    zerleger.add_argument("--fassung", default="A_original", choices=list(PROMPTS))
    wahl = zerleger.parse_args()

    ARBEIT.mkdir(parents=True, exist_ok=True)
    if wahl.tempo:
        tempo(wahl.tempo)
    elif wahl.produkte:
        produkte(wahl.kante, wahl.fassung)
    elif wahl.prompt:
        prompt_vergleich(wahl.kante)
    elif wahl.bericht:
        bericht()
    else:
        zerleger.error("Eine Betriebsart waehlen.")


if __name__ == "__main__":
    main()
