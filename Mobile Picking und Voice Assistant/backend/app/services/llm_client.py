"""Lokaler LLM-Client (Ollama) fuer die Qualitaetsbewertung aus dem TEXT.

Laeuft offline auf dem Lab-PC gegen einen Ollama-Container. Erzwingt
JSON-Output (`format: "json"`) und liefert bei jedem Fehler `ok=False` -- der
Workflow meldet dann `review_required` statt eines Ersatzurteils. Eine
Heuristik als Rueckfallebene gibt es seit dem v2-Umbau nicht mehr; sie stand
in den geloeschten v1-Workflows.

Den Bildbefund liefert `vision_client` getrennt. Dieses Modell bekommt ihn
bewusst NICHT: nur so laesst sich sein Urteil anschliessend dagegen pruefen.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Die vier Dispositionen der Kette. Sie stehen auch in `quality_alert.py`
# als Auswahlwerte -- wer hier etwas hinzufuegt, muss dort nachziehen.
VALID_DISPOSITIONS = ("scrap", "quarantine", "rework", "sellable")

# Deterministische Handlungsempfehlung je Disposition. Bewusst NICHT vom
# Modell formuliert: was ein Lager tun soll, ist eine Festlegung des
# Betriebs und keine Frage an ein Sprachmodell.
RECOMMENDED_ACTIONS = {
    "scrap": "Ware sperren, aussondern und Schichtleitung informieren.",
    "quarantine": "Ware sperren und manuelle Pruefung anfordern.",
    "rework": "Nacharbeit pruefen und Verpackung korrigieren.",
    "sellable": "Sichtpruefung durch Qualitaetsteam.",
}

_SYSTEM_PROMPT = (
    "Du bist Qualitaetspruefer in einem Lager und klassifizierst eine gemeldete "
    "Qualitaetsstoerung in genau eine Disposition. "
    "scrap = Totalschaden/unbrauchbar, quarantine = sperren und pruefen, "
    "rework = Nacharbeit moeglich, sellable = verkaufsfaehig/kein relevanter Mangel. "
    "Nutze ausschliesslich die gegebene Beschreibung und den Kontext, erfinde keine Fakten. "
    "Antworte ausschliesslich mit JSON der Form "
    '{"disposition": <scrap|quarantine|rework|sellable>, '
    '"confidence": <Zahl 0..1>, "summary": <kurze deutsche Begruendung, max 200 Zeichen>}.'
)


@dataclass(frozen=True)
class LlmDispositionResult:
    ok: bool
    model: str
    disposition: str | None = None
    confidence: float | None = None
    summary: str | None = None
    recommended_action: str | None = None


class LlmClient:
    PROVIDER = "ollama-local"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        timeout_ms: int = 30000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        seconds = max(1.0, timeout_ms / 1000.0)
        self._timeout = httpx.Timeout(connect=5.0, read=seconds, write=10.0, pool=5.0)
        self._transport = transport

    def _build_user_prompt(
        self,
        *,
        description: str,
        priority: str,
        photo_count: int,
        product_id: int | None,
        location_id: int | None,
    ) -> str:
        lines = [
            f"Beschreibung: {description.strip() or '<leer>'}",
            f"Prioritaet: {priority}",
            f"Fotos vorhanden: {'ja (' + str(photo_count) + ')' if photo_count > 0 else 'nein'}",
        ]
        if product_id:
            lines.append(f"Produkt-ID: {product_id}")
        if location_id:
            lines.append(f"Lagerort-ID: {location_id}")
        # Hier stand: "Wichtig: Es stehen keine Bildinhalte zur Verfuegung,
        # nur der Text." Der Satz war ab Task 10 wahr und ist es nicht mehr --
        # die Bilder werden jetzt geprueft, nur eben nicht von DIESEM Modell.
        # Er richtete zusaetzlich Schaden an: bei QA/0011 begruendete das
        # Modell sein Urteil mit "keine Bilder verfuegbar, daher als
        # Totalschaden eingestuft" und rechnete das fehlende Bild als
        # erschwerenden Umstand.
        #
        # Der Bildbefund kommt hier bewusst NICHT hinein. Diese Bewertung
        # bleibt eine reine Textbewertung -- genau deshalb laesst sie sich
        # anschliessend gegen den Bildbefund pruefen. Ein Modell, das beide
        # Quellen saehe, koennte einen Widerspruch wegerklaeren.
        return "\n".join(lines)

    async def classify_disposition(
        self,
        *,
        description: str,
        priority: str = "0",
        photo_count: int = 0,
        product_id: int | None = None,
        location_id: int | None = None,
    ) -> LlmDispositionResult:
        payload = {
            "model": self._model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": self._build_user_prompt(
                        description=description,
                        priority=priority,
                        photo_count=photo_count,
                        product_id=product_id,
                        location_id=location_id,
                    ),
                },
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(f"{self._endpoint}/api/chat", json=payload)
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content")
            return self._parse(content)
        except Exception as exc:  # noqa: BLE001 - jeder Fehler => kein Urteil
            logger.warning(json.dumps({
                "event_type": "llm_quality_disposition_failed",
                "model": self._model,
                "error": str(exc),
            }))
            return LlmDispositionResult(ok=False, model=self._model)

    def _parse(self, content: str | None) -> LlmDispositionResult:
        if not content or not isinstance(content, str):
            return LlmDispositionResult(ok=False, model=self._model)
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            return LlmDispositionResult(ok=False, model=self._model)
        if not isinstance(parsed, dict):
            return LlmDispositionResult(ok=False, model=self._model)

        disposition = str(parsed.get("disposition", "")).strip().lower()
        if disposition not in VALID_DISPOSITIONS:
            return LlmDispositionResult(ok=False, model=self._model)

        try:
            confidence = float(parsed.get("confidence"))
        except (TypeError, ValueError):
            return LlmDispositionResult(ok=False, model=self._model)
        confidence = max(0.0, min(1.0, round(confidence, 2)))

        summary = str(parsed.get("summary", "")).strip()
        if not summary:
            summary = f"LLM-Einstufung: {disposition}."
        summary = summary[:200]

        return LlmDispositionResult(
            ok=True,
            model=self._model,
            disposition=disposition,
            confidence=confidence,
            summary=summary,
            recommended_action=RECOMMENDED_ACTIONS[disposition],
        )
