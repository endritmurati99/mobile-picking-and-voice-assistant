"""Bildbefunde von einem lokalen Vision-Modell (Ollama).

**Zwei getrennte Aufrufe**, und das ist keine Geschmacksfrage. Im
Zwei-Bild-Aufruf hat das Modell einen sichtbaren Bruch als "decorative
element" abgetan und `damaged: false` gesetzt; derselbe Bruch wurde im
Einzelbild-Aufruf mit geschaerftem Prompt als "torn" erkannt. Der Vergleich
lenkt die Aufmerksamkeit auf Unterschiede zwischen den Bildern, die
Schadenspruefung auf die Oberflaeche eines einzelnen.

**Die Reihenfolge der JSON-Schluessel ist normativ**: erst beschreiben, dann
urteilen. Wird zuerst nach dem Urteil gefragt, antwortet das Modell aus dem
Schema statt aus dem Bild -- am 2026-08-05 gemessen, in beiden Sprachen, mit
Konfidenz 0.95 daneben.

**Der Wortlaut der Prompts ist Spezifikation, nicht Formulierung.** Ohne den
Satz ueber "ragged, torn or gouged" traf das Modell null von vier
Pruefbildern; mit ihm drei von vier, ohne einen einzigen Fehlalarm auf den
heilen Teilen.

**Zwei getrennte FELDER, ein Modell.** `describe` fragt
`vision_article_model`, `inspect_damage` fragt `vision_model`. Beide stehen
seit dem 2026-08-14 auf `gemma4:12b` (`config.py`). Die Trennung bleibt, damit
sich die Achsen einzeln umstellen lassen.

Hier stand bis zum 2026-09-15, `inspect_damage` frage `qwen2.5vl:7b` und
`gemma4:12b` sei auf der Schadensachse ungemessen. Beides ist ueberholt: Der
Wechsel am 2026-08-14 ist bei `vision_model` in `config.py` mit acht von Hand
beschrifteten Bildern belegt -- `qwen2.5vl:7b` 2/4 Schaeden, `gemma4:12b` 4/4,
beide ohne Fehlalarm. Auf der Artikelachse haelt `qwen2.5vl:7b` einen Riss fuer
ein Artikelmerkmal (Schadenstoleranz 2/6 gegen 5/6).

Jeder Fehler endet in `ok=False` mit leeren Feldern. Ein halber Befund waere
die Einladung, doch etwas daraus zu schliessen.
"""
from __future__ import annotations

import base64
import io
import math
import os
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

# Wie lange die letzten Schadensaufrufe je Modell gebraucht haben.
#
# Der Aufrufer muss vor jedem Bildaufruf wissen, ob die Restzeit noch fuer
# einen GANZEN Aufruf reicht. Bis zum 2026-09-15 stand dafuer ein fester Wert
# in der Konfiguration, und Lauf 11 hat ihn widerlegt: derselbe Prompt, fast
# dieselbe Tokenzahl (519 gegen 513), einmal 82,88 s und einmal 59,11 s. Ein
# fester Wert deckt entweder den schnellen Fall ab und laesst Aufrufe starten,
# die ihn reissen, oder den langsamen und laesst Fotos liegen, die gepasst
# haetten.
#
# Prozesslokal und absichtlich klein: nach einem Neustart gilt wieder die
# Vorgabe aus der Konfiguration. Ein Messwert, der einen Neustart ueberlebt,
# muesste gepflegt werden -- und eine kalte Maschine rechnet ohnehin anders.
_DAUERN: dict[str, deque[float]] = {}
# Ab wievielen Messungen der gemessene Wert die Vorgabe abloest. Unter drei
# Werten ist der 80-%-Wert kein Quantil, sondern ein Zufall.
_MINDESTMESSUNGEN = 3


def notiere_schadensdauer(model: str, sekunden: float) -> None:
    """Haelt die Dauer EINES abgeschlossenen Schadensaufrufs fest.

    Abgebrochene Aufrufe gehoeren NICHT hierher: ihre Dauer ist die Restzeit,
    die sie noch hatten, nicht die, die sie gebraucht haetten. Wer sie
    mitzaehlt, zieht die Schaetzung genau dann nach unten, wenn es eng wird.
    """
    _DAUERN.setdefault(model, deque(maxlen=8)).append(sekunden)


