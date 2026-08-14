"""Schadenserkennung: welches Bildmodell sieht den Schaden?

Die Achse, die nach dem Umbau des Artikelabgleichs uebrig bleibt. Am
2026-08-14 meldete `qwen2.5vl:7b` an foto_11 "keine Auffaelligkeit sichtbar" --
auf einem Foto, auf dem eine ausgerissene Kerbe rund ein Fuenftel der
sichtbaren Flaeche einnimmt. Das ist kein Aufloesungsproblem: die Vorlage ist
512 px und der Schaden fuellt einen grossen Teil davon.

Gemessen wird der PRODUKTIVE Aufruf: `VisionClient.inspect_damage` mit
`DAMAGE_MAX_EDGE`, ein Bild, derselbe Prompt. Kein Montage-Umweg, keine
Sonderfassung -- die Lehre aus dem Modellvergleich vom 2026-08-13, dessen 10/12
sich nicht auf den Produktivpfad uebertragen liessen.

Beide Achsen zaehlen: einen Schaden zu finden ist wertlos, wenn das Modell ihn
auch auf heilen Teilen findet.
"""
import asyncio
import json
import time

from app.services.assessment_media import DAMAGE_MAX_EDGE, prepare_image
from app.services.vision_client import VisionClient

# (Datei, hat_schaden, was darauf zu sehen ist)
FAELLE = [
    ("foto_4.jpg", True, "blauer 2x2 mit durchgehendem Riss"),
    ("foto_11.jpg", True, "gelber Bogenstein, ausgerissene Kerbe"),
    ("foto_10.jpg", True, "derselbe Schaden, gekippte Aufnahme"),
    ("foto_213.jpg", True, "derselbe Schaden, staerker angeschnitten"),
    ("foto_13.jpg", False, "gelber Bogenstein, sauber"),
    ("foto_3.jpg", False, "blauer 2x2, sauber"),
    ("kat_343724.jpg", False, "gelber 2x2, Katalogbild"),
    ("kat_301121.jpg", False, "roter 2x4, Katalogbild"),
]

MODELLE = ["qwen2.5vl:7b", "gemma4:12b", "minicpm-v4.5:8b"]
ERGEBNIS = "/tmp/schadensmessung.json"


async def lauf(modell: str) -> dict:
    vision = VisionClient(endpoint="http://ollama:11434", model=modell, timeout_ms=300000)
    treffer = fehlalarm = ausgefallen = 0
    zeiten: list[float] = []
    zeilen = []
    for datei, soll, was in FAELLE:
        bild = prepare_image(open(f"/korpus/{datei}", "rb").read(), max_edge=DAMAGE_MAX_EDGE)
        s = time.monotonic()
        befund = await vision.inspect_damage(bild)
        dt = time.monotonic() - s
        zeiten.append(dt)
        if not befund.ok:
            ausgefallen += 1
            marke = "AUSFALL"
        elif befund.damaged == soll:
            marke = "richtig"
            if soll:
                treffer += 1
        else:
            marke = "UEBERSEHEN" if soll else "FEHLALARM"
            if not soll:
                fehlalarm += 1
        print(f"  {datei:16} soll={'Schaden' if soll else 'heil   '} "
              f"ist={str(befund.damaged):5} {dt:5.0f}s  {marke:11} "
              f"{', '.join(befund.anomalies)[:60]}", flush=True)
        zeilen.append({"datei": datei, "soll": soll, "ist": befund.damaged,
                       "ok": befund.ok, "sekunden": round(dt, 1),
                       "anomalien": list(befund.anomalies),
                       "beschreibung": befund.description, "motiv": was})
    schaeden = sum(1 for _, s, _ in FAELLE if s)
    heile = len(FAELLE) - schaeden
    print(f"  => {modell}: Schaden {treffer}/{schaeden}, Fehlalarme {fehlalarm}/{heile}, "
          f"Ausfaelle {ausgefallen}, Median {sorted(zeiten)[len(zeiten) // 2]:.0f}s", flush=True)
    return {"modell": modell, "treffer": treffer, "von": schaeden,
            "fehlalarme": fehlalarm, "heile": heile, "ausfaelle": ausgefallen,
            "median_s": round(sorted(zeiten)[len(zeiten) // 2], 1), "faelle": zeilen}


async def main():
    alle = []
    for modell in MODELLE:
        print(f"\n=== {modell}", flush=True)
        try:
            alle.append(await lauf(modell))
        except Exception as exc:  # noqa: BLE001 - ein Modell darf die Reihe nicht toeten
            print(f"  {modell} abgebrochen: {type(exc).__name__}: {exc}", flush=True)
        json.dump(alle, open(ERGEBNIS, "w"), ensure_ascii=False, indent=1)
    print("\nFERTIG")


asyncio.run(main())
