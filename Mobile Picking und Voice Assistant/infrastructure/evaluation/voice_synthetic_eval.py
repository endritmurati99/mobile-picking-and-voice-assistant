"""Reproducible synthetic Piper -> Whisper -> deterministic-intent evaluation.

Runs inside the live backend container because its internal Docker network exposes
the existing ``piper`` and ``whisper`` services.  It never calls a booking or
confirmation route and writes only sanitized JSON to stdout.
"""
import asyncio
import json
import statistics
import sys
import time
import wave
from io import BytesIO

import httpx

from app.services.intent_engine import PickingContext, recognize_intent

CASES = (
    ("weiter", "next"),
    ("bestätigen", "confirm"),
    ("Problem", "problem"),
    ("Auftrag fertig", "confirm_all"),
    ("was kommt als nächstes", "next"),
)
REPETITIONS = 3
PIPER_URL = "http://piper:5500/synthesize"
WHISPER_URL = "http://whisper:9000/asr?task=transcribe&language=de&output=json"
DOMAIN_PROMPT = (
    "Kommissionierung Lager. Befehle: bestaetigen, weiter, naechste, "
    "auftrag fertig, problem, foto, was jetzt. Orte: Regal, Fach, Zone."
)


def milliseconds(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def wav_duration_ms(audio: bytes) -> float:
    with wave.open(BytesIO(audio)) as wav:
        return round(wav.getnframes() / wav.getframerate() * 1000, 2)


async def run_case(client: httpx.AsyncClient, command: str, expected: str, repetition: int) -> dict:
    result = {"command": command, "expected_intent": expected, "repetition": repetition}
    try:
        started = time.perf_counter()
        tts = await client.post(PIPER_URL, json={"text": command, "lang": "de-DE"})
        result["tts_ms"] = milliseconds(started)
        result["tts_http_status"] = tts.status_code
        tts.raise_for_status()
        audio = tts.content
        result["audio_duration_ms"] = wav_duration_ms(audio)

        started = time.perf_counter()
        stt = await client.post(
            WHISPER_URL,
            data={"initial_prompt": DOMAIN_PROMPT},
            files={"audio_file": ("synthetic.wav", audio, "audio/wav")},
        )
        result["stt_ms"] = milliseconds(started)
        result["stt_http_status"] = stt.status_code
        stt.raise_for_status()
        transcript = str(stt.json().get("text", "")).strip()
        result["transcript"] = transcript

        started = time.perf_counter()
        intent = recognize_intent(transcript, PickingContext.AWAITING_COMMAND)
        result["intent_ms"] = milliseconds(started)
        result["intent"] = intent.action
        result["intent_confidence"] = intent.confidence
        result["intent_strategy"] = intent.match_strategy
        result["success"] = intent.action == expected
    except Exception as exc:  # preserve failure evidence without endpoint/auth details
        result["success"] = False
        result["error_type"] = type(exc).__name__
    return result


def median(rows: list[dict], field: str) -> float | None:
    values = [row[field] for row in rows if field in row]
    return round(statistics.median(values), 2) if values else None


async def main() -> None:
    results: list[dict] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for command, expected in CASES:
            for repetition in range(1, REPETITIONS + 1):
                results.append(await run_case(client, command, expected, repetition))
    successful = sum(row["success"] for row in results)
    print(json.dumps({
        "method": "synthetic_piper_whisper_deterministic_intent",
        "boundary": {
            "audio_source": "Piper-generated German WAV only; no microphone or user recording",
            "execution_path": "direct internal Piper/Whisper clients, then recognize_intent",
            "bypassed": ["FastAPI voice route", "upload conversion/ffmpeg", "PWA/browser", "auth", "booking and confirmation endpoints"],
        },
        "cases_declared_before_execution": [
            {"command": command, "expected_intent": expected} for command, expected in CASES
        ],
        "repetitions_per_case": REPETITIONS,
        "sample_count": len(results),
        "successful_label_matches": successful,
        "timing_median_ms": {field: median(results, field) for field in ("tts_ms", "stt_ms", "intent_ms")},
        "results": results,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