def geschaetzte_schadensdauer(model: str, vorgabe: float) -> float:
    """Womit ein Aufruf dieses Modells zu rechnen hat, in Sekunden.

    Der 80-%-Wert der letzten acht Messungen: hoch genug, dass ein einzelner
    schneller Aufruf die Schaetzung nicht zu tief zieht, und robust genug, dass
    ein einzelner Ausreisser nach oben sie nicht fuer die naechsten acht
    Aufrufe bestimmt. Der Hoechstwert waere das nicht -- nach Lauf 11 stuende
    die Schaetzung bei 83 s, und ein Foto, das in 59 s durchgelaufen waere,
    bliebe liegen.

    Vor `_MINDESTMESSUNGEN` Messungen gilt die uebergebene Vorgabe.
    """
    werte = sorted(_DAUERN.get(model, ()))
    if len(werte) < _MINDESTMESSUNGEN:
        return vorgabe
    return werte[math.ceil(0.8 * len(werte)) - 1]

# EIN Bild je Aufruf, und der Vergleich passiert spaeter im Text.
#
# Vorher lag beides in einem Aufruf: Katalogbild und Meldefoto zusammen, und das
# Modell entschied selbst. Am 2026-08-07 gemessen, warum das nicht traegt: bei
# zwei aehnlichen Bildern beschreibt `qwen2.5vl:7b` BEIDE gleich. Ein hellblauer
# Duplo-Stein gegen das gelbe Katalogbild ergab "A yellow plastic corner guard"
# fuer beide Bilder und `same_article: true` -- bei 192, 384 und 512 px, mit dem
# alten wie mit einem geschaerften Prompt. Einzeln beschreibt dasselbe Modell
# jedes Bild richtig ("A light blue LEGO brick with a printed character").
# Ein Hundefoto fiel weiter durch; die Verwechslung zweier aehnlicher Artikel --
# der Fall, der im Lager wirklich vorkommt -- nicht.
#
# Farbe und Form stehen als eigene Felder da, damit sie nicht in einem Satz
# untergehen: "gelber Stein" und "gruener Stein" unterscheiden sich in genau
# einem Wort, und dieses Wort entscheidet.
DESCRIBE_PROMPT = (
    "Describe the single object in this image factually. Ignore the background, "
    "the lighting and any hand holding it.\n"
    "Answer strictly as JSON with these keys, in this order:\n"
    '  "object_type": what kind of thing it is in two or three words '
    "(for example \"toy building brick\", \"cardboard box\", \"dog\", \"person\"),\n"
    '  "colour": the dominant colour or colours,\n'
    '  "shape": size and shape in one short phrase,\n'
    '  "markings": printed images, logos, letters or studs, or "none",\n'
    '  "is_a_product": true if this is a manufactured article, false if it is a '
    "living being, a person, a room or a landscape\n\n"
    "Do not guess and do not compare with anything - describe only what you see."
)

DAMAGE_PROMPT = (
    "You inspect a moulded plastic part before shipping.\n"
    "Answer strictly as JSON with these keys, in this order:\n"
    '  "surface_description": describe the surface: is it smooth and continuous '
    "everywhere, or is there a region that looks torn, split, gouged, ragged or "
    "broken open?,\n"
    # "short strings" war die einzige Laengenvorgabe und blieb unbestimmt.
    # Am 2026-09-15 lieferte `gemma4:12b` darauf beim Plattenfoto aus Lauf 8
    # ganze Saetze ("a large cracked area with missing pieces", 7 Woerter),
    # bei denselben Optionen und `temperature: 0` auf anderen Fotos aber
    # weiter ein Wort. Die Vorgabe nennt die Laenge deshalb jetzt in Zahlen
    # und gibt Beispiele. Die Entscheidungsregel unten bleibt unberuehrt --
    # sie betrifft `damaged`, nicht dieses Feld.
    '  "anomalies": array of short strings, ONE TO THREE WORDS EACH, for '
    "every region that breaks the smooth surface "
    '(for example "crack", "broken edge", "missing stud"). '
    "Empty array if the surface is continuous everywhere.,\n"
    '  "damaged": true or false,\n'
    '  "confidence": number 0.0 to 1.0\n\n'
    "Decisive rule: a ragged, torn or gouged area on an otherwise smooth moulded "
    "surface is DAMAGE, never decoration or a design feature. Printed logos, "
    "smooth colour changes and reflections are NOT damage. "
    "An item whose surface is continuous everywhere must get damaged false."
)

