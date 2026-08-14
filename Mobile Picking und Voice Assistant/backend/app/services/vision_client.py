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

**Zwei getrennte MODELLE, seit dem 2026-08-14.** `describe` fragt
`vision_article_model` (`gemma4:12b`), `inspect_damage` fragt `vision_model`
(`qwen2.5vl:7b`). Begruendung und Messwerte stehen bei den beiden Feldern in
`config.py`; kurz: auf der Artikelachse haelt `qwen2.5vl:7b` einen Riss fuer
ein Artikelmerkmal (Schadenstoleranz 2/6 gegen 5/6), auf der Schadensachse ist
es bei 1024 px eingemessen und `gemma4:12b` ungemessen.

Jeder Fehler endet in `ok=False` mit leeren Feldern. Ein halber Befund waere
die Einladung, doch etwas daraus zu schliessen.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

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
    '  "anomalies": array of short strings for every region that breaks the '
    "smooth surface. Empty array if the surface is continuous everywhere.,\n"
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
            "options": {"temperature": 0, "num_ctx": _NUM_CTX},
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

    async def inspect_damage(self, candidate: bytes) -> DamageCheck:
        parsed = await self._ask(DAMAGE_PROMPT, [candidate], self._model)
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
