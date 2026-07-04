"""
Piper TTS Client.
Sendet Text an den lokalen Piper-Container und gibt WAV-Audio zurueck.

Analoges Muster zu whisper_client.py: persistenter httpx-Client.
Bei Fehler oder Timeout wird None zurueckgegeben — die aufrufende Schicht
faellt dann auf Browser-TTS zurueck.
"""
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = 5.0  # TTS soll schnell sein; bei > 5s lieber Fallback

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


async def synthesize(text: str, lang: str = "de-DE") -> bytes | None:
    """
    Synthesisiert Text zu WAV-Audio via lokalem Piper-Service.

    Gibt WAV-Bytes zurueck oder None wenn Piper nicht erreichbar ist.
    """
    if not text or not text.strip():
        return None

    try:
        client = _get_client()
        resp = await client.post(
            f"{settings.piper_url}/synthesize",
            json={"text": text.strip(), "lang": lang},
        )
        resp.raise_for_status()
        return resp.content
    except httpx.TimeoutException:
        logger.warning("Piper TTS Timeout — Browser-TTS-Fallback aktiv")
        return None
    except Exception as exc:
        logger.debug("Piper TTS nicht erreichbar: %s: %s", type(exc).__name__, exc)
        return None
