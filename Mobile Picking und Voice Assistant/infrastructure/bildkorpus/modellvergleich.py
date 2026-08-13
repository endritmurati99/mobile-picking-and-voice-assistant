#!/usr/bin/env python3
"""Zwoelf von Hand gepruefte Faelle, mehrere Bildmodelle, ein Vergleich.

**Warum von Hand.** Die Messreihe vom 2026-08-11 hat 103 Urteile geliefert, in
denen nur 66 verschiedene Bildpaare steckten -- und 13 davon trugen ein
falsches SOLL: `soll=gleich` auf einem Hundefoto, weil die Meldung am richtigen
Produkt hing, das Foto aber ein Testbild war. Wer darauf Modelle vergleicht,
vergleicht Korpusfehler.

Die zwoelf Faelle hier sind **einzeln angesehen und beschriftet** worden
(2026-08-13). Sie decken die beiden Achsen ab, an denen die Kette scheitert:

*Schadenstoleranz* -- ein beschaedigtes richtiges Teil MUSS `gleich` ergeben.
Das ist der teure Fehler: sonst wird die Schadensmeldung als Falschlieferung
abgewiesen und der Befund geht verloren.

*Artikelschaerfe* -- ein anderer Artikel MUSS `anders` ergeben, auch wenn er
dieselbe Farbe hat oder aehnlich aussieht. Ohne diese Achse gewinnt jedes
Modell, das immer `gleich` sagt.

**Der Korpus ist duenn, und das steht hier so.** Es gibt genau vier Motive:
gelber Bogenstein (sauber und drei Aufnahmen derselben Kerbe), blauer 2x2 mit
Riss, gelber 2x3 stark beschaedigt und verschmutzt, Hund am Strand. Zwoelf
Faelle aus vier Motiven sind eine Vorauswahl, kein Beweis. Ein Modell, das hier
durchfaellt, ist erledigt; eines, das besteht, muss danach gegen echte neue
Aufnahmen.

**Aufruf** (Repository ist im Backend-Container nicht eingehaengt):

    D=mobilepickingundvoiceassistant-backend-1
    docker exec -i $D python - --modell qwen3-vl:8b < infrastructure/bildkorpus/modellvergleich.py
    docker exec -i $D python - --bericht            < infrastructure/bildkorpus/modellvergleich.py
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

ARBEIT = Path("/tmp/modellvergleich")
BILDER = Path("/tmp/paarmatrix/bilder")
OLLAMA = os.environ.get("LLM_ENDPOINT", "http://ollama:11434")
KANTE = 448

# (Name, linkes Bild, rechtes Bild, soll_gleich, was darauf zu sehen ist)
# Die letzte Spalte ist das, was ICH auf dem Bild gesehen habe -- nicht das,
# was ein Modell dazu geschrieben hat.
FAELLE = [
    # --- Schadenstoleranz: beschaedigt, aber derselbe Artikel ---------------
    ("S1_blau_riss", "kat_4166960", "foto_4", True,
     "blauer 2x2-Stein gegen denselben Stein mit durchgehendem Riss"),
    ("S2_bogen_kerbe_a", "kat_6023350", "foto_11", True,
     "gelber Bogenstein gegen denselben Bogenstein mit ausgerissener Kerbe"),
    ("S3_bogen_kerbe_b", "kat_6023350", "foto_213", True,
     "derselbe Schaden, andere Aufnahme, staerker angeschnitten"),
    ("S4_bogen_kerbe_c", "kat_6023350", "foto_10", True,
     "derselbe Schaden, dritte Aufnahme, gekippte Lage"),
    ("S5_bogen_sauber", "kat_6023350", "foto_13", True,
     "gelber Bogenstein gegen sauberes Foto desselben Steins (Gegenprobe ohne Schaden)"),
    ("S6_blau_gedreht", "kat_4166960", "ABGELEITET:kat_4166960", True,
     "blauer 2x2-Stein gegen sich selbst, 25 Grad gedreht und verkleinert"),

    # --- Artikelschaerfe: wirklich ein anderer Artikel ----------------------
    ("A1_gruen_blau", "kat_301124", "foto_3", False,
     "gruener 2x2-Stein gegen blauen 2x2-Stein -- gleiche Form, andere Farbe"),
    ("A2_2x2_gegen_2x3", "kat_343724", "foto_12", False,
     "gelber 2x2-Stein gegen gelben 2x3-Stein -- gleiche Farbe, mehr Noppen"),
    ("A3_bogen_gegen_2x3", "kat_6023350", "foto_12", False,
     "gelber Bogenstein gegen gelben 2x3-Stein -- gleiche Farbe, andere Bauform"),
    ("A4_bogen_gegen_blau", "kat_6023350", "foto_4", False,
     "gelber Bogenstein gegen blauen 2x2-Stein -- alles anders"),
    ("A5_blau_gegen_2x3", "kat_4166960", "foto_12", False,
     "blauer 2x2-Stein gegen gelben 2x3-Stein"),
    ("A6_hund", "kat_6023350", "foto_14", False,
     "gelber Bogenstein gegen Hund am Strand -- der Ausloeserfall"),
]

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

# Fuer Modelle, die mehrere Bilder wirklich annehmen. Die Montage ist nur ein
# Notbehelf gegen Ollamas Beschraenkung bei `qwen-vl` (dort kommt bloss das
# erste Bild an, gemessen am 2026-08-11). Wer zwei Bilder schicken kann, spart
# dem Modell den Umweg ueber "linke Haelfte gegen rechte Haelfte" und gibt
# jedem Teil die volle Aufloesung statt der halben.
FRAGE_ZWEI = (
    "You are shown TWO images. The FIRST image is the reference part from the "
    "catalogue. The SECOND image is the delivered part. Ignore differences in "
    "lighting, background, viewing angle, scale and any damage such as cracks, "
    "scratches or missing corners -- a damaged part is still the same part. "
    "Decide only whether the two images show the same article. "
    "Answer as JSON and nothing else: "
    '{"left":"<max 10 words>","right":"<max 10 words>",'
    '"same_part":true|false,"why":"<max 12 words>"}'
)

# Beweisfrage: kommt das zweite Bild ueberhaupt an? Ein Modell, das nur das
# erste sieht, beschreibt zweimal dasselbe oder meldet "only one image".
FRAGE_PROBE = (
    "You are shown TWO images. Describe the FIRST image in at most 8 words, "
    "then the SECOND image in at most 8 words. If you can see only one image, "
    'say so. Answer as JSON and nothing else: {"first":"...","second":"..."}'
)


def fuellend(roh: bytes, kante: int) -> Image.Image:
    """Objekt auf die volle Kachel ziehen -- auch nach OBEN.

    `Image.thumbnail` verkleinert nur. Katalogbilder sind im Median 192 px,
    Fotos 512 px; ohne das Hochziehen sass links ein kleiner Fleck neben einem
    bildfuellenden Foto.
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


