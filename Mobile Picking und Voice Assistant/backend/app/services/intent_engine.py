"""
Voice intent engine for deterministic, context-aware command matching.

STT stays server-side via Whisper. This module only maps recognized text
to safe application intents.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


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
    "how_many_left",
    "whats_next",
    "where",
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
        # "alles fertig"/"alle fertig" standen bisher NUR in den done-Aliassen.
        # _match_exact laeuft vor _match_regex, traf dort also `done` -- und das
        # wird bei offenen Positionen vom Surface-Gate auf unknown gesetzt.
        # Ergebnis: "alles fertig" tat gar nichts. confirm_all steht in
        # PRIORITY_ORDER vor done und faengt es jetzt korrekt ab.
        "alles fertig",
        "alle fertig",
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
    "whats_next": (
        "was jetzt",
        "was nun",
        "was muss ich picken",
        "was muss ich holen",
        "was als naechstes",
        "naechste position bitte",
        "was ist dran",
    ),
    "where": (
        "wo",
        "wohin",
        "welcher platz",
        "welches fach",
        "welches regal",
    ),
    "how_many_left": (
        "wie viele noch",
        "wie viel noch",
        "wieviele offen",
        "wie viele offen",
    ),
}

REGEX_PATTERNS = {
    "confirm_all": (
        # Scope-Regeln: ein Reichweiten-Wort ("alle", "komplett", "ganz") in
        # Verbindung mit einem Buchungsverb meint den GANZEN Auftrag, egal wie
        # der Satz drumherum gebaut ist. Vorher war nur die woertliche Wendung
        # "alles bestaetigen" erfasst, weshalb "den ganzen Auftrag bestaetigen"
        # auf das Einzelzeilen-confirm fiel.
        #
        # Das Fenster von hoechstens drei Fuellwoertern zwischen Scope und Verb
        # ist die entscheidende Begrenzung: es erlaubt Artikel und Mengenangaben
        # ("alle SECHS bestaetigen", "den KOMPLETTEN Auftrag"), verhindert aber,
        # dass Scope- und Verbwort aus zwei unabhaengigen Aussagen
        # zusammengezogen werden.
        r"\b(alle|alles|allen|saemtliche|komplett\w*|ganze\w*|gesamt\w*|jede\w*)\b"
        r"(?:\s+\w+){0,3}\s+"
        r"\b(bestaetig\w*|buch\w*|abschliess\w*|fertig|erledigt|abgeschlossen|durch)\b",
        r"\b(bestaetig\w*|buch\w*|abschliess\w*)\b"
        r"(?:\s+\w+){0,3}\s+"
        r"\b(alle|alles|allen|saemtliche|komplett\w*|ganze\w*|gesamt\w*)\b",
        r"\b(auftrag|auftrags|lieferung)\b"
        r"(?:\s+\w+){0,2}\s+"
        r"\b(komplett|fertig|erledigt|abgeschlossen|abschliessen|bestaetigen|durch)\b",
        r"\b(alles bestaetigen|alle bestaetigen|komplett bestaetigen)\b",
        r"\b(alle positionen bestaetigen|auftrag komplett|auftrag abschliessen)\b",
        r"\b(alles erledigt|alle erledigt|alle durch|alles durch)\b",
        r"\b(alle auf einmal|alles auf einmal|bestaetige alles|bestaetige alle)\b",
        r"\b(bestaetige den auftrag|auftrag fertig|auftrag erledigt|komplett fertig)\b",
    ),
    "confirm": (
        # Buchungsverben duerfen mitten im Satz stehen ("bitte bestaetigen").
        # Die Alle-Faelle faengt confirm_all vorher ab, es steht in
        # PRIORITY_ORDER davor.
        r"\b(bestaetigt|bestaetige|bestaetigen|buche|buchen|gebucht)\b",
        # Kurze Zustimmungen und Hoeflichkeitspartikeln NUR als vollstaendige
        # Aeusserung. Vorher genuegte ihr blosses Vorkommen irgendwo im Satz --
        # "super gemacht", "alles gut soweit" und "guten morgen" haben damit
        # ungefragt eine Position gebucht. Als Antwort auf die Rueckfrage
        # ("<Produkt>, richtig?") bleiben sie vollstaendig erhalten, denn dort
        # ist die Aeusserung genau ein Wort.
        r"^(?:ja|jawohl|jep|jup|jo|joa|jupp|ok|okay|check|klar|gut|passt|stimmt"
        r"|richtig|genau|sicher|perfekt|super|alles klar|geht klar|in ordnung"
        r"|alles gut|das passt|passt so|das passt so|stimmt so)$",
        r"^(?:paket|karton|position|artikel)\s+(?:erledigt|fertig)$",
    ),
    "next_order": (
        r"\b(naechster|naechsten|naechste)\s+auftrag\b",
        r"\b(zum|zum naechsten|weiter zum naechsten)\s+auftrag\b",
        r"\bgib mir den naechsten auftrag\b",
    ),
    "next": (
        r"\b(naechster|naechste|naechstes|weiter|weitermachen|skip|ueberspringen)\b",
        r"\b(naechste position|naechste zeile|mach weiter|geh weiter)\b",
        r"\b(vorwarts|continue|forward)\b",
        # Kurze Allerweltswoerter nur als ganze Aeusserung: "vor" trifft sonst
        # "vor dem Regal", "los" trifft "es geht los damit".
        r"^(?:vor|los|go|komm|next)$",
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
        r"\b(pause|stopp|stop|warten|moment)\b",
        # "halt" ist die haeufigste deutsche Modalpartikel ("das ist halt so",
        # "mach halt weiter") und schaltete unverankert den Sprachmodus ab.
        r"^halt$",
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
    # Die drei Filter-/Status-Intents sind Listenkommandos und bestehen aus
    # Allerweltswoertern ("alle", "alles", "offen", "auftrage"). Unverankert
    # kaperten sie jeden Satz, der eines davon enthielt: "alle sechs
    # bestaetigen" wurde zu filter_normal, und weil app.js dafuer bei
    # geoeffnetem Auftrag ein `break` ohne Ansage hat, passierte GAR NICHTS --
    # aus Nutzersicht nicht unterscheidbar von "hat mich nicht gehoert".
    # Als vollstaendige Aeusserung bleiben sie erhalten.
    "filter_high": (
        r"^(?:nur\s+)?(?:dringend\w*|dringlich\w*|wichtig\w*|eilig\w*|express)$",
        r"^(?:hohe?\s*prioritat|prio)$",
        r"^zeig\w*\s+(?:mir\s+)?(?:nur\s+)?(?:die\s+)?dringend\w*$",
    ),
    "filter_normal": (
        r"^(?:alle|alles|normal|zurucksetzen|filter weg|filter aus|reset)$",
        r"^(?:zeig\w*\s+(?:mir\s+)?)?alle(?:\s+auftrage)?(?:\s+anzeigen)?$",
    ),
    "status": (
        r"^(?:status|ubersicht|uberblick|anzahl)$",
        r"^wie ?viele?(?:\s+\w+){0,2}$",
        r"^(?:was steht an|was ist offen|was ist noch offen)$",
    ),
    "whats_next": (
        r"\b(was jetzt|was nun|was als naechstes|was ist dran)\b",
        r"\bwas muss ich (picken|holen|nehmen)\b",
    ),
    "where": (
        r"\b(wo|wohin)\b",
        r"\b(welches (fach|regal)|welcher platz)\b",
    ),
    "how_many_left": (
        r"\bwie ?viele? (noch|offen)\b",
        r"\bwie ?viel noch\b",
    ),
}

def _normalize_pattern(pattern: str) -> str:
    """Zieht ae/oe/ue in einem Regex-Literal genauso zusammen wie normalize_text
    es mit dem Eingabetext tut.

    Ohne das konnten 26 der 211 Muster NIE treffen: sie sind in
    ae/oe/ue-Schreibweise notiert ("bestaetigen", "naechste", "ueberspringen"),
    geprueft werden sie aber gegen Text, den normalize_text vorher auf a/o/u
    kollabiert hat ("bestatigen", "nachste", "uberspringen"). Betroffen war unter
    anderem die komplette bestaetigen- und naechst-Familie -- `confirm_all` und
    `next_order` waren ueber den Regex-Pfad damit ueberhaupt nicht erreichbar,
    weshalb jede Umformulierung von "alles bestaetigen" beim Einzelzeilen-
    `confirm` landete.

    Sicher, weil kein Regex-Metazeichen die Folgen ae/oe/ue enthaelt.
    """
    return pattern.replace("ae", "a").replace("oe", "o").replace("ue", "u")


REGEX_PATTERNS = {
    action: tuple(_normalize_pattern(pattern) for pattern in patterns)
    for action, patterns in REGEX_PATTERNS.items()
}

# confirm_all gehoert in die Fuzzy-Stufe, sonst ist es nur ueber exakte
# Wortgleichheit erreichbar und jede Umformulierung faellt auf confirm zurueck.
FUZZY_ACTIONS = {"confirm", "confirm_all", "next", "problem", "repeat", "pause", "done"}
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
            # Abdeckungsstrafe: wie viel der GESAMTEN Aeusserung erklaert dieser
            # Treffer eigentlich? Vorher zaehlte nur das Maximum ueber alle
            # Token/Alias-Paare, ohne Laengenbezug -- ein einziges erkanntes Wort
            # in einem beliebig langen Satz lieferte 1.00. In "kompletten auftrag
            # bestatigen" traf das Token "bestatigen" den confirm-Alias exakt und
            # gewann damit gegen den eigentlich gemeinten Gesamtsinn.
            #
            # Der Deckel 0.94 liegt bewusst HART UNTER EXACT_MATCH_CONFIDENCE
            # (0.95): ein Teiltreffer kann einen exakten Volltreffer strukturell
            # nicht mehr schlagen. Zugleich rutschen schwach abgedeckte Treffer
            # unter die Schwellen und erreichen damit erstmals die Rueckfrage
            # bzw. den LLM-Fallback, statt stumm zu buchen.
            coverage = min(1.0, len(normalized_alias) / max(len(normalized_text), 1))
            adjusted = min(0.94, score * (0.5 + 0.5 * coverage))
            if best_score is None or adjusted > best_score:
                best_score = adjusted

    return best_score


def _resolve_with_context(
    intent: Intent,
    *,
    surface: VoiceSurface,
    remaining_line_count: int,
    active_line_present: bool,
) -> Intent:
    if surface == VoiceSurface.QUALITY_ALERT:
        if intent.action == "confirm":
            return Intent(
                action="submit_alert",
                value=intent.value,
                confidence=intent.confidence,
                raw_text=intent.raw_text,
                normalized_text=intent.normalized_text,
                match_strategy=intent.match_strategy,
            )
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

    if intent.action in {"whats_next", "where"}:
        if surface == VoiceSurface.DETAIL and active_line_present:
            return intent
        return _unknown_intent(intent.raw_text, intent.normalized_text)

    if intent.action == "how_many_left":
        if surface == VoiceSurface.DETAIL:
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
    """Bleibt als gemeinsame Vorpruefung erhalten: enthaelt die Aeusserung
    ueberhaupt irgendeine Verneinung? Die Unterscheidung, welche Art, trifft
    _apply_negation_guard ueber CANCEL_TERMS und DISCOURSE_NEGATIONS."""
    return any(term in normalized_text.split() for term in NEGATION_TERMS)


# Echte Verneinung: hebt das Kommando auf.
CANCEL_TERMS = ("nicht", "kein", "keine", "keinen", "nie", "niemals")
# Diskursmarker: leiten eine Selbstkorrektur ein, heben das FOLGENDE Kommando
# aber nicht auf. "Nein, weiter zur naechsten Position" ist ein Weiter-Befehl.
# Sie stehen bewusst NICHT in CANCEL_TERMS -- genau darin liegt der
# Unterschied zwischen "nein, weiter" (ausfuehren) und "nicht weiter" (abbrechen).
DISCOURSE_NEGATIONS = ("nein", "doch")
# Wendungen, in denen die Verneinung Teil des Alias selbst ist -- hier darf der
# Guard nicht greifen, sonst wird eine Problemmeldung zur Problemmeldung
# umgedeutet oder eine Rueckfrage unmoeglich.
NEGATION_LITERAL_PHRASES = (
    "stimmt nicht",
    "nicht in ordnung",
    "nicht richtig",
    "nicht verstanden",
    "nicht gefunden",
    "nichts mehr",
    "passt nicht",
    "da stimmt was nicht",
    "was stimmt nicht",
)


def _has_cancel_term(normalized_text: str) -> bool:
    return any(term in normalized_text.split() for term in CANCEL_TERMS)


def _apply_negation_guard(intent: Intent, normalized_text: str) -> Intent:
    """Eine Verneinung hebt das erkannte Kommando auf -- fuer ALLE Intents.

    Vorher galt der Schutz nur fuer Buchungen (WRITE_ACTIONS). "Kein Foto
    machen" oeffnete deshalb die Kamera und "keine Pause" beendete den
    Sprachmodus -- die Verneinung wurde schlicht ignoriert.

    Zwei Klassen, weil sie Gegenteiliges bedeuten:
      * Cancel-Term (nicht/kein/nie): hebt auf. Bei Buchungen weiterhin
        Umdeutung zu `problem` (die etablierte, getestete Zusage), sonst
        `abort`.
      * Diskursmarker (nein/doch) OHNE Cancel-Term: Selbstkorrektur, das
        Kommando dahinter ist gemeint und wird ausgefuehrt.

    `abort` ist bewusst NICHT in EXTERNAL_INTENT_LABELS -- der LLM darf es
    nicht erfinden.
    """
    # Billige Vorpruefung: ohne jede Verneinung ist hier nichts zu tun.
    if not _has_negation(normalized_text):
        return intent

    if any(phrase in normalized_text for phrase in NEGATION_LITERAL_PHRASES):
        return intent

    # Ab hier steht fest: es gibt eine Verneinung, aber keine woertliche
    # Ausnahme. Ohne echten Cancel-Term bleibt nur ein Diskursmarker
    # (DISCOURSE_NEGATIONS) oder "falsch" uebrig -- beides hebt das Kommando
    # nicht auf. "Nein, weiter zur naechsten Position" bleibt damit `next`.
    if not _has_cancel_term(normalized_text):
        return intent

    if intent.action in WRITE_ACTIONS:
        return Intent(
            action="problem",
            value=None,
            confidence=EXACT_MATCH_CONFIDENCE,
            raw_text=intent.raw_text,
            normalized_text=normalized_text,
            match_strategy="negation",
        )

    if intent.action == "unknown":
        return intent

    return Intent(
        action="abort",
        value=None,
        confidence=EXACT_MATCH_CONFIDENCE,
        raw_text=intent.raw_text,
        normalized_text=normalized_text,
        match_strategy="negation",
    )


# Labels an externally-produced classifier (LLM) may return. Mirrors the safe
# action vocabulary of the deterministic engine.
EXTERNAL_INTENT_LABELS = frozenset({
    "confirm", "confirm_all", "next", "previous", "next_order", "problem",
    "photo", "pause", "done", "whats_next", "where", "how_many_left",
    "status", "repeat", "help",
})

# An LLM-derived write intent is capped below the frontend direct-book threshold
# (0.90), so it can never book directly -- it always triggers a read-back.
LLM_WRITE_CONFIDENCE_CAP = 0.85


def finalize_external_intent(
    action: str,
    confidence: float,
    *,
    raw_text: str,
    normalized_text: str,
    surface: VoiceSurface,
    remaining_line_count: int,
    active_line_present: bool,
) -> Intent:
    """Run an externally produced (LLM) label through the same safeguards as a
    deterministic match: reject unknown labels, clamp write confidence so writes
    always read-back downstream, apply the negation guard, then surface gating.

    Der LLM-Zweig ist ein nachgelagerter Fallback: sein Ergebnis wird nur
    uebernommen, wenn es besser ist als der deterministische Treffer. Ein Fehler
    hier (kaputte confidence, unerwarteter Wert aus dem Modell) darf deshalb den
    Hauptpfad nicht mitreissen -- er wird protokolliert und als `unknown`
    gemeldet, womit der Aufrufer beim deterministischen Ergebnis bleibt.
    """
    if action not in EXTERNAL_INTENT_LABELS:
        return _unknown_intent(raw_text, normalized_text)
    try:
        conf = max(0.0, min(1.0, float(confidence)))
        if action in WRITE_ACTIONS:
            conf = min(conf, LLM_WRITE_CONFIDENCE_CAP)
        intent = Intent(
            action=action,
            value=None,
            confidence=conf,
            raw_text=raw_text,
            normalized_text=normalized_text,
            match_strategy="llm",
        )
        intent = _apply_negation_guard(intent, normalized_text)
        return _resolve_with_context(
            intent,
            surface=surface,
            remaining_line_count=remaining_line_count,
            active_line_present=active_line_present,
        )
    except Exception as exc:
        logger.warning(
            "LLM-Intent '%s' konnte nicht abgesichert werden, deterministisches "
            "Ergebnis bleibt bestehen: %s",
            action,
            exc,
        )
        return _unknown_intent(raw_text, normalized_text)


def _extract_number(text: str) -> int | None:
    digits = re.findall(r"\d+", text)
    if digits:
        return int(digits[0])
    for word, digit in GERMAN_NUMBERS.items():
        if word in text.split():
            return int(digit)
    return None


# 0.85 statt 0.9: ein perfekter Segment-Treffer ergab 1.00 * 0.9 = 0.90 und traf
# damit EXAKT die Direktbuchungs-Schwelle der PWA (VOICE_CONFIRM_DIRECT_THRESHOLD
# in voice-runtime.mjs). Ein Fallback-Treffer ist per Definition schwaechere
# Evidenz als ein Volltreffer und darf nie ohne Rueckfrage buchen -- 0.85 legt
# ihn strikt darunter.
SEGMENT_PENALTY = 0.85


# Aliase, die nur als VOLLSTAENDIGE Aeusserung gelten duerfen. Es sind kurze
# Allerweltswoerter; im Segment-Fallback erzeugten sie sonst Treffer mitten in
# unbeteiligten Woertern.
WHOLE_UTTERANCE_ONLY = frozenset({
    "gut", "super", "klar", "passt", "stimmt", "richtig", "genau", "bitte",
    "halt", "los", "vor", "was", "komm", "go", "next", "check", "sicher",
    "perfekt", "alle", "alles", "normal", "offen", "prio", "ende", "durch",
})


def _partial_ratio(pattern: str, text: str) -> float:
    """Levenshtein-Aehnlichkeit ueber zusammenhaengende TOKEN-Fenster.

    Vorher lief hier ein Zeichen-Schiebefenster. Das fand `gut` in "Guten
    Morgen", `vor` in "vorsichtig" und `was` in "Waschbecken" -- mit voller
    Aehnlichkeit 1.00, die nach SEGMENT_PENALTY exakt auf der Direktbuchungs-
    Schwelle landete. "Guten Morgen" buchte damit eine Position.

    Ein Tokenfenster kann das strukturell nicht: verglichen wird nur gegen
    ganze Woerter bzw. Wortfolgen. Zusaetzlich muss jedes Einzeltoken des
    Fensters fuer sich plausibel sein (>= 0.72), sonst zieht ein einzelnes
    perfekt passendes Wort ein ansonsten unpassendes Fenster nach oben.
    """
    if not pattern or not text:
        return 0.0

    pattern_tokens = pattern.split()
    text_tokens = text.split()
    if not pattern_tokens or not text_tokens:
        return 0.0

    span = len(pattern_tokens)
    if span > len(text_tokens):
        return levenshtein_similarity(pattern, text)

    best = 0.0
    for start in range(len(text_tokens) - span + 1):
        window = text_tokens[start : start + span]
        per_token = [
            levenshtein_similarity(window_token, pattern_token)
            for window_token, pattern_token in zip(window, pattern_tokens)
        ]
        if min(per_token) < 0.72:
            continue
        score = levenshtein_similarity(" ".join(window), pattern)
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
        return ["confirm", "pause", "repeat"]
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

            # Allerweltswoerter zaehlen im Segment-Fallback nur, wenn sie die
            # GANZE Aeusserung sind -- sonst kapert "gut" jedes "guten Morgen".
            if norm_alias in WHOLE_UTTERANCE_ONLY:
                if normalized == norm_alias:
                    ratio = 1.0
                    if ratio > best_conf:
                        best_conf = ratio
                        best_action = action
                        best_alias = norm_alias
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

    return _resolve_with_context(
        Intent(
            action=best_action,
            value=None,
            raw_text=text,
            normalized_text=normalized,
            confidence=applied_conf,
            match_strategy=f"segment_partial({best_alias})",
        ),
        surface=surface,
        remaining_line_count=remaining_line_count,
        active_line_present=active_line_present,
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
