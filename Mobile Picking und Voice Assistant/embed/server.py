"""Artikelabgleich als Abstand statt als Urteil.

**Warum es diesen Dienst gibt.** Der Artikelabgleich der Bewertungskette hat ein
Sprachmodell gefragt, ob zwei Teile derselbe Artikel sind. Ein Sprachmodell
erzaehlt dabei, und das auffaelligste Merkmal eines beschaedigten Teils ist der
Schaden -- also urteilt es "anderer Artikel", obwohl im Prompt woertlich steht,
dass Schaden nicht zaehlt. Gemessen am 2026-08-13 gegen zwoelf von Hand
gepruefte Faelle: `qwen2.5vl:7b` 6/12, davon auf der Schadensachse 2/6.

Eine Einbettung erzaehlt nicht. Sie bildet jedes Bild auf einen Vektor ab; die
Entscheidung ist ein Abstand. Gemessen mit `facebook/dinov2-base` auf denselben
Bildern: der gelbe Bogenstein hat sauber 0.990 Aehnlichkeit zu seinem
Katalogbild, mit ausgerissener Kerbe 0.819-0.849 -- und bleibt in beiden Faellen
auf Platz 1 vor allen 43 anderen Artikeln. Ein Hundefoto kommt auf 0.047.

**Es wird abgerufen, nicht verglichen.** Die Frage "sind diese zwei gleich"
braucht eine geratene Schwelle, und die ist nicht sauber ziehbar: gemessen
reichen die gleichen Paare von 0.82 aufwaerts, die verschiedenen bis 0.92
hinauf -- die Bereiche ueberlappen. Die Frage "welcher der bekannten Artikel
ist das" braucht keine Schwelle. Sie liefert eine Rangfolge und den Abstand zum
Zweitplatzierten als Mass fuer die Sicherheit.

**Zwei Kanaele.** DINOv2 ist formdominant: ein gruener und ein blauer 2x2-Stein
kommen auf 0.9157. Ueber alle 44 bebilderten Artikel gemessen (jeder gegen ein
gedrehtes, verkleinertes Abbild seiner selbst) landet die reine Form 33/44 mal
richtig auf Platz 1; mit einem Viertel Farbhistogramm dazu sind es 41/44, und
der mittlere Abstand zum Zweiten verdoppelt sich von 0.051 auf 0.101.
"""
from __future__ import annotations

import base64
import binascii
import io
import os
import threading
import time

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from transformers import AutoImageProcessor, AutoModel

MODELL = os.environ.get("EINBETT_MODELL", "facebook/dinov2-base")

# Anteil des Farbkanals am Gesamturteil. 0.25 ist gemessen, nicht geschaetzt:
# 0.0 -> 33/44, 0.25 -> 41/44, 0.40 -> 41/44 bei groesserem Abstand, aber ab
# dort entscheidet zunehmend die Beleuchtung statt das Teil.
FARBGEWICHT = float(os.environ.get("EINBETT_FARBGEWICHT", "0.25"))

# Unterhalb dieser Aehnlichkeit gehoert das Bild zu KEINEM bekannten Artikel.
# Gemessen: echte Teile 0.819-0.997, das Hundefoto 0.047. Dazwischen liegt eine
# Groessenordnung; 0.45 sitzt mit reichlich Luft in der Luecke.
FREMD_SCHWELLE = float(os.environ.get("EINBETT_FREMD_SCHWELLE", "0.45"))

# Ist der Abstand zwischen Platz 1 und Platz 2 kleiner als das, sind sich zwei
# Artikel im Sortiment zu aehnlich, um sie am Bild zu trennen. Gemessen gibt es
# solche Paare wirklich (`6167549` gegen `6171865`). Dann faellt kein Urteil,
# sondern der Fall geht an den Menschen -- das ist billiger als ein falsches
# `mismatch`, das eine echte Schadensmeldung abweist.
KNAPP_SCHWELLE = float(os.environ.get("EINBETT_KNAPP_SCHWELLE", "0.02"))

app = FastAPI(title="Bildeinbettung fuer den Artikelabgleich")

_sperre = threading.Lock()
_verarbeiter = None
_modell = None
# kennung -> (formvektor, farbvektor)
_katalog: dict[str, tuple[np.ndarray, np.ndarray]] = {}
_katalog_stand = 0.0


def _laden():
    global _verarbeiter, _modell
    if _modell is None:
        _verarbeiter = AutoImageProcessor.from_pretrained(MODELL)
        rumpf = AutoModel.from_pretrained(MODELL).eval()
        # SigLIP und CLIP tragen den Bildteil unter `vision_model`; DINOv2 ist
        # schon einer. So bleibt der Dienst gegen einen Modellwechsel offen.
        _modell = getattr(rumpf, "vision_model", rumpf)
    return _verarbeiter, _modell


def _bild(roh_b64: str) -> Image.Image:
    try:
        return Image.open(io.BytesIO(base64.b64decode(roh_b64))).convert("RGB")
    except (binascii.Error, UnidentifiedImageError, OSError, ValueError) as fehler:
        raise HTTPException(status_code=422, detail=f"Bild nicht lesbar: {fehler}")


def _formvektor(bild: Image.Image) -> np.ndarray:
    verarbeiter, modell = _laden()
    with torch.no_grad():
        ausgabe = modell(**verarbeiter(images=bild, return_tensors="pt"))
        # Mittel ueber die Patch-Vektoren statt des CLS-Vektors allein: das Teil
        # sitzt auf Lagerfotos selten mittig, und der CLS-Vektor gewichtet die
        # Bildmitte staerker.
        v = ausgabe.last_hidden_state[:, 1:, :].mean(dim=1).squeeze(0).numpy()
    return v / (np.linalg.norm(v) + 1e-9)


