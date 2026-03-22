"""
Voice-Intent-Engine.
Matcht Vosk-Transkripte auf Picking-Kommandos.
KEINE NLP-Library — nur Regex + deutsche Zahlwörter.
"""
import re
from dataclasses import dataclass
from enum import Enum


class PickingContext(Enum):
    IDLE = "idle"
    AWAITING_LOCATION_CHECK = "awaiting_location_check"
    AWAITING_QUANTITY_CONFIRM = "awaiting_quantity_confirm"
    AWAITING_COMMAND = "awaiting_command"


@dataclass
class Intent:
    action: str
    value: str | None
    confidence: float
    raw_text: str


PATTERNS = {
    "confirm": [r"\b(bestätigt|bestätige|bestätigen|ja|korrekt|stimmt|richtig|okay|ok)\b"],
    "next": [r"\b(nächster|nächste|weiter|skip|überspringen)\b"],
    "previous": [r"\b(zurück|vorheriger|vorherige)\b"],
    "problem": [r"\b(problem|fehler|defekt|beschädigt|kaputt|fehlt|mangel)\b"],
    "photo": [r"\b(foto|photo|bild|kamera|aufnahme)\b"],
    "repeat": [r"\b(wiederholen|nochmal|noch\s*mal|bitte\s*was|wie\s*bitte)\b"],
    "pause": [r"\b(pause|stopp|stop|halt|warten)\b"],
    "done": [r"\b(fertig|abgeschlossen|ende|beenden)\b"],
    "help": [r"\b(hilfe|help|was\s*kann\s*ich)\b"],
}

GERMAN_NUMBERS = {
    "null": "0", "eins": "1", "zwei": "2", "drei": "3", "vier": "4",
    "fünf": "5", "sechs": "6", "sieben": "7", "acht": "8", "neun": "9",
    "zehn": "10", "elf": "11", "zwölf": "12",
}


def recognize_intent(text: str, context: PickingContext) -> Intent:
    text_lower = text.strip().lower()
    if not text_lower:
        return Intent("unknown", None, 0.0, text)

    if context in (PickingContext.AWAITING_LOCATION_CHECK, PickingContext.AWAITING_QUANTITY_CONFIRM):
        number = _extract_number(text_lower)
        if number is not None:
            action = "check_digit" if context == PickingContext.AWAITING_LOCATION_CHECK else "quantity"
            return Intent(action, str(number), 0.95, text)

    for action, patterns in PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return Intent(action, None, 0.9, text)

    return Intent("unknown", None, 0.0, text)


def _extract_number(text: str) -> int | None:
    digits = re.findall(r"\d+", text)
    if digits:
        return int(digits[0])
    for word, digit in GERMAN_NUMBERS.items():
        if word in text:
            return int(digit)
    return None
