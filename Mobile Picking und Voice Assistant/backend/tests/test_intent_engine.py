"""Tests for the deterministic voice intent engine."""

from app.services.intent_engine import (
    PickingContext,
    VoiceSurface,
    normalize_text,
    recognize_intent,
)


class TestNormalization:
    def test_maps_umlaut_variants_to_same_normal_form(self):
        assert normalize_text("bestaetigen") == normalize_text("bestatigen")
        assert normalize_text("bestaetigen") == normalize_text("bestatigen")
        assert normalize_text("bestatigen") == "bestatigen"

    def test_maps_sz_and_ss_to_same_normal_form(self):
        assert normalize_text("gruss") == normalize_text("gruß")


class TestIntentRecognition:
    def test_confirm_matches_fuzzy_variants(self):
        for text in ("bestaedige", "bestatige", "bestatje"):
            intent = recognize_intent(
                text,
                PickingContext.AWAITING_COMMAND,
                surface=VoiceSurface.DETAIL,
                active_line_present=True,
            )
            assert intent.action == "confirm"
            assert intent.match_strategy in {"exact", "regex", "fuzzy"}
            assert intent.confidence >= 0.78

    def test_unrelated_words_do_not_match_confirm(self):
        for text in ("basteln", "besen"):
            intent = recognize_intent(
                text,
                PickingContext.AWAITING_COMMAND,
                surface=VoiceSurface.DETAIL,
                active_line_present=True,
            )
            assert intent.action == "unknown"

    def test_negated_confirmations_become_problem(self):
        for text in ("passt nicht", "stimmt nicht", "nicht richtig"):
            intent = recognize_intent(
                text,
                PickingContext.AWAITING_COMMAND,
                surface=VoiceSurface.DETAIL,
                active_line_present=True,
            )
            assert intent.action == "problem"
            assert intent.confidence >= 0.95

    def test_short_confirm_words_only_work_in_detail_with_active_line(self):
        detail_intent = recognize_intent(
            "ja",
            PickingContext.AWAITING_COMMAND,
            surface=VoiceSurface.DETAIL,
            active_line_present=True,
        )
        list_intent = recognize_intent(
            "ja",
            PickingContext.AWAITING_COMMAND,
            surface=VoiceSurface.LIST,
            active_line_present=False,
        )
        assert detail_intent.action == "confirm"
        assert list_intent.action == "unknown"

    def test_fertig_only_becomes_done_when_no_lines_remain(self):
        done_intent = recognize_intent(
            "fertig",
            PickingContext.AWAITING_COMMAND,
            surface=VoiceSurface.COMPLETE,
            remaining_line_count=0,
            active_line_present=False,
        )
        blocked_intent = recognize_intent(
            "fertig",
            PickingContext.AWAITING_COMMAND,
            surface=VoiceSurface.DETAIL,
            remaining_line_count=2,
            active_line_present=True,
        )
        assert done_intent.action == "done"
        assert blocked_intent.action == "unknown"

    def test_quality_alert_surface_only_allows_repeat_or_pause(self):
        intent = recognize_intent(
            "problem",
            PickingContext.AWAITING_COMMAND,
            surface=VoiceSurface.QUALITY_ALERT,
            active_line_present=False,
        )
        assert intent.action == "unknown"

        repeat_intent = recognize_intent(
            "nochmal",
            PickingContext.AWAITING_COMMAND,
            surface=VoiceSurface.QUALITY_ALERT,
            active_line_present=False,
        )
        assert repeat_intent.action == "repeat"

    def test_number_contexts_still_work(self):
        check_intent = recognize_intent(
            "vier sieben",
            PickingContext.AWAITING_LOCATION_CHECK,
        )
        quantity_intent = recognize_intent(
            "funf",
            PickingContext.AWAITING_QUANTITY_CONFIRM,
        )
        assert check_intent.action == "check_digit"
        assert check_intent.value == "4"
        assert quantity_intent.action == "quantity"
        assert quantity_intent.value == "5"

    def test_existing_non_hotpath_intents_still_match(self):
        assert recognize_intent("mach ein foto", PickingContext.AWAITING_COMMAND).action == "photo"
        assert recognize_intent("alle anzeigen", PickingContext.AWAITING_COMMAND).action == "filter_normal"
        assert recognize_intent("was ist offen", PickingContext.AWAITING_COMMAND).action == "status"
