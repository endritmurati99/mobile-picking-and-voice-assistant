"""
Voice endpoints: server-side Whisper STT, deterministic intent parsing, Piper TTS.
"""
import logging
import time
from uuid import uuid4
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.dependencies import get_odoo_client, get_picking_service, get_request_odoo_client_or_grace, get_write_request_context
from app.models.n8n import VoiceAssistRequest, VoiceAssistResponse
from app.models.voice import TTSRequest
from app.services.obsidian_context import format_obsidian_hits, search_obsidian_notes
from app.services import piper_client, whisper_client
from app.services.intent_engine import (
    FUZZY_PHRASE_THRESHOLD,
    FUZZY_SINGLE_THRESHOLD,
    PickingContext,
    VoiceSurface,
    finalize_external_intent,
    recognize_intent,
    recognize_intent_from_segments,
)
from app.services.voice_intent_classifier import get_classifier
from app.services.mobile_workflow import WriteRequestContext
from app.services.n8n_webhook import N8NReply
from app.services.odoo_client import OdooClient
from app.services.picking_service import PickingService
from app.utils.audio import convert_to_wav

logger = logging.getLogger(__name__)
router = APIRouter()

_LOCAL_ONLY_ASSIST_INTENTS = {"confirm", "confirm_all", "next", "previous", "done", "pause", "photo"}
_SHORTAGE_TERMS = ("fehlt", "fehlmenge", "mangel", "restbestand", "nachschub", "leer")


def _find_line_context(picking: dict, move_line_id: int | None, product_id: int | None) -> dict | None:
    lines = picking.get("move_lines") or []
    if move_line_id is not None:
        for line in lines:
            if line.get("id") == move_line_id:
                return line
    if product_id is not None:
        for line in lines:
            if line.get("product_id") == product_id:
                return line
    return lines[0] if lines else None


def _fallback_tts(intent: str) -> str:
    if intent == "stock_query":
        return "Ich kann den Bestand gerade nicht sicher pruefen."
    if intent == "problem":
        return "Ich kann das Problem gerade nicht sicher einordnen."
    return "Ich kann das gerade nicht sicher beantworten."


def _requires_problem_assist(text: str) -> bool:
    normalized = (text or "").lower()
    return any(term in normalized for term in _SHORTAGE_TERMS)


async def _load_stock_context(
    odoo: OdooClient,
    *,
    product_id: int | None,
    location_id: int | None,
) -> dict[str, Any]:
    if product_id is None:
        return {
            "stock_summary_text": "",
            "alternative_locations": [],
            "recommendation": None,
        }

    quants = await odoo.search_read(
        "stock.quant",
        [("product_id", "=", product_id)],
        ["quantity", "reserved_quantity", "location_id"],
        limit=50,
    )
    available_rows = []
    current_available = 0.0
    current_location_name = ""
    for quant in quants:
        available = float(quant.get("quantity", 0) or 0) - float(quant.get("reserved_quantity", 0) or 0)
        location_value = quant.get("location_id")
        location_tuple = location_value if isinstance(location_value, list) else location_value or []
        loc_id = location_tuple[0] if location_tuple else None
        loc_name = location_tuple[1] if location_tuple else ""
        if loc_id == location_id:
            current_available += available
            current_location_name = loc_name or current_location_name
        if available > 0 and loc_id and loc_id != location_id:
            available_rows.append(
                {
                    "id": loc_id,
                    "name": loc_name,
                    "quantity_available": round(available, 2),
                }
            )

    available_rows.sort(key=lambda item: (-item["quantity_available"], item["name"]))
    alternative_locations = available_rows[:3]

    if location_id and current_location_name:
        if current_available > 0:
            summary_text = (
                f"Am aktuellen Lagerplatz {current_location_name} sind noch "
                f"{round(current_available, 2)} Stueck verfuegbar."
            )
        elif alternative_locations:
            alt_text = ", ".join(
                f"{item['name']} ({item['quantity_available']} Stueck)"
                for item in alternative_locations
            )
            summary_text = (
                f"Am aktuellen Lagerplatz {current_location_name} ist kein verfuegbarer Bestand mehr. "
                f"Alternativen: {alt_text}."
            )
        else:
            summary_text = f"Am aktuellen Lagerplatz {current_location_name} ist kein verfuegbarer Bestand mehr."
    else:
        total_available = round(sum(item["quantity_available"] for item in alternative_locations), 2)
        summary_text = (
            f"Es sind noch {total_available} Stueck an alternativen Lagerplaetzen verfuegbar."
            if alternative_locations
            else "Es wurde kein verfuegbarer Bestand gefunden."
        )

    recommendation = None
    if location_id and current_available <= 0 and alternative_locations:
        recommendation = {
            "action": "trigger_replenishment",
            "location_id": location_id,
            "recommended_location_id": alternative_locations[0]["id"],
            "recommended_location": alternative_locations[0]["name"],
            "reason": "Am Zielplatz ist kein verfuegbarer Bestand vorhanden, aber an einem Alternativplatz liegt Ware.",
            "quantity": 1.0,
        }

    return {
        "stock_summary_text": summary_text,
        "alternative_locations": alternative_locations,
        "recommendation": recommendation,
    }


