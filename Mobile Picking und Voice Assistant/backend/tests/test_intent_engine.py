"""Tests for the deterministic voice intent engine."""

from app.services.intent_engine import (
    EXTERNAL_INTENT_LABELS,
    PickingContext,
    VoiceSurface,
    finalize_external_intent,
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

    def test_negated_ok_and_gut_never_confirm(self):
        # Regression: "nicht ok"/"nicht gut" are NOT in the problem regex, so they
        # used to fall through to the confirm regex and book @ 0.95.
        for text in ("nicht ok", "nicht gut", "nicht bestaetigen", "kein ok"):
            intent = recognize_intent(
                text,
                PickingContext.AWAITING_COMMAND,
                surface=VoiceSurface.DETAIL,
                active_line_present=True,
            )
            assert intent.action not in {"confirm", "confirm_all"}, text

    def test_plain_confirmation_still_confirms(self):
        intent = recognize_intent(
            "ok",
            PickingContext.AWAITING_COMMAND,
            surface=VoiceSurface.DETAIL,
            active_line_present=True,
        )
        assert intent.action == "confirm"

    def test_english_words_do_not_confirm(self):
        # "eine" mis-transcribes to "fine"; English confirm aliases polluted
        # German matching. They must not book.
        for text in ("fine", "yes", "yep"):
            intent = recognize_intent(
                text,
                PickingContext.AWAITING_COMMAND,
                surface=VoiceSurface.DETAIL,
                active_line_present=True,
            )
            assert intent.action != "confirm", text

    def test_query_intents_recognized(self):
        cases = [
            ("was jetzt", "whats_next"),
            ("was muss ich picken", "whats_next"),
            ("wo", "where"),
            ("welches regal", "where"),
            ("wie viele noch", "how_many_left"),
        ]
        for text, expected in cases:
            intent = recognize_intent(
                text,
                PickingContext.AWAITING_COMMAND,
                surface=VoiceSurface.DETAIL,
                remaining_line_count=3,
                active_line_present=True,
            )
            assert intent.action == expected, f"{text} -> {intent.action}"

    def test_query_intents_are_read_only(self):
        # Never a write intent, so they can never book.
        for text in ("was jetzt", "wo", "wie viele noch"):
            intent = recognize_intent(
                text,
                PickingContext.AWAITING_COMMAND,
                surface=VoiceSurface.DETAIL,
                remaining_line_count=3,
                active_line_present=True,
            )
            assert intent.action not in {"confirm", "confirm_all"}, text

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

    def test_done_is_blocked_while_last_line_is_still_active(self):
        intent = recognize_intent(
            "auftrag erledigt",
            PickingContext.AWAITING_COMMAND,
            surface=VoiceSurface.DETAIL,
            remaining_line_count=0,
            active_line_present=True,
        )

        assert intent.action == "confirm_all"

        done_intent = recognize_intent(
            "fertig",
            PickingContext.AWAITING_COMMAND,
            surface=VoiceSurface.DETAIL,
            remaining_line_count=0,
            active_line_present=True,
        )

        assert done_intent.action == "unknown"

    def test_package_and_carton_done_confirm_the_active_line(self):
        for text in ("paket erledigt", "karton erledigt", "position erledigt", "artikel erledigt"):
            intent = recognize_intent(
                text,
                PickingContext.AWAITING_COMMAND,
                surface=VoiceSurface.DETAIL,
                remaining_line_count=2,
                active_line_present=True,
            )

            assert intent.action == "confirm"

    def test_confirm_all_is_context_blocked_outside_active_detail(self):
        list_intent = recognize_intent(
            "komplett",
            PickingContext.AWAITING_COMMAND,
            surface=VoiceSurface.LIST,
            remaining_line_count=0,
            active_line_present=False,
        )
        complete_intent = recognize_intent(
            "auftrag fertig",
            PickingContext.AWAITING_COMMAND,
            surface=VoiceSurface.COMPLETE,
            remaining_line_count=0,
            active_line_present=False,
        )

        assert list_intent.action == "unknown"
        assert complete_intent.action == "unknown"

    def test_next_order_is_distinct_from_next_line(self):
        intent = recognize_intent(
            "naechster auftrag",
            PickingContext.AWAITING_COMMAND,
            surface=VoiceSurface.COMPLETE,
            remaining_line_count=0,
            active_line_present=False,
        )

        assert intent.action == "next_order"

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


class TestFinalizeExternalIntent:
    def _finalize(self, action, confidence, text, **kw):
        params = dict(
            raw_text=text,
            normalized_text=normalize_text(text),
            surface=VoiceSurface.DETAIL,
            remaining_line_count=1,
            active_line_present=True,
        )
        params.update(kw)
        return finalize_external_intent(action, confidence, **params)

    def test_unknown_label_becomes_unknown(self):
        assert self._finalize("teleport", 0.9, "beam mich hoch").action == "unknown"

    def test_write_confidence_is_clamped(self):
        intent = self._finalize("confirm", 0.99, "jawohl bitte")
        assert intent.action == "confirm"
        assert intent.confidence <= 0.85

    def test_non_write_confidence_not_clamped(self):
        intent = self._finalize("next", 0.95, "geh weiter")
        assert intent.action == "next"
        assert intent.confidence == 0.95

    def test_negation_downgrades_llm_confirm(self):
        assert self._finalize("confirm", 0.99, "nicht ok").action == "problem"

    def test_surface_gating_applies(self):
        intent = self._finalize(
            "confirm", 0.99, "jawohl",
            surface=VoiceSurface.LIST, active_line_present=False,
        )
        assert intent.action == "unknown"

    def test_labels_cover_the_engine_actions(self):
        assert "confirm" in EXTERNAL_INTENT_LABELS
        assert "whats_next" in EXTERNAL_INTENT_LABELS
