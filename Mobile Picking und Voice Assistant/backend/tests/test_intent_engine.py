"""Tests für die Voice-Intent-Engine."""
from app.services.intent_engine import (
    recognize_intent,
    PickingContext,
)


class TestIntentRecognition:
    def test_confirm_recognized(self):
        intent = recognize_intent("bestätigt", PickingContext.AWAITING_COMMAND)
        assert intent.action == "confirm"
        assert intent.confidence >= 0.8

    def test_next_recognized(self):
        intent = recognize_intent("nächster", PickingContext.AWAITING_COMMAND)
        assert intent.action == "next"

    def test_problem_recognized(self):
        intent = recognize_intent("da ist ein problem", PickingContext.AWAITING_COMMAND)
        assert intent.action == "problem"

    def test_number_as_check_digit(self):
        intent = recognize_intent("vier sieben", PickingContext.AWAITING_LOCATION_CHECK)
        assert intent.action == "check_digit"
        assert intent.value == "4"  # Erster Match

    def test_digit_as_quantity(self):
        intent = recognize_intent("5", PickingContext.AWAITING_QUANTITY_CONFIRM)
        assert intent.action == "quantity"
        assert intent.value == "5"

    def test_german_number_word(self):
        intent = recognize_intent("fünf", PickingContext.AWAITING_QUANTITY_CONFIRM)
        assert intent.action == "quantity"
        assert intent.value == "5"

    def test_unknown_text(self):
        intent = recognize_intent("blablabla", PickingContext.AWAITING_COMMAND)
        assert intent.action == "unknown"
        assert intent.confidence == 0.0

    def test_empty_text(self):
        intent = recognize_intent("", PickingContext.AWAITING_COMMAND)
        assert intent.action == "unknown"

    def test_repeat_recognized(self):
        intent = recognize_intent("bitte wiederholen", PickingContext.AWAITING_COMMAND)
        assert intent.action == "repeat"

    def test_done_recognized(self):
        intent = recognize_intent("fertig", PickingContext.AWAITING_COMMAND)
        assert intent.action == "done"

    def test_case_insensitive(self):
        intent = recognize_intent("BESTÄTIGT", PickingContext.AWAITING_COMMAND)
        assert intent.action == "confirm"

    # ── Erweiterte Patterns: natürliche Sprache ──────────────

    def test_confirm_passt(self):
        intent = recognize_intent("ja passt", PickingContext.AWAITING_COMMAND)
        assert intent.action == "confirm"

    def test_confirm_genau(self):
        intent = recognize_intent("genau", PickingContext.AWAITING_COMMAND)
        assert intent.action == "confirm"

    def test_confirm_alles_klar(self):
        intent = recognize_intent("alles klar", PickingContext.AWAITING_COMMAND)
        assert intent.action == "confirm"

    def test_confirm_in_ordnung(self):
        intent = recognize_intent("in ordnung", PickingContext.AWAITING_COMMAND)
        assert intent.action == "confirm"

    def test_confirm_geht_klar(self):
        intent = recognize_intent("geht klar", PickingContext.AWAITING_COMMAND)
        assert intent.action == "confirm"

    def test_next_weitermachen(self):
        intent = recognize_intent("weitermachen", PickingContext.AWAITING_COMMAND)
        assert intent.action == "next"

    def test_next_mach_weiter(self):
        intent = recognize_intent("mach weiter", PickingContext.AWAITING_COMMAND)
        assert intent.action == "next"

    def test_next_naechste_position(self):
        intent = recognize_intent("nächste position", PickingContext.AWAITING_COMMAND)
        assert intent.action == "next"

    def test_problem_stimmt_nicht(self):
        intent = recognize_intent("das stimmt nicht", PickingContext.AWAITING_COMMAND)
        assert intent.action == "problem"

    def test_problem_falsch(self):
        intent = recognize_intent("das ist falsch", PickingContext.AWAITING_COMMAND)
        assert intent.action == "problem"

    def test_problem_passt_nicht(self):
        intent = recognize_intent("passt nicht", PickingContext.AWAITING_COMMAND)
        assert intent.action == "problem"

    def test_problem_falsches_produkt(self):
        intent = recognize_intent("falsches produkt", PickingContext.AWAITING_COMMAND)
        assert intent.action == "problem"

    def test_repeat_was(self):
        intent = recognize_intent("was", PickingContext.AWAITING_COMMAND)
        assert intent.action == "repeat"

    def test_repeat_verstehe_nicht(self):
        intent = recognize_intent("verstehe nicht", PickingContext.AWAITING_COMMAND)
        assert intent.action == "repeat"

    def test_done_bin_fertig(self):
        intent = recognize_intent("bin fertig", PickingContext.AWAITING_COMMAND)
        assert intent.action == "done"

    def test_done_alles_erledigt(self):
        intent = recognize_intent("alles erledigt", PickingContext.AWAITING_COMMAND)
        assert intent.action == "done"

    def test_pause_moment(self):
        intent = recognize_intent("moment mal", PickingContext.AWAITING_COMMAND)
        assert intent.action == "pause"

    def test_pause_warte_mal(self):
        intent = recognize_intent("warte mal", PickingContext.AWAITING_COMMAND)
        assert intent.action == "pause"

    def test_stock_wie_viel_haben_wir(self):
        intent = recognize_intent("wie viel haben wir", PickingContext.AWAITING_COMMAND)
        assert intent.action == "stock_query"

    def test_stock_auf_lager(self):
        intent = recognize_intent("ist das noch auf lager", PickingContext.AWAITING_COMMAND)
        assert intent.action == "stock_query"

    def test_filter_high_prio(self):
        intent = recognize_intent("zeig mir die dringenden", PickingContext.AWAITING_COMMAND)
        assert intent.action == "filter_high"

    def test_filter_normal_alle_anzeigen(self):
        intent = recognize_intent("alle anzeigen", PickingContext.AWAITING_COMMAND)
        assert intent.action == "filter_normal"

    def test_status_was_steht_an(self):
        intent = recognize_intent("was steht an", PickingContext.AWAITING_COMMAND)
        assert intent.action == "status"

    def test_status_was_ist_offen(self):
        intent = recognize_intent("was ist offen", PickingContext.AWAITING_COMMAND)
        assert intent.action == "status"

    def test_photo_mach_foto(self):
        intent = recognize_intent("mach ein foto", PickingContext.AWAITING_COMMAND)
        assert intent.action == "photo"

    def test_help_befehle(self):
        intent = recognize_intent("welche befehle gibt es", PickingContext.AWAITING_COMMAND)
        assert intent.action == "help"
