"""
Minimaler HTTP-Wrapper fuer Piper TTS via Python-API.
POST /synthesize  { text: str }  → audio/wav
GET  /health                      → { status: ok }
"""
import asyncio
import io
import logging
import wave

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("piper-server")

MODEL_PATH = "/models/de.onnx"

app = FastAPI(title="Piper TTS")

# Singleton — Voice wird einmal geladen und gecacht
_voice = None


def _get_voice():
    global _voice
    if _voice is None:
        from piper.voice import PiperVoice
        logger.info("Lade Piper-Stimme: %s", MODEL_PATH)
        _voice = PiperVoice.load(MODEL_PATH)
        logger.info("Piper bereit. Samplerate: %d Hz", _voice.config.sample_rate)
    return _voice


def _synth_blocking(text: str) -> bytes:
    voice = _get_voice()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        # synthesize_wav setzt Format (channels/samplewidth/framerate) selbst
        voice.synthesize_wav(text, wf)
    return buf.getvalue()


@app.on_event("startup")
async def startup():
    # Modell beim Start vorwaermen — erste Anfrage dann ohne Verzoegerung
    await asyncio.to_thread(_get_voice)
    logger.info("Piper TTS Server bereit.")


class SynthRequest(BaseModel):
    text: str
    lang: str = "de-DE"


@app.post("/synthesize")
async def synthesize(body: SynthRequest):
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="Text darf nicht leer sein")
    try:
        wav = await asyncio.to_thread(_synth_blocking, body.text.strip())
        return Response(content=wav, media_type="audio/wav")
    except Exception as exc:
        logger.error("Synthese fehlgeschlagen: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
def health():
    return {"status": "ok"}