# Bildkacheln zaehlen als Token. Seit dem Umbau geht je Aufruf nur EIN Bild
# hinaus, dafuer bei der Schadenspruefung mit 768 px -- das sind rund 750
# Kacheln und passt nicht in die Standardgroesse von 4096. 8192 hat in beiden
# Messungen gereicht.
_NUM_CTX = 8192
# Gemessen am 2026-09-15 auf leerem Ollama, qwen2.5:7b, 60 Token, gleicher
# Prompt: ohne diese Option 1,21 tok/s, mit num_thread=8 7,40 tok/s (Faktor 6).
# Grund: Docker meldet 14 CPUs, der Host ist ein Intel Core Ultra 7 255H mit
# 6 P-Cores, 8 E-Cores, 2 LP-E-Cores. llama.cpp synchronisiert bei jedem Token,
# der schnellste Kern wartet auf den langsamsten. Die Umgebungsvariable
# OLLAMA_NUM_THREAD wirkt NICHT -- gemessen am selben Tag, 1,21 tok/s trotz
# gesetzter Variablen. Nur diese Option im Request wirkt.
_NUM_THREAD = int(os.environ.get("OLLAMA_NUM_THREAD", "8"))

# Warmup: ein Bild, weil erst ein Bild im Request den Projektor laedt. 64 px
# grau reicht dafuer und kostet eine Kachel -- der Inhalt ist gleichgueltig,
# geladen wird so oder so. Der Prompt verlangt dasselbe JSON-Format wie die
# echten Aufrufe, damit ollama denselben Runner mit derselben Kontextgroesse
# nimmt und nicht beim ersten echten Aufruf neu laedt (Stolperfalle 3 im
# Testlauf-Skill).
WARMUP_PROMPT = 'Answer with {"ok": true} and nothing else.'


@lru_cache(maxsize=1)
def _warmup_bild() -> bytes:
    puffer = io.BytesIO()
    Image.new("RGB", (64, 64), (128, 128, 128)).save(puffer, format="JPEG")
    return puffer.getvalue()


@dataclass(frozen=True)
class ArticleDescription:
    """Was auf EINEM Bild zu sehen ist. `ok=False` heisst: kein Befund.

    `text` ist die Zeile, die spaeter der Textvergleich liest und die im
    Widerspruchsfall bis ins Odoo-Formular durchgeht. Sie wird hier gebaut und
    nicht vom Modell formuliert, damit Farbe und Form in jeder Beschreibung an
    derselben Stelle stehen.
    """

    ok: bool
    text: str | None = None
    is_a_product: bool | None = None


@dataclass(frozen=True)
class DamageCheck:
    ok: bool
    damaged: bool | None = None
    anomalies: tuple[str, ...] = field(default_factory=tuple)
    description: str | None = None


