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


async def transcribe_audio(audio_bytes: bytes) -> str:
    """
    Sendet Audio an Vosk-Server und gibt Transkript zurück.
    
    Audio-Formate: WAV, WebM/Opus, MP4/AAC
    Vosk akzeptiert alle; bei Problemen ffmpeg-Konvertierung nutzen.
    """
    try:
        async with websockets.connect(settings.vosk_url) as ws:
            await ws.send(audio_bytes)
            await ws.send('{"eof" : 1}')
            
            result_text = ""
            async for msg in ws:
                data = json.loads(msg)
                if "text" in data and data["text"]:
                    result_text = data["text"]
            
            return result_text.strip()
    except Exception as e:
        logger.error(f"Vosk STT Fehler: {e}")
        return ""
