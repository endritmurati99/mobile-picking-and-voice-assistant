"""
Whisper STT Client.
Sendet WAV-Audio (16kHz, Mono) per REST an den Whisper-ASR-Webservice.
Audio wird vorher im Backend zu WAV konvertiert (Whisper-Container hat minimales ffmpeg).

Performance: Persistente HTTP-Verbindung (keep-alive) statt neuer Client pro Request.
"""
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = 60.0  # faster_whisper small ist schnell, aber längere Aufnahmen brauchen mehr Zeit

# Halluzinations-Schwelle: Segmente mit hoher no_speech_prob sind meist
# erfundener Text bei Stille/Rauschen (z. B. "Untertitelung des ZDF").
NO_SPEECH_MAX = 0.6

# Domänen-Prompt biast Whisper auf Lager-/Picking-Vokabular statt generischer
# deutscher Sätze und reduziert Fehlerkennungen bei kurzen Kommandos.
DOMAIN_PROMPT = (
    "Kommissionierung im Lager. Befehle: bestaetigen, weiter, naechste, "
    "auftrag fertig, problem, foto, was jetzt. Orte: Regal, Fach, Zone."
)

# Persistenter Client — eine TCP-Verbindung für alle Whisper-Requests.
# Spart ~50-150ms Connection-Setup pro Voice-Request.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=TIMEOUT,
            limits=httpx.Limits(
                max_keepalive_connections=2,
                max_connections=4,
                keepalive_expiry=30.0,
            ),
        )
    return _client


async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/wav") -> str:
    """
    Sendet Audio an Whisper-ASR-Webservice und gibt Transkript zurück.

    API: POST /asr?task=transcribe&language=de&output=json
    Body: multipart/form-data mit audio_file
    """
    ext = ".wav" if "wav" in mime_type else (".mp4" if "mp4" in mime_type else ".webm")
    filename = f"audio{ext}"

    logger.info(f"Whisper: {len(audio_bytes)} bytes, mime={mime_type}, file={filename}")

    try:
        client = _get_client()
        resp = await client.post(
            f"{settings.whisper_url}/asr",
            params={
                "task": "transcribe",
                "language": "de",
                "output": "json",
                "encode": "false",
                "initial_prompt": DOMAIN_PROMPT,
            },
            files={
                "audio_file": (filename, audio_bytes, mime_type or "audio/wav"),
            },
        )
        logger.info(f"Whisper Response: {resp.status_code} {resp.text[:200]}")
        resp.raise_for_status()
        data = resp.json()
        text = data.get("text", "").strip()
        segments = data.get("segments") or []
        if segments:
            worst = max(
                (s.get("no_speech_prob", 0.0) for s in segments),
                default=0.0,
            )
            if worst >= NO_SPEECH_MAX:
                logger.info(
                    "Whisper: dropped likely hallucination (no_speech_prob=%.2f)",
                    worst,
                )
                return ""
        return text
    except Exception as e:
        logger.error(f"Whisper STT Fehler: {type(e).__name__}: {e}")
        return ""
