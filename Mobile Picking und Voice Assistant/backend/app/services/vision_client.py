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

Jeder Fehler endet in `ok=False` mit leeren Feldern. Ein halber Befund waere
die Einladung, doch etwas daraus zu schliessen.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

ARTICLE_PROMPT = (
    "You receive two images.\n"
    "IMAGE 1 is the official catalogue photo of the article that SHOULD be in "
    "the box.\n"
    "IMAGE 2 is the photo a warehouse worker just took of the item in front of "
    "them.\n\n"
    "Answer strictly as JSON with these keys, in this order:\n"
    '  "image1_shows": short factual description of image 1,\n'
    '  "image2_shows": short factual description of image 2,\n'
    '  "same_article": true or false - is image 2 the same kind of article as '
    "image 1?,\n"
    '  "same_article_reason": one short sentence\n\n'
    "Rules: describe before you judge. Do not guess. If image 2 shows something "
    "that is not a product at all (a person, an animal, a room), set "
    "same_article false and say so."
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

# Bildkacheln zaehlen als Token. Zwei Bilder zu 512 px passen nicht in die
# Standardgroesse von 4096; 8192 hat in der Messung gereicht.
_NUM_CTX = 8192


@dataclass(frozen=True)
class ArticleMatch:
    """`ok=False` heisst: kein Befund. Nicht "kein Treffer"."""

    ok: bool
    same_article: bool | None = None
    reason: str | None = None
    candidate_description: str | None = None


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
        timeout_ms: int = 180000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        seconds = max(1.0, timeout_ms / 1000.0)
        self._timeout = httpx.Timeout(connect=5.0, read=seconds, write=30.0, pool=5.0)
        self._transport = transport

    @property
    def model(self) -> str:
        return self._model

    async def _ask(self, prompt: str, images: list[bytes]) -> dict | None:
        payload = {
            "model": self._model,
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
                "model": self._model,
                # Der Typ steht dabei, weil genau hier eine Zeitgrenze mit
                # leerem `str(exc)` ankommt (httpx.ReadTimeout) und ohne ihn
                # nicht von einem Verbindungsfehler zu unterscheiden ist.
                "error_type": type(exc).__name__,
                "error": str(exc),
            }))
            return None
        return parsed if isinstance(parsed, dict) else None

    async def compare_article(self, reference: bytes, candidate: bytes) -> ArticleMatch:
        """Katalogbild ZUERST -- die Prompt-Zuordnung haengt an der Position."""
        parsed = await self._ask(ARTICLE_PROMPT, [reference, candidate])
        if parsed is None or not isinstance(parsed.get("same_article"), bool):
            return ArticleMatch(ok=False)
        return ArticleMatch(
            ok=True,
            same_article=parsed["same_article"],
            reason=_text(parsed.get("same_article_reason")),
            candidate_description=_text(parsed.get("image2_shows")),
        )

    async def inspect_damage(self, candidate: bytes) -> DamageCheck:
        parsed = await self._ask(DAMAGE_PROMPT, [candidate])
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
    """Leerer Text ist `None`, damit spaeter nichts Leeres im Klartext steht."""
    return str(value).strip() or None if value is not None else None
