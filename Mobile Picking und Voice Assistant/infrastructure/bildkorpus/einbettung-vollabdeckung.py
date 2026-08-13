#!/usr/bin/env python3
"""Alle Artikel gegeneinander -- in Sekunden statt in anderthalb Stunden.

Der Lauf, den der Bildsprachweg nicht schafft: JEDER bebilderte Artikel bekommt
ein abgeleitetes Bild (gedreht, verkleinert, neu komprimiert) und wird gegen
ALLE Katalogbilder gehalten. Landet der eigene Artikel auf Platz 1?

Das ist die Frage aus dem Betrieb. Nicht "sind diese zwei gleich" (dafuer muss
man eine Schwelle raten), sondern "welcher Artikel ist das" -- und die Antwort
bringt einen Abstand zum Zweitplatzierten mit, also ein Mass fuer die
Sicherheit des Urteils.

Zusaetzlich geprueft: die Farbschwaeche. DINOv2 gab einem gruenen und einem
blauen 2x2-Stein 0.9157 Aehnlichkeit -- die Form dominiert. Deshalb hier ein
zweiter Kanal aus dem Farbhistogramm und die Frage, ob die Kombination die
Verwechslungen aufloest, die die reine Form uebrig laesst.
"""
import io
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel

BILDER = Path("/bilder")

WAHRHEIT = {
    "foto_4": "kat_4166960", "foto_3": "kat_4166960",
    "foto_11": "kat_6023350", "foto_213": "kat_6023350",
    "foto_10": "kat_6023350", "foto_13": "kat_6023350",
    "foto_14": None,
}


def abgeleitet(pfad):
    """Aus dem Katalogbild ein 'geliefertes Teil' machen -- ohne neue Aufnahme."""
    teil = Image.open(pfad).convert("RGB")
    teil = teil.rotate(25, expand=True, fillcolor=(255, 255, 255), resample=Image.BICUBIC)
    teil = teil.resize((max(8, int(teil.width * 0.8)), max(8, int(teil.height * 0.8))),
                       Image.LANCZOS)
    puffer = io.BytesIO()
    teil.save(puffer, format="JPEG", quality=80)
    return Image.open(io.BytesIO(puffer.getvalue())).convert("RGB")


def farbvektor(bild):
    """Farbhistogramm ohne den weissen Hintergrund.

    Katalogrenderings stehen auf Weiss, Fotos auf hellem Grund. Wer den
    Hintergrund mitzaehlt, misst die Freistellung statt das Teil.
    """
    klein = bild.resize((64, 64), Image.LANCZOS)
    punkte = np.asarray(klein, dtype=np.float32).reshape(-1, 3)
    hell = punkte.max(axis=1)
    dunkel = punkte.min(axis=1)
    ist_teil = ~((hell > 225) & ((hell - dunkel) < 28))
    if ist_teil.sum() < 40:
        ist_teil = np.ones(len(punkte), dtype=bool)
    punkte = punkte[ist_teil]
    kanten = np.linspace(0, 256, 9)
    hist = []
    for kanal in range(3):
        h, _ = np.histogram(punkte[:, kanal], bins=kanten)
        hist.append(h)
    v = np.concatenate(hist).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def main(modellname):
    verarbeiter = AutoImageProcessor.from_pretrained(modellname)
    modell = AutoModel.from_pretrained(modellname).eval()
    if hasattr(modell, "vision_model"):
        modell = modell.vision_model

    def einbetten(bild):
        with torch.no_grad():
            a = modell(**verarbeiter(images=bild, return_tensors="pt"))
            v = a.last_hidden_state[:, 1:, :].mean(dim=1).squeeze(0).numpy()
        return v / (np.linalg.norm(v) + 1e-9)

    katalog_dateien = sorted(BILDER.glob("kat_*.jpg"))
    print(f"{len(katalog_dateien)} Katalogartikel\n", flush=True)

    form, farbe, form_var, farbe_var = {}, {}, {}, {}
    import time
    begonnen = time.monotonic()
    for pfad in katalog_dateien:
        k = pfad.stem
        original = Image.open(pfad).convert("RGB")
        variante = abgeleitet(pfad)
        form[k], farbe[k] = einbetten(original), farbvektor(original)
        form_var[k], farbe_var[k] = einbetten(variante), farbvektor(variante)
    dauer = time.monotonic() - begonnen
    print(f"{2 * len(katalog_dateien)} Bilder eingebettet in {dauer:.0f}s "
          f"({dauer / (2 * len(katalog_dateien)):.2f}s je Bild)\n", flush=True)

    for gewicht in (0.0, 0.25, 0.4):
        treffer, knapp, daneben = 0, [], []
        abstaende = []
        for k in form:
            rang = sorted(
                ((float((1 - gewicht) * np.dot(form_var[k], form[a])
                        + gewicht * np.dot(farbe_var[k], farbe[a])), a) for a in form),
                reverse=True,
            )
            if rang[0][1] == k:
                treffer += 1
                abstaende.append(rang[0][0] - rang[1][0])
                if rang[0][0] - rang[1][0] < 0.02:
                    knapp.append((k, rang[1][1], rang[0][0] - rang[1][0]))
            else:
                daneben.append((k, rang[0][1], rang[0][0]))
        art = "nur Form" if gewicht == 0 else f"Form + {gewicht:.0%} Farbe"
        print(f"{art:22s} Platz 1 richtig: {treffer}/{len(form)}"
              f"   mittlerer Abstand zum Zweiten: {np.mean(abstaende):.3f}", flush=True)
        for k, falsch, _ in daneben:
            print(f"    DANEBEN {k[4:]:10s} -> {falsch[4:]}", flush=True)
        for k, zweiter, d in knapp[:5]:
            print(f"    knapp   {k[4:]:10s} vor {zweiter[4:]:10s} ({d:.4f})", flush=True)
        print(flush=True)

    print("Echte Meldefotos gegen den Katalog:", flush=True)
    for foto, soll in WAHRHEIT.items():
        pfad = BILDER / f"{foto}.jpg"
        if not pfad.exists():
            continue
        v = einbetten(Image.open(pfad).convert("RGB"))
        rang = sorted(((float(np.dot(v, form[a])), a) for a in form), reverse=True)
        spitze = ", ".join(f"{a[4:]} {s:.3f}" for s, a in rang[:2])
        marke = "(Hund, darf nichts treffen)" if soll is None else (
            "TREFFER" if rang[0][1] == soll else "DANEBEN")
        print(f"  {foto:9s} -> {spitze}   {marke}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "facebook/dinov2-base")