class VisionClient:
    PROVIDER = "ollama-local"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        article_model: str | None = None,
        timeout_ms: int = 180000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        # Ohne eigenes Artikelmodell verhaelt sich der Client wie vorher: ein
        # Modell fuer beide Fragen. Das ist der Rueckweg, wenn `gemma4:12b`
        # nicht geladen ist -- eine Einstellung, kein Codeeingriff.
        self._article_model = article_model or model
        seconds = max(1.0, timeout_ms / 1000.0)
        self._timeout = httpx.Timeout(connect=5.0, read=seconds, write=30.0, pool=5.0)
        self._transport = transport

    @property
    def model(self) -> str:
        return self._model

    @property
    def article_model(self) -> str:
        return self._article_model

    async def _ask(self, prompt: str, images: list[bytes], model: str) -> dict | None:
        begonnen = time.monotonic()
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [base64.b64encode(image).decode("ascii") for image in images],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_ctx": _NUM_CTX,
                "num_thread": _NUM_THREAD,
            },
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._endpoint}/api/generate", json=payload
                )
            response.raise_for_status()
            parsed = json.loads(response.json().get("response") or "")
        except Exception as exc:  # noqa: BLE001 - jeder Fehler heisst: kein Befund
            logger.warning(json.dumps({
                "event_type": "vision_probe_failed",
                # Das TATSAECHLICH gefragte Modell, nicht `self._model`: seit
                # Artikel- und Schadensfrage auf verschiedenen Modellen liegen,
                # waere der feste Name hier eine falsche Spur im Protokoll.
                "model": model,
                # Der Typ steht dabei, weil genau hier eine Zeitgrenze mit
                # leerem `str(exc)` ankommt (httpx.ReadTimeout) und ohne ihn
                # nicht von einem Verbindungsfehler zu unterscheiden ist.
                "error_type": type(exc).__name__,
                "error": str(exc),
                "duration_ms": int((time.monotonic() - begonnen) * 1000),
            }))
            return None
        # Erfolgsfall MIT Modellnamen protokollieren, nicht nur der Fehlerfall.
        #
        # Am 2026-08-14 stand die Frage im Raum, welches Bildmodell einen
        # konkreten Lauf tatsaechlich bedient hat. Aus Odoo ist das nicht zu
        # beantworten (`ai_model` traegt das TEXTmodell und bleibt bei
        # `review_required` leer), und Ollama protokolliert je Aufruf nur Pfad
        # und Dauer, nie den Modellnamen. Damit blieb nur Indizienbeweis.
        # Diese Zeile beendet das: je Bildaufruf steht Modell und Dauer im Log.
        logger.info(json.dumps({
            "event_type": "vision_probe",
            "model": model,
            "images": len(images),
            "duration_ms": int((time.monotonic() - begonnen) * 1000),
            "ok": isinstance(parsed, dict),
        }))
        return parsed if isinstance(parsed, dict) else None

    async def describe(self, image: bytes) -> ArticleDescription:
        """Ein Bild, ein Aufruf, kein Vergleich.

        Der Vergleich zweier solcher Beschreibungen ist Sache des Textmodells
        (`LlmClient.compare_articles`). Diese Trennung IST der Fix: siehe die
        Messung ueber `DESCRIBE_PROMPT`.
        """
        parsed = await self._ask(DESCRIBE_PROMPT, [image], self._article_model)
        if parsed is None:
            return ArticleDescription(ok=False)
        teile = [
            _text(parsed.get("object_type")),
            _text(parsed.get("colour")),
            _text(parsed.get("shape")),
        ]
        markings = _text(parsed.get("markings"))
        if markings and markings.lower() not in ("none", "keine", "no markings"):
            teile.append(markings)
        text = ", ".join(part for part in teile if part)
        if not text:
            # Ein Aufruf, der antwortet aber nichts benennt, ist kein Befund.
            # Eine leere Beschreibung im Textvergleich waere schlimmer als
            # keine: sie liesse sich mit allem als "gleich" lesen.
            return ArticleDescription(ok=False)
        product = parsed.get("is_a_product")
        return ArticleDescription(
            ok=True,
            text=text,
            is_a_product=product if isinstance(product, bool) else None,
        )

    async def warmup(self) -> bool:
        """Laedt das Bildmodell samt Projektor in den Ollama-Speicher.

        Ohne das zahlt der ERSTE echte Aufruf den Kaltstart -- gemessen 80-145 s
        -- und zwar aus dem Zeitbudget der ersten Meldung heraus. Bei 255 s
        Anruferfrist prueft die Kette dann statt drei Fotos eines.

        Mit Bild, nicht mit reinem Text: erst ein Bild im Request laedt den
        Projektor. Ein Textaufruf laedt nur die Sprachhaelfte und laesst die
        andere fuer den ersten echten Aufruf liegen.

        Fehler sind geschluckt -- `_ask` gibt bei jedem Fehler `None` zurueck.
        Warmup ist best-effort und darf einen Start nie verhindern.
        """
        ok = await self._ask(WARMUP_PROMPT, [_warmup_bild()], self._model) is not None
        if self._article_model != self._model:
            ok = (
                await self._ask(
                    WARMUP_PROMPT, [_warmup_bild()], self._article_model
                )
                is not None
                and ok
            )
        return ok

    async def inspect_damage(self, candidate: bytes) -> DamageCheck:
        begonnen = time.monotonic()
        parsed = await self._ask(DAMAGE_PROMPT, [candidate], self._model)
        # Auch ein Aufruf ohne verwertbare Antwort hat seine Zeit gekostet und
        # gehoert in die Schaetzung. Ein ABGEBROCHENER kommt hier nie an --
        # `_in_restzeit` bricht die Koroutine ab, und das ist richtig so.
        notiere_schadensdauer(self._model, time.monotonic() - begonnen)
        if parsed is None or not isinstance(parsed.get("damaged"), bool):
            return DamageCheck(ok=False)
        raw = parsed.get("anomalies")
        anomalies: tuple[str, ...] = ()
        if isinstance(raw, list):
            anomalies = tuple(
                cleaned for cleaned in (str(item).strip() for item in raw) if cleaned
            )
        return DamageCheck(
            ok=True,
            damaged=parsed["damaged"],
            anomalies=anomalies,
            description=_text(parsed.get("surface_description")),
        )


