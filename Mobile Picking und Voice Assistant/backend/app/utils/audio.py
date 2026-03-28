"""
Audio-Format-Konvertierung.

iOS Safari: audio/mp4 (AAC)
Chrome Android: audio/webm;codecs=opus
Vosk akzeptiert beides, aber für Zuverlässigkeit wird zu WAV konvertiert.
"""
import asyncio
import subprocess
import tempfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _run_ffmpeg(audio_bytes: bytes, suffix: str) -> bytes:
    """
    Synchroner ffmpeg-Aufruf (läuft im Thread-Pool, blockiert nicht den Event-Loop).
    Gibt WAV-Bytes zurück, oder die Original-Bytes bei Fehler.
    """
    inp_path = ""
    out_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as inp:
            inp.write(audio_bytes)
            inp_path = inp.name

        out_path = inp_path + ".wav"

        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", inp_path,
                "-ar", "16000",     # 16kHz Sampling Rate
                "-ac", "1",         # Mono
                "-f", "wav",
                out_path,
            ],
            capture_output=True,
            timeout=10,
        )

        if result.returncode == 0:
            return Path(out_path).read_bytes()

        logger.warning("ffmpeg Fehler: %s", result.stderr.decode())
        return audio_bytes

    except Exception as exc:
        logger.error("Audio-Konvertierung fehlgeschlagen: %s", exc)
        return audio_bytes
    finally:
        for p in (inp_path, out_path):
            if p:
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass


async def convert_to_wav(audio_bytes: bytes, source_mime: str = "") -> bytes:
    """
    Konvertiert Audio-Blob zu WAV (16kHz, Mono) via ffmpeg.
    ffmpeg läuft im Thread-Pool damit der asyncio Event-Loop nicht blockiert wird.
    Gibt originale Bytes zurück, wenn Konvertierung fehlschlägt.
    """
    suffix = ".mp4" if "mp4" in source_mime else ".webm"
    return await asyncio.to_thread(_run_ffmpeg, audio_bytes, suffix)
