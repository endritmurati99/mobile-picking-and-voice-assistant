"""Korpus-Regressionsgate fuer die Sprach-Intent-Erkennung.

Warum dieser Test existiert
---------------------------
Vor der Sanierung vom 2026-08-02 lag die Fehlerquote der Engine gegen einen
Korpus realistischer deutscher Picker-Saetze bei 41 %. Drei Fehlerklassen waren
dabei besonders schaedlich, weil sie fuer den Nutzer nicht als Fehler sichtbar
waren:

  * **stumme Fehlbuchung** -- eine beilaeufige Floskel ("super gemacht") wurde
    als `confirm` mit Konfidenz >= 0.90 gewertet und buchte ohne Rueckfrage.
  * **stiller No-Op** -- ein Satz wie "alle sechs bestaetigen" landete bei
    `filter_normal`, wofuer die PWA bei geoeffnetem Auftrag ein `break` ohne
    Ansage hat. Aus Nutzersicht nicht unterscheidbar von "hat mich nicht
    gehoert".
  * **Reichweitenfehler** -- "den ganzen Auftrag bestaetigen" buchte eine
    einzelne Zeile, weil ein Fuzzy-Teiltreffer auf dem Wort "bestaetigen"
    Konfidenz 1.00 lieferte und damit den Gesamtsinn ueberstimmte.

Die Gates unten halten genau diese drei Klassen geschlossen.

Ehrlichkeitshinweis fuer die Arbeit
-----------------------------------
Dieser Korpus ist KONSTRUIERT, nicht im Feld aufgezeichnet. Eine niedrige
Fehlerquote hier ist eine Regressionsschranke, kein Guetesiegel fuer die
Erkennungsleistung im Lager. Der naechste Schritt waere eine Testschicht mit
echten Whisper-Transkripten aus dem Betrieb.
"""
from __future__ import annotations

import pytest

from app.services.intent_engine import (
    FUZZY_SINGLE_THRESHOLD,
    PickingContext,
    VoiceSurface,
    recognize_intent,
    recognize_intent_from_segments,
)

# Schwelle, ab der die PWA ohne Rueckfrage bucht (voice-runtime.mjs).
DIRECT_BOOK_THRESHOLD = 0.90

BOOKING_ACTIONS = {"confirm", "confirm_all"}


def classify(text: str, *, surface=VoiceSurface.DETAIL, remaining=6, active=True):
    """Bildet die Kette aus routers/voice.py nach: erst der deterministische
    Matcher, bei niedriger Konfidenz zusaetzlich der Segment-Fallback.
    Der LLM-Fallback bleibt bewusst aussen vor -- dieser Test prueft die
    deterministische Schicht."""
    intent = recognize_intent(
        text,
        PickingContext.AWAITING_COMMAND,
        surface=surface,
        remaining_line_count=remaining,
        active_line_present=active,
    )
    if intent.action == "unknown" or intent.confidence < FUZZY_SINGLE_THRESHOLD:
        seg = recognize_intent_from_segments(
            text,
            surface=surface,
            remaining_line_count=remaining,
            active_line_present=active,
        )
        if seg.confidence > intent.confidence:
            intent = seg
    return intent


# --------------------------------------------------------------------------
# A. Ganzer Auftrag -- MUSS confirm_all ergeben.
#    Das ist die Beschwerde, mit der die Sanierung angestossen wurde.
# --------------------------------------------------------------------------
CONFIRM_ALL_PHRASES = [
    "alles bestätigen",
    "alle bestätigen",
    "alle Positionen bestätigen",
    "Auftrag komplett bestätigen",
    "kompletten Auftrag bestätigen",
    "den kompletten Auftrag bestätigen",
    "den ganzen Auftrag bestätigen",
    "ganzen Auftrag bestätigen",
    "bestätige den kompletten Auftrag",
    "bestätige alles",
    "alle sechs bestätigen",
    "alle sechs Positionen bestätigen",
    "sämtliche Positionen bestätigen",
    "den gesamten Auftrag buchen",
    "komplett bestätigen",
    "Auftrag fertig",
    "Auftrag erledigt",
    "alles erledigt",
    "alles fertig",
    "alles durch",
]

# --------------------------------------------------------------------------
# B. Einzelne Position bzw. Antwort auf die Rueckfrage -- MUSS confirm ergeben.
# --------------------------------------------------------------------------
CONFIRM_PHRASES = [
    "bestätigen",
    "bestätige",
    "bitte bestätigen",
    "buchen",
    "ja",
    "jawohl",
    "genau",
    "richtig",
    "stimmt",
    "ok",
    "okay",
    "passt",
]

# --------------------------------------------------------------------------
# C. Aeusserungen, die NIEMALS ohne Rueckfrage buchen duerfen.
#    Beilaeufiges Gerede, Hoeflichkeit, Selbstgespraech, Umgebungssaetze.
# --------------------------------------------------------------------------
MUST_NOT_BOOK = [
    "Guten Morgen",
    "guten Morgen zusammen",
    "super gemacht",
    "alles gut soweit",
    "das ist halt so",
    "na gut dann",
    "vor dem Regal steht eine Kiste",
    "die Kiste ist offen",
    "mach mal langsam",
    "wo ist denn das Regal",
    "ich schaue mal nach",
    "der Karton ist ganz schön schwer",
    "das dauert ja alles ewig",
    "warte ich muss kurz überlegen",
]

# --------------------------------------------------------------------------
# D. Verneinungen -- duerfen das Kommando nicht ausfuehren.
# --------------------------------------------------------------------------
NEGATIONS = [
    ("nicht bestätigen", {"problem"}),
    ("nicht buchen", {"problem"}),
    ("kein Foto", {"abort"}),
    ("keine Pause", {"abort"}),
    ("stopp nicht weiter", {"abort", "pause"}),
]

