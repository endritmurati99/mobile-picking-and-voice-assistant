"""
Voice intent engine for deterministic, context-aware command matching.

STT stays server-side via Whisper. This module only maps recognized text
to safe application intents.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


class PickingContext(Enum):
    IDLE = "idle"
    AWAITING_LOCATION_CHECK = "awaiting_location_check"
    AWAITING_QUANTITY_CONFIRM = "awaiting_quantity_confirm"
    AWAITING_COMMAND = "awaiting_command"


class VoiceSurface(Enum):
    LIST = "list"
    DETAIL = "detail"
    QUALITY_ALERT = "quality_alert"
    COMPLETE = "complete"


@dataclass(frozen=True)
class Intent:
    action: str
    value: str | None
    confidence: float
    raw_text: str
    normalized_text: str
    match_strategy: str = "unknown"


EXACT_MATCH_CONFIDENCE = 0.95
FUZZY_SINGLE_THRESHOLD = 0.73
FUZZY_PHRASE_THRESHOLD = 0.68

GERMAN_NUMBERS = {
    "null": "0",
    "eins": "1",
    "zwei": "2",
    "drei": "3",
    "vier": "4",
    "funf": "5",
    "sechs": "6",
    "sieben": "7",
    "acht": "8",
    "neun": "9",
    "zehn": "10",
    "elf": "11",
    "zwolf": "12",
}

NEGATION_TERMS = ("nicht", "kein", "keine", "keinen", "falsch", "nein", "nie")

PRIORITY_ORDER = (
    "problem",
    "confirm_all",
    "confirm",
    "next_order",
    "next",
    "previous",
    "photo",
    "done",
    "pause",
    "stock_query",
    "filter_high",
    "filter_normal",
    "status",
    "repeat",
    "help",
)

ALIASES = {
    "confirm_all": (
        "alles bestaetigen",
        "alle bestaetigen",
        "komplett bestaetigen",
        "alle positionen bestaetigen",
        "auftrag komplett",
        "auftrag abschliessen",
        "alles erledigt",
        "alle erledigt",
        "alle durch",
        "alles durch",
        "komplett",
        "alle auf einmal",
        "alles auf einmal",
        "bestaetige alles",
        "bestaetige alle",
        "bestaetige den auftrag",
        "auftrag fertig",
        "auftrag erledigt",
        "auftrag abschliessen",
    ),
    "confirm": (
        "bestaetigen",
        "bestaetige",
        "bestaetigt",
        "ja",
        "ok",
        "okay",
        "check",
        # natural affirmations
        "jep",
        "jup",
        "jo",
        "joa",
        "jupp",
        "klar",
        "gut",
        "passt",
        "stimmt",
        "richtig",
        "genau",
        "jawohl",
        "sicher",
        "alles klar",
        "geht klar",
        "in ordnung",
        "perfekt",
        "super",
        "alles gut",
        "paket erledigt",
        "paket fertig",
        "karton erledigt",
        "karton fertig",
        "position erledigt",
        "position fertig",
        "artikel erledigt",
        "artikel fertig",
    ),
    "next_order": (
        "naechster auftrag",
        "naechsten auftrag",
        "naechste auftrag",
        "zum naechsten auftrag",
        "weiter zum naechsten auftrag",
        "gib mir den naechsten auftrag",
        "naechster auftrag bitte",
    ),
    "next": (
        "weiter",
        "weitermachen",
        "naechster",
        "naechste",
        "naechstes",
        "skip",
        "ueberspringen",
        # additional navigation commands
        "vor",
        "vorwarts",
        "continue",
        "next",
        "go",
        "los",
        "komm",
        "geh weiter",
        "mach weiter",
        "weiter so",
        "weiter gehts",
        "naechste position",
        "naechste zeile",
        "und weiter",
    ),
    "previous": (
        "zuruck",
        "vorheriger",
        "vorherige",
        "vorheriges",
    ),
    "problem": (
        "problem",
        "fehler",
        "defekt",
        "beschaedigt",
        "kaputt",
        "fehlt",
        "mangel",
        "falsch",
        "passt nicht",
        "stimmt nicht",
        "nicht richtig",
        # additional problem terms
        "verkehrt",
        "nicht in ordnung",
        "was stimmt nicht",
        "da stimmt was nicht",
        "falscher artikel",
        "falsche menge",
        "beschadigung",
    ),
    "photo": (
        "foto",
        "photo",
        "bild",
        "kamera",
        "aufnahme",
        "fotografieren",
    ),
    "repeat": (
        "wiederholen",
        "nochmal",
        "noch mal",
        "wie bitte",
        "was",
        # additional repeat commands
        "bitte",
        "nochmals",
        "kannst du wiederholen",
        "hab nicht verstanden",
        "nicht verstanden",
        "sag das nochmal",
    ),
    "pause": (
        "pause",
        "stopp",
        "stop",
        "halt",
        "warten",
        "moment",
        # additional pause commands
        "abbrechen",
        "aufhoren",
        "genug",
        "schluss",
        "kurze pause",
        "sekunde",
        "einen moment",
    ),
    "done": (
        "fertig",
        "erledigt",
        "abgeschlossen",
        "ende",
        "beenden",
        "komplett",
        # additional done expressions
        "bin fertig",
        "alles erledigt",
        "alles fertig",
        "komplett fertig",
        "geschafft",
        "durch",
        "alles durch",
    ),
    "help": (
        "hilfe",
        "help",
        "befehle",
        "kommandos",
    ),
    "stock_query": (
        "noch da",
        "im bestand",
        "lagerbestand",
        "bestand pruefen",
        "vorratig",
        "verfugbar",
        "auf lager",
    ),
    "filter_high": (
        "dringend",
        "dringlich",
        "wichtig",
        "hohe prioritat",
        "eilig",
        "prio",
    ),
    "filter_normal": (
        "alle",
        "alles",
        "normal",
        "zurucksetzen",
        "filter weg",
        "reset",
    ),
    "status": (
        "wie viele",
        "status",
        "ubersicht",
        "anzahl",
        "offen",
        "auftrage",
        "was steht an",
        "was ist offen",
    ),
}

REGEX_PATTERNS = {
    "confirm_all": (
        r"\b(alles bestaetigen|alle bestaetigen|komplett bestaetigen)\b",
        r"\b(alle positionen bestaetigen|auftrag komplett|auftrag abschliessen)\b",
        r"\b(alles erledigt|alle erledigt|alle durch|alles durch)\b",
        r"\b(alle auf einmal|alles auf einmal|bestaetige alles|bestaetige alle)\b",
        r"\b(bestaetige den auftrag|auftrag fertig|auftrag erledigt|komplett fertig)\b",
    ),
    "confirm": (
        r"\b(bestaetigt|bestaetige|bestaetigen|ja|ok|okay|check)\b",
        r"\b(jep|jup|jo|joa|jupp|klar|gut|passt|stimmt|richtig|genau|jawohl|sicher)\b",
        r"\b(alles klar|geht klar|in ordnung|perfekt|super|alles gut)\b",
        r"\b(paket|karton|position|artikel)\s+(erledigt|fertig)\b",
    ),
    "next_order": (
        r"\b(naechster|naechsten|naechste)\s+auftrag\b",
        r"\b(zum|zum naechsten|weiter zum naechsten)\s+auftrag\b",
        r"\bgib mir den naechsten auftrag\b",
    ),
    "next": (
        r"\b(naechster|naechste|naechstes|weiter|weitermachen|skip|ueberspringen)\b",
        r"\b(naechste position|naechste zeile|mach weiter|geh weiter)\b",
        r"\b(vor|vorwarts|continue|next|forward|los|go|komm)\b",
        r"\b(und weiter|weiter gehts|weitergehts|weiter so)\b",
    ),
    "previous": (
        r"\b(zuruck|davor|eins zuruck|schritt zuruck)\b",
    ),
    "problem": (
        r"\b(problem|fehler|defekt|beschaedigt|kaputt|fehlt|mangel)\b",
        r"\b(falsch|stimmt nicht|nicht richtig|verkehrt|passt nicht)\b",
        r"\b(falsche menge|falsches produkt|falscher artikel)\b",
        r"\b(nicht in ordnung|da stimmt was nicht|was stimmt nicht|beschadigung)\b",
    ),
    "photo": (
        r"\b(foto|photo|bild|kamera|aufnahme|fotografieren)\b",
        r"\b(mach.*foto|mach.*bild)\b",
    ),
    "repeat": (
        r"\b(wiederholen|nochmal|noch mal|wie bitte)\b",
        r"\b(sag nochmal|bitte was|nicht verstanden|hab nicht verstanden)\b",
        r"\b(nochmals|sag das nochmal|kannst du wiederholen)\b",
        r"^was$",
    ),
    "pause": (
        r"\b(pause|stopp|stop|halt|warten|moment)\b",
        r"\b(warte mal|warte kurz|sekunde|einen moment)\b",
        r"\b(abbrechen|aufhoren|genug|schluss|kurze pause)\b",
    ),
    "done": (
        r"\b(fertig|erledigt|abgeschlossen|ende|beenden|komplett)\b",
        r"\b(bin fertig|alles erledigt|alles fertig)\b",
        r"\b(komplett fertig|geschafft|durch|alles durch)\b",
    ),
    "help": (
        r"\b(hilfe|help|befehle|kommandos)\b",
        r"\b(was kann ich|welche befehle)\b",
    ),
    "stock_query": (
        r"\b(noch da|im bestand|lagerbestand|wie viel.*vorrat)\b",
        r"\b(bestand pruefen|vorratig|verfugbar|auf lager)\b",
        r"\b(wie viel haben wir|restbestand|restmenge)\b",
    ),
    "filter_high": (
        r"\b(dringend\w*|dringlich\w*|wichtig\w*|hohe?\s*prioritat|eilig\w*)\b",
        r"\b(zeig.*dringend\w*|nur\s*dringend\w*|express)\b",
    ),
    "filter_normal": (
        r"\b(alle|alles|normal|zurucksetzen|filter weg|reset)\b",
        r"\b(zeig.*alle|alle anzeigen|filter aus)\b",
    ),
    "status": (
        r"\b(wie viele|status|ubersicht|anzahl)\b",
        r"\b(offen|auftrage|was steht an|was ist offen|uberblick)\b",
    ),
}

FUZZY_ACTIONS = {"confirm", "next", "problem", "repeat", "pause", "done"}
SHORT_EXACT_ONLY = {"ja", "ok"}


def recognize_intent(
    text: str,
    context: PickingContext,
    *,
    surface: VoiceSurface = VoiceSurface.DETAIL,
    remaining_line_count: int = 1,
    active_line_present: bool = True,
) -> Intent:
    normalized_text = normalize_text(text)
    if not normalized_text:
        return _unknown_intent(text, normalized_text)

    if context in (
        PickingContext.AWAITING_LOCATION_CHECK,
        PickingContext.AWAITING_QUANTITY_CONFIRM,
    ):
        number = _extract_number(normalized_text)
        if number is not None:
            action = (
                "check_digit"
                if context == PickingContext.AWAITING_LOCATION_CHECK
                else "quantity"
            )
            return Intent(
                action=action,
                value=str(number),
                confidence=EXACT_MATCH_CONFIDENCE,
                raw_text=text,
                normalized_text=normalized_text,
                match_strategy="exact",
            )

    exact_match = _match_exact(text, normalized_text)
    if exact_match is not None:
        return _resolve_with_context(
            _apply_negation_guard(exact_match, normalized_text),
            surface=surface,
            remaining_line_count=remaining_line_count,
            active_line_present=active_line_present,
        )

    regex_match = _match_regex(text, normalized_text)
    if regex_match is not None:
        return _resolve_with_context(
            _apply_negation_guard(regex_match, normalized_text),
            surface=surface,
            remaining_line_count=remaining_line_count,
            active_line_present=active_line_present,
        )

    fuzzy_match = _match_fuzzy(text, normalized_text)
    if fuzzy_match is not None:
        return _resolve_with_context(
            _apply_negation_guard(fuzzy_match, normalized_text),
            surface=surface,
            remaining_line_count=remaining_line_count,
            active_line_present=active_line_present,
        )

    return _unknown_intent(text, normalized_text)


def normalize_text(text: str) -> str:
    normalized = str(text or "").strip().lower()
    normalized = normalized.replace("ß", "ss")
    normalized = normalized.replace("ä", "a").replace("ö", "o").replace("ü", "u")
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    normalized = normalized.replace("ae", "a").replace("oe", "o").replace("ue", "u")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _match_exact(raw_text: str, normalized_text: str) -> Intent | None:
    for action in PRIORITY_ORDER:
        for alias in ALIASES.get(action, ()):
            normalized_alias = normalize_text(alias)
            if normalized_text == normalized_alias:
                return Intent(
                    action=action,
                    value=None,
                    confidence=EXACT_MATCH_CONFIDENCE,
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    match_strategy="exact",
                )
    return None


def _match_regex(raw_text: str, normalized_text: str) -> Intent | None:
    for action in PRIORITY_ORDER:
        for pattern in REGEX_PATTERNS.get(action, ()):
            if re.search(pattern, normalized_text):
                return Intent(
                    action=action,
                    value=None,
                    confidence=EXACT_MATCH_CONFIDENCE,
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    match_strategy="regex",
                )
    return None


def _match_fuzzy(raw_text: str, normalized_text: str) -> Intent | None:
    best_match: Intent | None = None
    best_priority = len(PRIORITY_ORDER)

    for action in PRIORITY_ORDER:
        if action not in FUZZY_ACTIONS:
            continue

        score = _best_fuzzy_score(normalized_text, ALIASES.get(action, ()))
        if score is None:
            continue

        priority = PRIORITY_ORDER.index(action)
        if best_match is None or score > best_match.confidence or (
            score == best_match.confidence and priority < best_priority
        ):
            best_match = Intent(
                action=action,
                value=None,
                confidence=score,
                raw_text=raw_text,
                normalized_text=normalized_text,
                match_strategy="fuzzy",
            )
            best_priority = priority

    return best_match


def _best_fuzzy_score(normalized_text: str, aliases: tuple[str, ...]) -> float | None:
    tokens = [token for token in normalized_text.split(" ") if len(token) >= 4]
    candidates = tokens + ([normalized_text] if len(normalized_text) >= 4 else [])
    best_score: float | None = None

    for alias in aliases:
        normalized_alias = normalize_text(alias)
        if normalized_alias in SHORT_EXACT_ONLY or len(normalized_alias) < 4:
            continue

        threshold = (
            FUZZY_PHRASE_THRESHOLD
            if " " in normalized_alias or " " in normalized_text
            else FUZZY_SINGLE_THRESHOLD
        )

        for candidate in candidates:
            score = levenshtein_similarity(candidate, normalized_alias)
            if score < threshold:
                continue
            if best_score is None or score > best_score:
                best_score = score

    return best_score


def _resolve_with_context(
    intent: Intent,
    *,
    surface: VoiceSurface,
    remaining_line_count: int,
    active_line_present: bool,
) -> Intent:
    if surface == VoiceSurface.QUALITY_ALERT:
        if intent.action in {"pause", "repeat"}:
            return intent
        return _unknown_intent(intent.raw_text, intent.normalized_text)

    if intent.action == "confirm":
        if surface == VoiceSurface.DETAIL and active_line_present:
            return intent
        return _unknown_intent(intent.raw_text, intent.normalized_text)

    if intent.action == "confirm_all":
        if surface == VoiceSurface.DETAIL and active_line_present:
            return intent
        return _unknown_intent(intent.raw_text, intent.normalized_text)

    if intent.action == "next_order":
        if surface in {VoiceSurface.LIST, VoiceSurface.COMPLETE} or not active_line_present:
            return intent
        return _unknown_intent(intent.raw_text, intent.normalized_text)

    if intent.action == "done":
        if remaining_line_count <= 0 and not active_line_present:
            return intent
        return _unknown_intent(intent.raw_text, intent.normalized_text)

    return intent


def _unknown_intent(raw_text: str, normalized_text: str) -> Intent:
    return Intent(
        action="unknown",
        value=None,
        confidence=0.0,
        raw_text=raw_text,
        normalized_text=normalized_text,
        match_strategy="unknown",
    )


WRITE_ACTIONS = frozenset({"confirm", "confirm_all"})


def _has_negation(normalized_text: str) -> bool:
    return any(term in normalized_text.split() for term in NEGATION_TERMS)


def _apply_negation_guard(intent: Intent, normalized_text: str) -> Intent:
    """A negation anywhere in the utterance cancels a booking intent.

    Prevents "nicht ok"/"nicht gut" (not covered by the problem regex) from
    matching the confirm regex and silently booking. Downgrades to a problem
    report instead of confirming.
    """
    if intent.action in WRITE_ACTIONS and _has_negation(normalized_text):
        return Intent(
            action="problem",
            value=None,
            confidence=EXACT_MATCH_CONFIDENCE,
            raw_text=intent.raw_text,
            normalized_text=normalized_text,
            match_strategy="negation",
        )
    return intent


def _extract_number(text: str) -> int | None:
    digits = re.findall(r"\d+", text)
    if digits:
        return int(digits[0])
    for word, digit in GERMAN_NUMBERS.items():
        if word in text.split():
            return int(digit)
    return None


SEGMENT_PENALTY = 0.9


def _partial_ratio(pattern: str, text: str) -> float:
    """Sliding-window Levenshtein similarity — equivalent to fuzz.partial_ratio.

    Finds the best window in `text` of length `len(pattern)` and returns its
    similarity to `pattern`. O(|text| * |pattern|) — fast enough for short
    voice commands and typical Whisper transcripts.
    """
    plen, tlen = len(pattern), len(text)
    if plen == 0 or tlen == 0:
        return 0.0
    if plen >= tlen:
        return levenshtein_similarity(pattern, text)
    best = 0.0
    for i in range(tlen - plen + 1):
        score = levenshtein_similarity(text[i : i + plen], pattern)
        if score > best:
            best = score
        if best == 1.0:
            break
    return best


def _get_surface_actions(
    surface: VoiceSurface,
    remaining_line_count: int,
    active_line_present: bool,
) -> list[str]:
    """Returns the plausible actions for the current UI surface.

    Restricting candidate actions reduces false-positive segment matches when
    the transcript contains generic words that happen to overlap with aliases
    of context-inappropriate actions.
    """
    if surface == VoiceSurface.LIST:
        return ["next_order", "filter_high", "filter_normal", "status", "help", "pause"]
    if surface == VoiceSurface.QUALITY_ALERT:
        return ["pause", "repeat"]
    if surface == VoiceSurface.COMPLETE:
        return ["next_order", "pause", "help"]
    # DETAIL (default)
    actions = ["confirm", "next", "previous", "problem", "repeat", "pause", "photo"]
    if remaining_line_count <= 0 and not active_line_present:
        actions.append("done")
    if not active_line_present and "confirm" in actions:
        actions.remove("confirm")
    return actions


def recognize_intent_from_segments(
    text: str,
    *,
    surface: VoiceSurface = VoiceSurface.DETAIL,
    remaining_line_count: int = 1,
    active_line_present: bool = True,
    min_confidence: float = FUZZY_SINGLE_THRESHOLD,
) -> Intent:
    """Partial-ratio substring search over known keywords.

    Called only when the primary recognize_intent() result is below
    FUZZY_SINGLE_THRESHOLD.  Iterates over *keywords* (not text segments)
    so complexity stays O(K * T) where K = number of alias strings and
    T = len(normalized transcript) — not O(N^2) over word pairs.
    """
    normalized = normalize_text(text)
    if not normalized:
        return _unknown_intent(text, normalized)

    candidate_actions = _get_surface_actions(surface, remaining_line_count, active_line_present)

    best_conf = 0.0
    best_action = "unknown"
    best_alias = ""

    for action in candidate_actions:
        for alias in ALIASES.get(action, ()):
            norm_alias = normalize_text(alias)
            if not norm_alias:
                continue

            if len(norm_alias) < 3:
                # Short aliases ("ja", "ok"): only accept as an isolated token
                if norm_alias in normalized.split():
                    ratio = 0.92  # high but still penalised below
                    if ratio > best_conf:
                        best_conf = ratio
                        best_action = action
                        best_alias = norm_alias
                continue

            ratio = _partial_ratio(norm_alias, normalized)
            if ratio > best_conf:
                best_conf = ratio
                best_action = action
                best_alias = norm_alias

    applied_conf = round(best_conf * SEGMENT_PENALTY, 3)
    if applied_conf < min_confidence or best_action == "unknown":
        return _unknown_intent(text, normalized)

    return Intent(
        action=best_action,
        value=None,
        raw_text=text,
        normalized_text=normalized,
        confidence=applied_conf,
        match_strategy=f"segment_partial({best_alias})",
    )


def levenshtein_similarity(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0

    distance = _levenshtein_distance(left, right)
    max_length = max(len(left), len(right))
    return round(1.0 - (distance / max_length), 2)


def _levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous_row = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current_row = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            insert_cost = current_row[right_index - 1] + 1
            delete_cost = previous_row[right_index] + 1
            replace_cost = previous_row[right_index - 1] + (left_char != right_char)
            current_row.append(min(insert_cost, delete_cost, replace_cost))
        previous_row = current_row
    return previous_row[-1]