def _text(value) -> str | None:
    """Leerer Text ist `None`, damit spaeter nichts Leeres im Klartext steht.

    Listen werden zusammengezogen. Das Modell antwortet fuer `colour` mal mit
    einem String und mal mit einer Liste; ohne diesen Zweig landete am
    2026-08-08 woertlich `plate of food, ['white', 'brown'], round plate` im
    Odoo-Formular. Ein Mensch liest dort keine Python-Repraesentation.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        teile = [str(item).strip() for item in value]
        return ", ".join(teil for teil in teile if teil) or None
    return str(value).strip() or None


def _selbstpruefung() -> None:
    """Prueft das Warmup ohne Ollama: `python -m app.services.vision_client`.

    Drei Zusagen, an denen es haengt: das Warmbild ist ein gueltiges JPEG, der
    Aufruf geht mit Bild hinaus (sonst bleibt der Projektor ungeladen), und ein
    Ausfall von Ollama bleibt ein `False` statt einer Ausnahme -- sonst
    verhinderte ein abgeschaltetes Ollama den Start des Backends.
    """
    import asyncio as _asyncio

    bild = _warmup_bild()
    assert bild[:2] == b"\xff\xd8", "Warmbild ist kein JPEG"
    assert Image.open(io.BytesIO(bild)).size == (64, 64)

    gesehen: list[dict] = []

    def antwort(request: httpx.Request) -> httpx.Response:
        gesehen.append(json.loads(request.content))
        return httpx.Response(200, json={"response": '{"ok": true}'})

    client = VisionClient(
        endpoint="http://ollama:11434",
        model="bildmodell",
        article_model="artikelmodell",
        transport=httpx.MockTransport(antwort),
    )
    assert _asyncio.run(client.warmup()) is True
    assert [p["model"] for p in gesehen] == ["bildmodell", "artikelmodell"], gesehen
    assert all(p["images"] for p in gesehen), "Warmup ohne Bild laedt keinen Projektor"
    assert all(p["options"]["num_ctx"] == _NUM_CTX for p in gesehen)

    def kaputt(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    taub = VisionClient(
        endpoint="http://ollama:11434",
        model="bildmodell",
        transport=httpx.MockTransport(kaputt),
    )
    assert _asyncio.run(taub.warmup()) is False, "Ausfall muss False sein, nicht werfen"
    print("vision_client Selbstpruefung ok")


if __name__ == "__main__":
    _selbstpruefung()
