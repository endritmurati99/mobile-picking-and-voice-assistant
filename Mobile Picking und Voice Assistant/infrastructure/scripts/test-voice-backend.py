"""Small regression checks for the WAV contract at the ffmpeg boundary."""
from __future__ import annotations

import importlib.util
import io
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
SPEC = importlib.util.spec_from_file_location("voice_audio", ROOT / "backend/app/utils/audio.py")
assert SPEC and SPEC.loader
audio = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audio
SPEC.loader.exec_module(audio)


wav = io.BytesIO()
with wave.open(wav, "wb") as output:
    output.setnchannels(1)
    output.setsampwidth(2)
    output.setframerate(16_000)
    output.writeframes(b"\0\0" * 160)
valid_wav = wav.getvalue()

if shutil.which("ffmpeg"):
    converted = audio._run_ffmpeg(valid_wav, ".webm")
    with wave.open(io.BytesIO(converted)) as output:
        assert output.getnchannels() == 1
        assert output.getframerate() == 16_000


with patch.object(audio.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, b"", b"bad input")):
    try:
        audio._run_ffmpeg(b"not-wav", ".webm")
    except audio.AudioConversionError:
        pass
    else:
        raise AssertionError("failed ffmpeg conversion must not return compressed bytes as WAV")


try:
    import asyncio
    import httpx
    from fastapi import FastAPI
except ModuleNotFoundError:
    print("route checks skipped (FastAPI/httpx unavailable)")
else:
    from app.routers import voice

    if not shutil.which("ffmpeg"):
        print("route checks skipped (ffmpeg unavailable)")
    else:
        async def route_checks() -> None:
            app = FastAPI()
            app.include_router(voice.router)
            transport = httpx.ASGITransport(app=app)
            original_transcribe = voice.whisper_client.transcribe_audio
            try:
                async def should_not_transcribe(*_args: object) -> str:
                    raise AssertionError("invalid audio reached Whisper")

                voice.whisper_client.transcribe_audio = should_not_transcribe
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/voice/recognize",
                        data={"context": "awaiting_command"},
                        files={"audio": ("bad.webm", b"not audio", "audio/webm")},
                    )
                    assert response.status_code == 422, response.text

                    async def unavailable_whisper(*_args: object) -> str:
                        raise voice.whisper_client.WhisperTranscriptionError("down")

                    voice.whisper_client.transcribe_audio = unavailable_whisper
                    response = await client.post(
                        "/voice/recognize",
                        data={"context": "awaiting_command"},
                        files={"audio": ("valid.wav", valid_wav, "audio/wav")},
                    )
                    assert response.status_code == 503, response.text
            finally:
                voice.whisper_client.transcribe_audio = original_transcribe

        asyncio.run(route_checks())

print("voice backend checks passed")