def abgeleitet(roh: bytes) -> bytes:
    teil = Image.open(io.BytesIO(roh)).convert("RGB")
    teil = teil.rotate(25, expand=True, fillcolor=(255, 255, 255), resample=Image.BICUBIC)
    teil = teil.resize((int(teil.width * 0.8), int(teil.height * 0.8)), Image.LANCZOS)
    puffer = io.BytesIO()
    teil.save(puffer, format="JPEG", quality=80)
    return puffer.getvalue()


def bild(kennung: str) -> bytes:
    if kennung.startswith("ABGELEITET:"):
        return abgeleitet((BILDER / f"{kennung.split(':', 1)[1]}.jpg").read_bytes())
    return (BILDER / f"{kennung}.jpg").read_bytes()


def montage(links: bytes, rechts: bytes) -> bytes:
    zusammen = Image.new("RGB", (KANTE * 2 + 8, KANTE), (0, 0, 0))
    zusammen.paste(fuellend(links, KANTE), (0, 0))
    zusammen.paste(fuellend(rechts, KANTE), (KANTE + 8, 0))
    puffer = io.BytesIO()
    zusammen.save(puffer, format="JPEG", quality=88)
    return puffer.getvalue()


def urteilen(bilder: list[bytes], modell: str, frage: str = FRAGE,
             als_json: bool = True) -> tuple[dict | str | None, float]:
    nutzlast = {
        "model": modell, "prompt": frage,
        "images": [base64.b64encode(b).decode() for b in bilder],
        "stream": False, "options": {"temperature": 0},
    }
    if als_json:
        nutzlast["format"] = "json"
    nutzlast = json.dumps(nutzlast).encode()
    anfrage = urllib.request.Request(
        f"{OLLAMA}/api/generate", data=nutzlast,
        headers={"Content-Type": "application/json"},
    )
    begonnen = time.monotonic()
    try:
        antwort = json.load(urllib.request.urlopen(anfrage, timeout=900))
        text = antwort.get("response") or ""
        if not als_json:
            # Rohtext zurueck -- der Aufrufer zieht das JSON selbst heraus.
            return text, time.monotonic() - begonnen
        return json.loads(text or "{}"), time.monotonic() - begonnen
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as fehler:
        print(f"    gescheitert: {type(fehler).__name__}: {fehler}", flush=True)
        return None, time.monotonic() - begonnen