def _build_obsidian_terms(body: VoiceAssistRequest, picking_detail: dict, line_context: dict | None) -> list[str]:
    terms = [body.text]
    for candidate in (
        picking_detail.get("kit_name"),
        picking_detail.get("origin"),
        picking_detail.get("reference_code"),
        (line_context or {}).get("ui_display"),
    ):
        if candidate:
            terms.append(str(candidate))
    return terms


def _build_local_assist_answer(
    *,
    body: VoiceAssistRequest,
    picking_detail: dict,
    line_context: dict | None,
    stock_context: dict[str, Any],
    obsidian_hits: list[dict],
) -> tuple[str, dict[str, Any] | None]:
    kit_name = picking_detail.get("kit_name") or "gerade einen Auftrag"
    line_name = (line_context or {}).get("ui_display") or "dem aktuellen Artikel"
    voice_intro = picking_detail.get("voice_intro") or ""
    obsidian_text = format_obsidian_hits(obsidian_hits, max_chars=220)
    recommendation = stock_context.get("recommendation")

    if body.intent == "stock_query":
        return stock_context.get("stock_summary_text") or f"Ich habe keinen belastbaren Bestand fuer {line_name} gefunden.", recommendation

    if body.intent == "problem" and recommendation:
        # Sagt, was IST, nicht was jemand tut: den Nachschub stoesst seit dem
        # Wegfall des v1-Workflows niemand automatisch an, und eine Ansage
        # "ich leite ein" waere damit eine Behauptung ohne Deckung.
        text = (
            f"Fuer {line_name} ist am aktuellen Platz kein verfuegbarer Bestand mehr vorhanden. "
            f"Ware liegt in {recommendation.get('recommended_location', 'einem Alternativplatz')}."
        )
        return text, recommendation

    if obsidian_text:
        return (
            f"Du baust {kit_name}. Aktuell geht es um {line_name}. "
            f"Ich habe passende Notizen gefunden: {obsidian_text}",
            recommendation,
        )

    if voice_intro:
        return (
            f"Du baust {kit_name}. {voice_intro}",
            recommendation,
        )

    return (
        f"Du baust {kit_name}. Aktuell geht es um {line_name}.",
        recommendation,
    )


