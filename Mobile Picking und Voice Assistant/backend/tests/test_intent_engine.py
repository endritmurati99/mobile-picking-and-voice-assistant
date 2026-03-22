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