def aus_text(rohtext: str) -> dict:
    """Erstes JSON-Objekt aus freiem Text ziehen.

    Noetig, weil `format: json` nicht bei jedem Modell funktioniert. Gemessen
    am 2026-08-13 mit Ollama 0.31.1: `qwen3-vl:8b` liefert unter `format: json`
    zwoelfmal ein leeres `{}` -- und wer dann `.get("same_part")` liest,
    bekommt `None`, macht daraus `False` und protokolliert ein Urteil, das das
    Modell nie gefaellt hat. Genau so ist am 2026-08-13 eine ganze Messreihe
    entstanden, die nur die eigene Auswertung gemessen hat.
    """
    tiefe, start = 0, None
    for stelle, zeichen in enumerate(rohtext):
        if zeichen == "{":
            if tiefe == 0:
                start = stelle
            tiefe += 1
        elif zeichen == "}" and tiefe:
            tiefe -= 1
            if tiefe == 0 and start is not None:
                try:
                    return json.loads(rohtext[start:stelle + 1])
                except json.JSONDecodeError:
                    start = None
    return {}


def geurteilt(bilder: list[bytes], modell: str, frage: str) -> tuple[dict | None, float]:
    """Erst mit Formatzwang, bei leerer Antwort ohne -- und dann aus dem Text.

    Ein Fall ohne `same_part` wird NICHT als `False` gebucht, sondern gilt als
    fehlgeschlagen. Ein Modell, das nicht antwortet, hat nicht 'anders' gesagt.
    """
    ergebnis, dauer = urteilen(bilder, modell, frage)
    if isinstance(ergebnis, dict) and "same_part" in ergebnis:
        return ergebnis, dauer
    roh, dauer2 = urteilen(bilder, modell, frage, als_json=False)
    zweiter = aus_text(roh) if isinstance(roh, str) else (roh or {})
    if isinstance(zweiter, dict) and "same_part" in zweiter:
        return zweiter, dauer + dauer2
    return None, dauer + dauer2


def probe(modell: str) -> bool:
    """Kommt das ZWEITE Bild an? Ohne diese Probe misst man womoeglich Unsinn.

    Bei `qwen2.5vl:7b` reicht Ollama nur das erste Bild durch -- das Modell
    antwortet dann fuer beide Bilder dasselbe oder meldet "only one image".
    Genau darum existiert der Montage-Umweg ueberhaupt.
    """
    print(f"{modell}: Zweibild-Probe ...", flush=True)
    ergebnis, dauer = urteilen(
        [bild("kat_6023350"), bild("foto_14")], modell, FRAGE_PROBE,
    )
    if not isinstance(ergebnis, dict):
        print(f"  keine verwertbare Antwort: {str(ergebnis)[:120]}", flush=True)
        return False
    erst = str(ergebnis.get("first", ""))
    zweit = str(ergebnis.get("second", ""))
    print(f"  Bild 1: {erst}", flush=True)
    print(f"  Bild 2: {zweit}  ({dauer:.0f}s)", flush=True)
    # Bild 1 ist ein gelber Bogenstein, Bild 2 ein Hund am Strand. Wer beide
    # sieht, kann sie nicht gleich beschreiben.
    hund = any(w in zweit.lower() for w in ("dog", "animal", "beach", "labrador"))
    verschieden = erst.strip().lower() != zweit.strip().lower()
    print(f"  ZWEI BILDER KOMMEN AN: {'JA' if (hund and verschieden) else 'NEIN'}\n", flush=True)
    return hund and verschieden


