"""
Vosk STT Client.
Wird in Phase 4 implementiert.
Nutzt WebSocket-Verbindung zum Vosk-Docker-Container.
"""
import json
import logging
import websockets
from app.config import settings

logger = logging.getLogger(__name__)


CHUNK_SIZE = 4000  # Bytes pro Chunk — Vosk verarbeitet Audio in kleinen Stücken


async def transcribe_audio(audio_bytes: bytes) -> str:
    """
    Sendet WAV-Audio (16kHz, Mono) an Vosk-Server und gibt Transkript zurück.

    Vosk WebSocket-Protokoll:
    1. Config-Message mit sample_rate senden
    2. Audio in Chunks senden
    3. EOF senden
    4. Ergebnisse lesen bis Connection geschlossen
    """
    try:
        async with websockets.connect(settings.vosk_url) as ws:
            # 1. Vosk braucht zuerst die Sample-Rate
            await ws.send(json.dumps({"config": {"sample_rate": 16000}}))

            # 2. Audio in Chunks senden (nicht als einzelnen Blob)
            for i in range(0, len(audio_bytes), CHUNK_SIZE):
                await ws.send(audio_bytes[i:i + CHUNK_SIZE])

            # 3. EOF signalisieren
            await ws.send('{"eof" : 1}')

            # 4. Ergebnisse sammeln (partial + final)
            result_text = ""
            async for msg in ws:
                data = json.loads(msg)
                if "text" in data and data["text"]:
                    result_text = data["text"]

            return result_text.strip()
    except Exception as e:
        logger.error(f"Vosk STT Fehler: {e}")
        return ""
