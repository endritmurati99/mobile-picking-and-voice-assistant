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
    "confirm": [
        r"\b(bestätigt|bestätige|bestätigen|ja|jap|jo|jep|jepp|jawohl)\b",
        r"\b(korrekt|stimmt|richtig|genau|passt|in\s*ordnung|alles\s*klar)\b",
        r"\b(okay|ok|okey|sicher|na\s*klar|logo|mach\s*ich|geht\s*klar)\b",
        r"\b(das\s*stimmt|ja\s*genau|ist\s*richtig|sieht\s*gut\s*aus)\b",
        r"\b(einverstanden|akzeptiert|angenommen|abgehakt|check)\b",
    ],
    "next": [
        r"\b(nächster|nächste|nächstes|weiter|weitermachen|skip|überspringen)\b",
        r"\b(weiter\s*so|nächste\s*zeile|nächste\s*position|gib\s*mir.*nächst)\b",
        r"\b(und\s*weiter|komm\s*weiter|mach\s*weiter|los\s*weiter)\b",
    ],
    "previous": [
        r"\b(zurück|vorheriger|vorherige|vorheriges|davor|eins\s*zurück)\b",
        r"\b(nochmal\s*zurück|geh\s*zurück|schritt\s*zurück)\b",
    ],
    "problem": [
        r"\b(problem|fehler|defekt|beschädigt|kaputt|fehlt|mangel)\b",
        r"\b(falsch|stimmt\s*nicht|nicht\s*richtig|verkehrt|passt\s*nicht)\b",
        r"\b(beschädigung|schaden|bruch|riss|leck|verdorben)\b",
        r"\b(falsche\s*menge|falsches\s*produkt|falscher\s*artikel)\b",
        r"\b(reklamation|beanstandung|abweichung|differenz)\b",
    ],
    "photo": [
        r"\b(foto|photo|bild|kamera|aufnahme|knipsen|fotografieren)\b",
        r"\b(mach.*foto|mach.*bild|aufnehmen|scannen|scan)\b",
    ],
    "repeat": [
        r"\b(wiederholen|nochmal|noch\s*mal|nochmals|bitte\s*was)\b",
        r"\b(wie\s*bitte|was\s*hast\s*du\s*gesagt|sag\s*nochmal)\b",
        r"\b(verstehe\s*nicht|nicht\s*verstanden|hä|häh)\b",
        r"\b(kannst\s*du.*wiederholen|sag.*noch\s*mal)\b",
        r"^was\??$",
    ],
    "pause": [
        r"\b(pause|stopp|stop|halt|warten|moment|moment\s*mal)\b",
        r"\b(kurz\s*warten|warte\s*mal|warte\s*kurz|sekunde|ruhe)\b",
        r"\b(mikrofon\s*aus|mikro\s*aus|mic\s*aus|stille|leise)\b",
    ],
    "done": [
        r"\b(fertig|erledigt|abgeschlossen|ende|beenden|komplett)\b",
        r"\b(bin\s*fertig|alles\s*fertig|alles\s*erledigt|geschafft)\b",
        r"\b(abschließen|beende|schluss|feierabend|das\s*war's)\b",
    ],
    "help": [
        r"\b(hilfe|help|was\s*kann\s*ich|befehle|kommandos)\b",
        r"\b(was\s*geht|was\s*gibt.*optionen|wie\s*funktioniert)\b",
    ],
    "stock_query": [
        r"\b(noch\s+da|im\s+bestand|lagerbestand|wie\s+viel.*vorrat)\b",
        r"\b(bestand\s*prüfen|bestand\s*checken|vorrätig|verfügbar)\b",
        r"\b(wie\s*viel\s*haben\s*wir|ist\s*noch\s*was\s*da|auf\s*lager)\b",
        r"\b(menge\s*prüfen|stückzahl|restbestand|restmenge)\b",
    ],
    # Filter-Intents (Picking-Liste)
    "filter_high": [
        r"\b(dringend\w*|dringlich\w*|wichtig\w*|hohe?\s*priorität|eilig\w*)\b",
        r"\b(priorisiert\w*|kritisch\w*|prio|nur\s*dringend\w*|nur\s*eilig\w*)\b",
        r"\b(zeig.*dringend\w*|zeig.*eilig\w*|express|eilt)\b",
    ],
    "filter_normal": [
        r"\b(alle|alles|normal|zurücksetzen|filter\s*weg|reset)\b",
        r"\b(zeig.*alle|alle\s*anzeigen|filter\s*aus|ohne\s*filter)\b",
        r"\b(komplett\s*liste|ganze\s*liste|alles\s*zeigen)\b",
    ],
    "status": [
        r"\b(wie\s*viele|status|übersicht|wieviele|anzahl)\b",
        r"\b(offen|aufträge|was\s*steht\s*an|was\s*gibt\s*es)\b",
        r"\b(was\s*ist\s*offen|zusammenfassung|überblick|stand)\b",
    ],
}

GERMAN_NUMBERS = {
    "null": "0", "eins": "1", "zwei": "2", "drei": "3", "vier": "4",
    "fünf": "5", "sechs": "6", "sieben": "7", "acht": "8", "neun": "9",
    "zehn": "10", "elf": "11", "zwölf": "12",
}


_NEGATION = re.compile(r"\b(nicht|kein\w*|nein|falsch\w*|nie)\b")

# Wörter die mit Negation zu "problem" werden statt "confirm"
_CONFIRM_NEGATABLE = re.compile(r"\b(stimmt|richtig|passt)\b")

# Reihenfolge: problem vor confirm, damit Negation gewinnt
_PRIORITY_ORDER = [
    "problem", "confirm", "next", "previous", "photo", "done",
    "pause", "stock_query", "filter_high", "filter_normal",
    "status", "repeat", "help",
]


def recognize_intent(text: str, context: PickingContext) -> Intent:
    text_lower = text.strip().lower()
    if not text_lower:
        return Intent("unknown", None, 0.0, text)

    if context in (PickingContext.AWAITING_LOCATION_CHECK, PickingContext.AWAITING_QUANTITY_CONFIRM):
        number = _extract_number(text_lower)
        if number is not None:
            action = "check_digit" if context == PickingContext.AWAITING_LOCATION_CHECK else "quantity"
            return Intent(action, str(number), 0.95, text)

    has_negation = bool(_NEGATION.search(text_lower))

    # "stimmt nicht" / "passt nicht" → problem (nicht confirm)
    if has_negation and _CONFIRM_NEGATABLE.search(text_lower):
        return Intent("problem", None, 0.9, text)

    for action in _PRIORITY_ORDER:
        patterns = PATTERNS[action]
        for pattern in patterns:
            if re.search(pattern, text_lower):
                # "nicht richtig" soll nicht als confirm matchen
                if action == "confirm" and has_negation:
                    continue
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