@router.post("/voice/recognize")
async def recognize_speech(
    audio: UploadFile = File(...),
    context: str = Form(default="awaiting_command"),
    surface: str = Form(default="detail"),
    remaining_line_count: int = Form(default=1),
    active_line_present: bool = Form(default=True),
):
    """
    Receive an audio blob, transcribe it through Whisper, then resolve intent.

    The response stays backward-compatible and adds normalized_text plus the
    matching strategy used by the resolver.
    """
    started_at = time.monotonic()

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Leere Audio-Datei")

    audio_size = len(audio_bytes)

    convert_started_at = time.monotonic()
    audio_bytes = await convert_to_wav(audio_bytes, audio.content_type or "")
    convert_ms = round((time.monotonic() - convert_started_at) * 1000)

    stt_started_at = time.monotonic()
    text = await whisper_client.transcribe_audio(audio_bytes, "audio/wav")
    stt_ms = round((time.monotonic() - stt_started_at) * 1000)
    total_ms = round((time.monotonic() - started_at) * 1000)

    logger.info(
        "Voice latency: audio=%dB convert=%dms stt=%dms total=%dms",
        audio_size,
        convert_ms,
        stt_ms,
        total_ms,
    )

    if not text:
        return {
            "text": "",
            "intent": "unknown",
            "value": None,
            "confidence": 0.0,
            "normalized_text": "",
            "match_strategy": "unknown",
            "_timing": {
                "audio_bytes": audio_size,
                "convert_ms": convert_ms,
                "stt_ms": stt_ms,
                "total_ms": total_ms,
            },
        }

    try:
        picking_context = PickingContext(context)
    except ValueError:
        picking_context = PickingContext.AWAITING_COMMAND

    try:
        ui_surface = VoiceSurface(surface)
    except ValueError:
        ui_surface = VoiceSurface.DETAIL

    intent = recognize_intent(
        text,
        picking_context,
        surface=ui_surface,
        remaining_line_count=remaining_line_count,
        active_line_present=active_line_present,
    )

    # Segment-fallback: try partial-ratio substring search when primary match
    # is uncertain. Only runs when needed — avoids extra work on clear matches.
    if intent.action == "unknown" or intent.confidence < FUZZY_SINGLE_THRESHOLD:
        seg = recognize_intent_from_segments(
            text,
            surface=ui_surface,
            remaining_line_count=remaining_line_count,
            active_line_present=active_line_present,
        )
        if seg.confidence > intent.confidence:
            intent = seg

    # LLM fallback: only when the deterministic engine is still unsure. The LLM
    # label is run through the same guards (negation, surface gating, write
    # confidence clamp) as a deterministic match. Any failure keeps the
    # deterministic result, so a slow/absent model never breaks voice.
    if intent.action == "unknown" or intent.confidence < FUZZY_SINGLE_THRESHOLD:
        llm = await get_classifier().classify(text)
        if llm.ok and llm.intent is not None:
            candidate = finalize_external_intent(
                llm.intent,
                llm.confidence or 0.0,
                raw_text=text,
                normalized_text=intent.normalized_text or text,
                surface=ui_surface,
                remaining_line_count=remaining_line_count,
                active_line_present=active_line_present,
            )
            if candidate.action != "unknown" and candidate.confidence > intent.confidence:
                intent = candidate

    # Recovery-dialog: backend signals PWA to ask user for confirmation when
    # confidence is in the fuzzy range [FUZZY_PHRASE_THRESHOLD, FUZZY_SINGLE_THRESHOLD).
    # Vollstaendige Aktions-Vokabular: PRIORITY_ORDER + abort/check_digit/quantity
    # aus services/intent_engine.py (nur gelesen, dort nicht veraendert). Ohne
    # Eintrag faellt Zeile ~334 auf den rohen englischen Bezeichner zurueck --
    # das soll praktisch nie mehr passieren.
    _ACTION_DE = {
        "problem": "Problem melden",
        "confirm_all": "alles bestätigen",
        "confirm": "bestätigen",
        "submit_alert": "Qualitätsmeldung absenden",
        "next_order": "nächster Auftrag",
        "next": "weiter",
        "previous": "zurück",
        "photo": "Foto aufnehmen",
        "done": "fertig",
        "pause": "pausieren",
        "stock_query": "Bestand abfragen",
        "filter_high": "nach hoher Dringlichkeit filtern",
        "filter_normal": "nach normaler Dringlichkeit filtern",
        "how_many_left": "wie viele noch offen sind",
        "whats_next": "was als Nächstes ansteht",
        "where": "wo die Position ist",
        "status": "Status abfragen",
        "repeat": "wiederholen",
        "help": "Hilfe anzeigen",
        "abort": "abbrechen",
        "check_digit": "Prüfziffer bestätigen",
        "quantity": "Menge bestätigen",
    }
    requires_confirmation = (
        intent.action != "unknown"
        and FUZZY_PHRASE_THRESHOLD <= intent.confidence < FUZZY_SINGLE_THRESHOLD
    )
    confirmation_prompt = (
        f"Ich habe \u201e{_ACTION_DE.get(intent.action, intent.action)}\u201c verstanden. Richtig?"
        if requires_confirmation
        else None
    )

    logger.info(
        "STT: '%s' -> intent=%s strategy=%s conf=%.2f surface=%s remaining=%s active_line=%s [%dms]",
        text,
        intent.action,
        intent.match_strategy,
        intent.confidence,
        ui_surface.value,
        remaining_line_count,
        active_line_present,
        total_ms,
    )

    return {
        "text": intent.raw_text,
        "intent": intent.action,
        "value": intent.value,
        "confidence": intent.confidence,
        "normalized_text": intent.normalized_text,
        "match_strategy": intent.match_strategy,
        "requires_confirmation": requires_confirmation,
        "confirmation_prompt": confirmation_prompt,
        "_timing": {
            "audio_bytes": audio_size,
            "convert_ms": convert_ms,
            "stt_ms": stt_ms,
            "total_ms": total_ms,
        },
    }


