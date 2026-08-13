#!/usr/bin/env python3
"""Nicht fragen, sondern messen: Artikelabgleich ueber Bildeinbettungen.

Der bisherige Weg laesst ein Sprachmodell entscheiden, ob zwei Teile derselbe
Artikel sind. Ein Sprachmodell erzaehlt dabei -- und das auffaelligste Merkmal
eines beschaedigten Teils ist der Schaden. Deshalb urteilt es "anderer Artikel",
obwohl im Prompt ausdruecklich steht, dass Schaden nicht zaehlt.

Eine Einbettung erzaehlt nicht. Sie bildet jedes Bild auf einen Vektor ab; die
Entscheidung ist ein Abstand. Ein gerissener blauer Stein bleibt einem heilen
blauen Stein naeher als einem gruenen -- der Riss verschiebt den Vektor kaum.
Ausserdem faellt damit die 1:1-Frage weg: man kann das Foto gegen ALLE 47
Katalogbilder halten und schauen, ob der richtige Artikel auf Platz 1 landet.
Das ist die Frage, die im Betrieb zaehlt, und sie liefert einen Abstand als
Konfidenz statt eines Muenzwurfs.

Gemessen werden zwei Ruecken: `facebook/dinov2-base` (selbstueberwacht, laut
Literatur stark bei Instanzwiedererkennung) und `google/siglip2-base-patch16-224`
(bild-text-ausgerichtet, staerker semantisch).
"""
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel

BILDER = Path("/bilder")

# Von Hand geprueft am 2026-08-13 -- dieselben zwoelf Faelle wie beim
# Modellvergleich, damit die Zahlen vergleichbar sind.
FAELLE = [
    ("S1_blau_riss", "kat_4166960", "foto_4", True),
    ("S2_bogen_kerbe_a", "kat_6023350", "foto_11", True),
    ("S3_bogen_kerbe_b", "kat_6023350", "foto_213", True),
    ("S4_bogen_kerbe_c", "kat_6023350", "foto_10", True),
    ("S5_bogen_sauber", "kat_6023350", "foto_13", True),
    ("A1_gruen_blau", "kat_301124", "foto_3", False),
    ("A2_2x2_gegen_2x3", "kat_343724", "foto_12", False),
    ("A3_bogen_gegen_2x3", "kat_6023350", "foto_12", False),
    ("A4_bogen_gegen_blau", "kat_6023350", "foto_4", False),
    ("A5_blau_gegen_2x3", "kat_4166960", "foto_12", False),
    ("A6_hund", "kat_6023350", "foto_14", False),
]

# Foto -> Artikel, den es zeigt. Nur die Motive, die ich selbst angesehen habe.
WAHRHEIT = {
    "foto_4": "kat_4166960",    # blauer 2x2 mit Riss
    "foto_3": "kat_4166960",    # blauer 2x2 sauber
    "foto_11": "kat_6023350",   # gelber Bogenstein mit Kerbe
    "foto_213": "kat_6023350",
    "foto_10": "kat_6023350",
    "foto_13": "kat_6023350",   # gelber Bogenstein sauber
    "foto_14": None,            # Hund -- darf KEINEN Artikel treffen
}


def einbetten(modellname):
    verarbeiter = AutoImageProcessor.from_pretrained(modellname)
    modell = AutoModel.from_pretrained(modellname).eval()
    if hasattr(modell, "vision_model"):
        modell = modell.vision_model

    vektoren = {}
    dateien = sorted(BILDER.glob("*.jpg"))
    for nummer, pfad in enumerate(dateien, start=1):
        bild = Image.open(pfad).convert("RGB")
        with torch.no_grad():
            eingabe = verarbeiter(images=bild, return_tensors="pt")
            ausgabe = modell(**eingabe)
            # Mittel ueber die Patch-Vektoren: robuster gegen Randeffekte als
            # der CLS-Vektor allein, wenn das Objekt nicht zentriert sitzt.
            v = ausgabe.last_hidden_state[:, 1:, :].mean(dim=1).squeeze(0).numpy()
        vektoren[pfad.stem] = v / (np.linalg.norm(v) + 1e-9)
        if nummer % 25 == 0:
            print(f"  {nummer}/{len(dateien)}", flush=True)
    return vektoren


def auswerten(modellname, vektoren):
    print(f"\n{'=' * 62}\n{modellname}\n{'=' * 62}", flush=True)

    print("\nDie zwoelf Faelle (Kosinus-Aehnlichkeit):", flush=True)
    werte = []
    for name, links, rechts, soll in FAELLE:
        if links not in vektoren or rechts not in vektoren:
            print(f"  {name}: Bild fehlt")
            continue
        s = float(np.dot(vektoren[links], vektoren[rechts]))
        werte.append((name, s, soll))
        print(f"  {name:22s} {s: .4f}   soll={'GLEICH' if soll else 'anders'}", flush=True)

    gleich = [s for _, s, k in werte if k]
    anders = [s for _, s, k in werte if not k]
    if gleich and anders:
        print(f"\n  gleich:  min {min(gleich):.4f}  max {max(gleich):.4f}", flush=True)
        print(f"  anders:  min {min(anders):.4f}  max {max(anders):.4f}", flush=True)
        trennbar = min(gleich) > max(anders)
        print(f"  SAUBER TRENNBAR: {'JA' if trennbar else 'NEIN'}"
              f"{'' if trennbar else '  (Ueberlappung -- eine Schwelle reicht nicht)'}", flush=True)
        beste, bester_wert = 0, -1
        for schwelle in np.arange(0.0, 1.0, 0.005):
            richtig = sum(1 for _, s, k in werte if (s >= schwelle) == k)
            if richtig > bester_wert:
                beste, bester_wert = schwelle, richtig
        print(f"  beste Schwelle {beste:.3f} -> {bester_wert}/{len(werte)} richtig", flush=True)

    print("\nAbruf: welches Katalogbild ist dem Foto am naechsten?", flush=True)
    katalog = {k: v for k, v in vektoren.items() if k.startswith("kat_")}
    treffer = gesamt = 0
    for foto, soll in WAHRHEIT.items():
        if foto not in vektoren:
            continue
        rang = sorted(((float(np.dot(vektoren[foto], v)), k) for k, v in katalog.items()),
                      reverse=True)
        spitze = ", ".join(f"{k[4:]} {s:.3f}" for s, k in rang[:3])
        if soll is None:
            print(f"  {foto:10s} (Hund)      -> {spitze}", flush=True)
            continue
        gesamt += 1
        ok = rang[0][1] == soll
        treffer += ok
        print(f"  {foto:10s} soll {soll[4:]:9s} -> {spitze}   {'TREFFER' if ok else 'DANEBEN'}",
              flush=True)
    if gesamt:
        print(f"\n  Platz 1 richtig: {treffer}/{gesamt}", flush=True)


if __name__ == "__main__":
    for modellname in sys.argv[1:]:
        print(f"\nlade {modellname} ...", flush=True)
        try:
            auswerten(modellname, einbetten(modellname))
        except Exception as fehler:
            print(f"  {modellname} gescheitert: {type(fehler).__name__}: {fehler}", flush=True)