def _farbvektor(bild: Image.Image) -> np.ndarray:
    """Farbhistogramm OHNE den Hintergrund.

    Katalogbilder sind freigestellte Renderings auf Weiss, Meldefotos stehen auf
    hellem Grund. Wer den Hintergrund mitzaehlt, misst die Freistellung statt
    das Teil -- dann sind sich alle Katalogbilder untereinander aehnlich.
    """
    punkte = np.asarray(bild.resize((64, 64), Image.LANCZOS), dtype=np.float32)
    punkte = punkte.reshape(-1, 3)
    hell, dunkel = punkte.max(axis=1), punkte.min(axis=1)
    ist_teil = ~((hell > 225) & ((hell - dunkel) < 28))
    if ist_teil.sum() < 40:  # fast alles Hintergrund -> lieber alles zaehlen
        ist_teil = np.ones(len(punkte), dtype=bool)
    punkte = punkte[ist_teil]
    kanten = np.linspace(0, 256, 9)
    hist = np.concatenate([np.histogram(punkte[:, k], bins=kanten)[0] for k in range(3)])
    v = hist.astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def _wert(kandidat: tuple[np.ndarray, np.ndarray],
          eintrag: tuple[np.ndarray, np.ndarray]) -> float:
    form = float(np.dot(kandidat[0], eintrag[0]))
    farbe = float(np.dot(kandidat[1], eintrag[1]))
    return (1.0 - FARBGEWICHT) * form + FARBGEWICHT * farbe


class Artikel(BaseModel):
    kennung: str
    bild_b64: str


class KatalogAnfrage(BaseModel):
    artikel: list[Artikel] = Field(min_length=1)


class AbgleichAnfrage(BaseModel):
    bild_b64: str
    erwartet: str | None = None


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "modell": MODELL,
        "katalog": len(_katalog),
        "katalog_stand": _katalog_stand,
        "geladen": _modell is not None,
    }


@app.post("/katalog")
def katalog_setzen(anfrage: KatalogAnfrage) -> dict:
    """Den Katalog einmal einbetten und halten.

    Das ist der Grund, warum der Abruf im Betrieb billig ist: die 44
    Katalogbilder werden einmal durchgerechnet, danach kostet eine Meldung
    genau eine Einbettung plus 44 Skalarprodukte.
    """
    global _katalog_stand
    begonnen = time.monotonic()
    neu: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for eintrag in anfrage.artikel:
        bild = _bild(eintrag.bild_b64)
        neu[eintrag.kennung] = (_formvektor(bild), _farbvektor(bild))
    with _sperre:
        _katalog.clear()
        _katalog.update(neu)
        _katalog_stand = time.time()
    dauer = time.monotonic() - begonnen
    return {"artikel": len(neu), "sekunden": round(dauer, 1),
            "je_bild": round(dauer / max(1, len(neu)), 2)}


@app.post("/abgleich")
def abgleich(anfrage: AbgleichAnfrage) -> dict:
    """Welcher bekannte Artikel ist das? Rangfolge statt Ja/Nein.

    `urteil` kennt drei Werte, nicht zwei:
      `match`     der erwartete Artikel steht auf Platz 1, mit Abstand.
      `mismatch`  ein anderer Artikel steht auf Platz 1, mit Abstand.
      `unsicher`  entweder gehoert das Bild zu keinem Artikel (Hundefoto), oder
                  Platz 1 und 2 liegen zu dicht beieinander. Beides gehoert zum
                  Menschen und NICHT zu einem geratenen Ja/Nein.
    """
    if not _katalog:
        raise HTTPException(status_code=409, detail="Kein Katalog hinterlegt.")
    begonnen = time.monotonic()
    bild = _bild(anfrage.bild_b64)
    kandidat = (_formvektor(bild), _farbvektor(bild))
    with _sperre:
        rang = sorted(((_wert(kandidat, e), k) for k, e in _katalog.items()), reverse=True)

    spitze, zweiter = rang[0], (rang[1] if len(rang) > 1 else (0.0, None))
    abstand = spitze[0] - zweiter[0]

    if spitze[0] < FREMD_SCHWELLE:
        urteil, grund = "unsicher", (
            f"Kein bekannter Artikel: beste Uebereinstimmung {spitze[0]:.3f} "
            f"unter der Schwelle {FREMD_SCHWELLE:.2f}."
        )
    elif abstand < KNAPP_SCHWELLE:
        urteil, grund = "unsicher", (
            f"{spitze[1]} und {zweiter[1]} liegen zu dicht beieinander "
            f"({abstand:.4f}) -- am Bild nicht trennbar."
        )
    elif anfrage.erwartet is None:
        urteil, grund = "match", f"Naechster Artikel: {spitze[1]} ({spitze[0]:.3f})."
    elif spitze[1] == anfrage.erwartet:
        urteil, grund = "match", (
            f"Stimmt mit dem Katalogbild ueberein ({spitze[0]:.3f}, "
            f"Abstand zum naechsten Artikel {abstand:.3f})."
        )
    else:
        platz = next((n for n, (_, k) in enumerate(rang, 1) if k == anfrage.erwartet), None)
        urteil, grund = "mismatch", (
            f"Foto passt zu {spitze[1]} ({spitze[0]:.3f}), nicht zum bestellten "
            f"Artikel {anfrage.erwartet}"
            + (f" (dort Platz {platz})." if platz else " (nicht im Katalog).")
        )

    return {
        "urteil": urteil, "grund": grund,
        "rang": [{"kennung": k, "wert": round(w, 4)} for w, k in rang[:5]],
        "abstand": round(abstand, 4),
        "sekunden": round(time.monotonic() - begonnen, 2),
    }