@router.post("/voice/assist", response_model=VoiceAssistResponse)
async def assist_voice(
    body: VoiceAssistRequest,
    service: PickingService = Depends(get_picking_service),
    odoo: OdooClient = Depends(get_request_odoo_client_or_grace),
    context: WriteRequestContext = Depends(get_write_request_context),
):
    started_at = time.monotonic()

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Text fuer Assistenz fehlt.")

    if body.intent in _LOCAL_ONLY_ASSIST_INTENTS:
        return VoiceAssistResponse(
            status="not_applicable",
            tts_text="Dieses Kommando wird direkt im schnellen Picking-Pfad verarbeitet.",
            source="fastapi",
            correlation_id="local-intent",
            latency_ms=0,
            fallback_reason="local_intent",
        )

    if body.intent == "problem" and not _requires_problem_assist(body.text):
        return VoiceAssistResponse(
            status="not_applicable",
            tts_text="Bitte melde das Problem direkt als Qualitaetsalarm.",
            source="fastapi",
            correlation_id="quality-alert",
            latency_ms=0,
            fallback_reason="local_quality_alert",
        )

    picking_detail: dict = {}
    if body.picking_id is not None:
        picking_detail = await service.get_picking_detail(body.picking_id)
        if picking_detail.get("error"):
            picking_detail = {}

    line_context = _find_line_context(picking_detail, body.move_line_id, body.product_id) if picking_detail else None
    stock_context = await _load_stock_context(
        odoo,
        product_id=body.product_id or (line_context or {}).get("product_id"),
        location_id=body.location_id or (line_context or {}).get("location_src_id"),
    )
    obsidian_hits = search_obsidian_notes(
        _build_obsidian_terms(body, picking_detail, line_context),
        limit=3,
    )
    picking_context = {
        "picking_id": body.picking_id,
        "move_line_id": body.move_line_id or (line_context or {}).get("id"),
        "product_id": body.product_id or (line_context or {}).get("product_id"),
        "location_id": body.location_id or (line_context or {}).get("location_src_id"),
        "priority": picking_detail.get("priority"),
        "origin": picking_detail.get("origin"),
    }
    # Die Antwort entsteht lokal, nicht in n8n.
    #
    # Frueher fragte diese Route synchron den v1-Workflow `voice-exception-query`
    # und fiel nach `N8N_SYNC_TIMEOUT_MS` (7 s) auf genau diese lokale Antwort
    # zurueck. Seit der Workflow weg ist, war dieser Timeout der Regelfall: jede
    # Sprachanfrage wartete sieben Sekunden auf eine Antwort, die nie kam, und
    # meldete sich danach als `fallback` -- was die PWA als Warnung anzeigt.
    # Die lokale Antwort IST jetzt das Produkt, also traegt sie auch `ok`.
    local_started_at = time.monotonic()
    local_tts_text, recommendation = _build_local_assist_answer(
        body=body,
        picking_detail=picking_detail,
        line_context=line_context,
        stock_context=stock_context,
        obsidian_hits=obsidian_hits,
    )
    reply = N8NReply(
        status="ok",
        tts_text=local_tts_text or _fallback_tts(body.intent),
        source="fastapi-local-context",
        correlation_id=str(uuid4()),
        latency_ms=round((time.monotonic() - local_started_at) * 1000),
        recommendation=recommendation,
    )

    # Kein automatischer Nachschub-Anstoss mehr.
    #
    # Hier feuerte der v1-Workflow `shortage-reported`, den es nicht mehr gibt.
    # Die Empfehlung selbst bleibt in der Antwort und damit sichtbar -- nur
    # ausgeloest wird nichts, und der Text unten behauptet es auch nicht mehr.
    logger.info(
        "Voice assist: intent=%s picking=%s source=%s status=%s latency=%dms end_to_end=%dms",
        body.intent,
        body.picking_id,
        reply.source,
        reply.status,
        reply.latency_ms,
        round((time.monotonic() - started_at) * 1000),
    )
    return VoiceAssistResponse(**reply.asdict())


@router.post("/voice/tts")
async def synthesize_speech(body: TTSRequest):
    """
    Synthesisiert Text via lokalem Piper-TTS-Service zu WAV-Audio.
    Gibt 503 zurueck wenn Piper nicht erreichbar — die PWA faellt dann
    automatisch auf Browser-TTS zurueck.
    """
    audio = await piper_client.synthesize(body.text, body.lang)
    if audio is None:
        raise HTTPException(status_code=503, detail="TTS-Service nicht erreichbar")
    return Response(content=audio, media_type="audio/wav")