def lauf(modell: str, zweibild: bool = False) -> None:
    ARBEIT.mkdir(parents=True, exist_ok=True)
    kennzeichen = modell.replace(":", "_").replace("/", "_") + ("_zweibild" if zweibild else "")
    ziel = ARBEIT / f"{kennzeichen}.json"
    urteile = json.loads(ziel.read_text()) if ziel.exists() else {}

    def eingabe(links: str, rechts: str) -> list[bytes]:
        if zweibild:
            return [bild(links), bild(rechts)]
        return [montage(bild(links), bild(rechts))]

    frage = FRAGE_ZWEI if zweibild else FRAGE

    # Aufwaermen mit einem Fall, der NICHT gemessen wird -- sonst faellt der
    # erste Messwert um den Faktor 4 hoeher aus (Ladezeit des Sehmodells) und
    # der zweite trifft womoeglich den Prompt-Cache.
    if not urteile:
        print(f"{modell}: aufwaermen ...", flush=True)
        urteilen(eingabe("kat_301124", "kat_343724"), modell, frage)
        if zweibild and not probe(modell):
            print("ABBRUCH: das Modell sieht das zweite Bild nicht -- eine "
                  "Zweibild-Messung waere wertlos.\n", flush=True)
            return

    print(f"\n{modell}{' [zwei Bilder]' if zweibild else ' [Montage]'} "
          f"-- {len(FAELLE)} Faelle\n", flush=True)
    for name, links, rechts, soll, beschreibung in FAELLE:
        if name in urteile:
            continue
        ergebnis, dauer = geurteilt(eingabe(links, rechts), modell, frage)
        if ergebnis is None:
            print(f"?? {name:22s} kein verwertbares Urteil ({dauer:.0f}s) -- "
                  f"NICHT als 'anders' gebucht", flush=True)
            continue
        ist = bool(ergebnis.get("same_part"))
        urteile[name] = {
            "soll_gleich": soll, "ist_gleich": ist, "roh": ergebnis,
            "dauer": round(dauer, 1), "beschreibung": beschreibung,
            "modell": modell + (" [2 Bilder]" if zweibild else " [Montage]"),
        }
        ziel.write_text(json.dumps(urteile, ensure_ascii=False, indent=1))
        marke = "  " if ist == soll else "XX"
        print(f"{marke} {name:22s} soll={'gleich' if soll else 'anders':7s} "
              f"ist={'gleich' if ist else 'anders':7s} ({dauer:.0f}s)  "
              f"{ergebnis.get('why', '')[:52]}", flush=True)

    if urteile:
        auswerten({next(iter(urteile.values()))["modell"]: urteile})


def auswerten(alle: dict) -> None:
    print(f"\n{'Modell':22s} {'gesamt':>8s} {'Schaden':>9s} {'Artikel':>9s} {'s/Fall':>7s}", flush=True)
    for modell, urteile in alle.items():
        if not urteile:
            continue
        schaden = [v for v in urteile.values() if v["soll_gleich"]]
        artikel = [v for v in urteile.values() if not v["soll_gleich"]]
        rs = sum(1 for v in schaden if v["ist_gleich"])
        ra = sum(1 for v in artikel if not v["ist_gleich"])
        dauer = sum(v["dauer"] for v in urteile.values()) / len(urteile)
        print(f"{modell:22s} {rs + ra:3d}/{len(urteile):<4d} {rs:4d}/{len(schaden):<4d} "
              f"{ra:4d}/{len(artikel):<4d} {dauer:6.0f}s", flush=True)


def bericht() -> None:
    alle = {}
    for pfad in sorted(ARBEIT.glob("*.json")):
        daten = json.loads(pfad.read_text())
        if daten:
            alle[next(iter(daten.values()))["modell"]] = daten
    if not alle:
        raise SystemExit("Noch keine Messung.")
    auswerten(alle)
    print("\nFehler je Modell:", flush=True)
    for modell, urteile in alle.items():
        schlecht = [(n, v) for n, v in urteile.items() if v["ist_gleich"] != v["soll_gleich"]]
        print(f"\n  {modell}", flush=True)
        if not schlecht:
            print("    keiner", flush=True)
        for name, v in schlecht:
            print(f"    {name:22s} {v['beschreibung']}", flush=True)
            print(f"    {'':22s} -> {v['roh'].get('why', '')}", flush=True)


def main() -> None:
    zerleger = argparse.ArgumentParser()
    zerleger.add_argument("--modell")
    zerleger.add_argument("--zweibild", action="store_true",
                          help="zwei getrennte Bilder statt der Montage")
    zerleger.add_argument("--bericht", action="store_true")
    wahl = zerleger.parse_args()
    if wahl.bericht:
        bericht()
    elif wahl.modell:
        lauf(wahl.modell, zweibild=wahl.zweibild)
    else:
        zerleger.error("--modell oder --bericht")


if __name__ == "__main__":
    main()