# --------------------------------------------------------------------------
# E. Selbstkorrektur -- der Diskursmarker hebt das Kommando NICHT auf.
# --------------------------------------------------------------------------
SELF_CORRECTIONS = [
    ("nein weiter zur nächsten Position", "next"),
    ("nein, zurück", "previous"),
]

# --------------------------------------------------------------------------
# F. Navigation und Rueckfragen -- duerfen nicht als Buchung enden.
# --------------------------------------------------------------------------
NAVIGATION = [
    ("weiter", "next"),
    ("nächste Position", "next"),
    ("zurück", "previous"),
    ("wiederholen", "repeat"),
    ("nochmal", "repeat"),
    ("was jetzt", "whats_next"),
    ("wo", "where"),
    ("welches Regal", "where"),
    ("wie viele noch", "how_many_left"),
    ("Problem", "problem"),
    ("Artikel ist kaputt", "problem"),
    ("Pause", "pause"),
]


@pytest.mark.parametrize("text", CONFIRM_ALL_PHRASES)
def test_whole_order_phrases_yield_confirm_all(text):
    """Die Kernbeschwerde: eine Reichweitenangabe muss den ganzen Auftrag
    meinen, nicht die aktuelle Zeile."""
    intent = classify(text)
    assert intent.action == "confirm_all", (
        f"{text!r} -> {intent.action} ({intent.confidence:.2f}, {intent.match_strategy})"
    )


@pytest.mark.parametrize("text", CONFIRM_PHRASES)
def test_single_line_and_readback_answers_yield_confirm(text):
    intent = classify(text)
    assert intent.action == "confirm", (
        f"{text!r} -> {intent.action} ({intent.confidence:.2f}, {intent.match_strategy})"
    )


@pytest.mark.parametrize("text", MUST_NOT_BOOK)
def test_incidental_speech_never_books_silently(text):
    """Haerteste Zusage des Tests: Nebengerede darf nie ohne Rueckfrage buchen.

    Ein Treffer mit niedriger Konfidenz ist erlaubt -- der loest die Rueckfrage
    oder den LLM-Fallback aus. Verboten ist nur die stumme Direktbuchung.
    """
    intent = classify(text)
    silent_booking = (
        intent.action in BOOKING_ACTIONS and intent.confidence >= DIRECT_BOOK_THRESHOLD
    )
    assert not silent_booking, (
        f"{text!r} wuerde stumm buchen: {intent.action} {intent.confidence:.2f} "
        f"({intent.match_strategy})"
    )


@pytest.mark.parametrize("text,allowed", NEGATIONS)
def test_negation_cancels_the_command(text, allowed):
    intent = classify(text)
    assert intent.action in allowed, (
        f"{text!r} -> {intent.action} ({intent.confidence:.2f})"
    )
    assert intent.action not in BOOKING_ACTIONS


@pytest.mark.parametrize("text,expected", SELF_CORRECTIONS)
def test_discourse_marker_keeps_the_command(text, expected):
    """"Nein, weiter zur naechsten Position" ist eine Selbstkorrektur mit
    Kommando -- kein Abbruch."""
    assert classify(text).action == expected


@pytest.mark.parametrize("text,expected", NAVIGATION)
def test_navigation_and_queries_keep_their_meaning(text, expected):
    assert classify(text).action == expected


def test_no_dead_regex_literals():
    """Sichert die Wurzelursache dauerhaft ab.

    Die Muster in REGEX_PATTERNS werden gegen Text geprueft, den normalize_text
    zuvor auf a/o/u zusammengezogen hat. Ein Muster, das noch ae/oe/ue enthaelt,
    kann deshalb NIE treffen -- vor der Sanierung betraf das 26 von 211 Mustern,
    darunter die komplette bestaetigen- und naechst-Familie.
    """
    from app.services.intent_engine import REGEX_PATTERNS

    dead = [
        (action, pattern)
        for action, patterns in REGEX_PATTERNS.items()
        for pattern in patterns
        if "ae" in pattern or "oe" in pattern or "ue" in pattern
    ]
    assert not dead, f"Muster koennen nie treffen (ae/oe/ue vs. normalisierter Text): {dead}"


def test_corpus_error_rate_gate():
    """Gesamt-Gate ueber den vollstaendigen Korpus.

    Zaehlt getrennt, was der Nutzer unterschiedlich erlebt: eine stumme
    Fehlbuchung ist gravierender als ein nicht erkannter Satz.
    """
    failures, silent_bookings = [], []

    for text in CONFIRM_ALL_PHRASES:
        if classify(text).action != "confirm_all":
            failures.append(text)
    for text in CONFIRM_PHRASES:
        if classify(text).action != "confirm":
            failures.append(text)
    for text, expected in NAVIGATION + SELF_CORRECTIONS:
        if classify(text).action != expected:
            failures.append(text)
    for text, allowed in NEGATIONS:
        if classify(text).action not in allowed:
            failures.append(text)
    for text in MUST_NOT_BOOK:
        intent = classify(text)
        if intent.action in BOOKING_ACTIONS and intent.confidence >= DIRECT_BOOK_THRESHOLD:
            silent_bookings.append(text)

    total = (
        len(CONFIRM_ALL_PHRASES) + len(CONFIRM_PHRASES) + len(NAVIGATION)
        + len(SELF_CORRECTIONS) + len(NEGATIONS) + len(MUST_NOT_BOOK)
    )
    error_rate = len(failures) / total

    assert not silent_bookings, f"stumme Fehlbuchungen: {silent_bookings}"
    assert error_rate <= 0.10, (
        f"Fehlerquote {error_rate:.0%} ueber {total} Saetze (Grenze 10 %): {failures}"
    )
