"""
Regressionstests fuer zwei Fehlerbehandlungsluecken (Audit 2026-08-19).

1. `PickingService.confirm_pick_line`: nach dem Odoo-Schreibvorgang ist die
   Position gebucht. Fliegt danach noch eine Ausnahme heraus, bricht der Router
   die Idempotenz-Reservierung ab -- ein Retry mit demselben Idempotency-Key
   bucht dann ein zweites Mal. Nach dem Schreiben darf deshalb nichts mehr
   werfen; der Grund muss stattdessen im Log stehen.

2. `finalize_external_intent`: der LLM-Zweig ist ein nachgelagerter Fallback.
   Ein Fehler dort darf die Spracherkennung nicht mitreissen, sondern muss als
   `unknown` gemeldet und protokolliert werden.
"""
import logging
from unittest.mock import AsyncMock

import pytest

from app.services import intent_engine
from app.services.intent_engine import (
    VoiceSurface,
    finalize_external_intent,
    normalize_text,
)
from app.services.odoo_client import OdooAPIError
from app.services.picking_service import PickingService


@pytest.fixture
def odoo():
    return AsyncMock()


@pytest.fixture
def n8n():
    return AsyncMock()


@pytest.fixture
def service(odoo, n8n):
    return PickingService(odoo, n8n)


class TestConfirmPickLineAfterWrite:
    @pytest.mark.anyio
    async def test_followup_query_failure_does_not_escape_after_the_booking(
        self, service, odoo, caplog
    ):
        """Die Folgeabfrage nach dem Schreiben faellt aus.

        Frueher flog der Fehler bis in den Router, der daraufhin die
        Idempotenz-Reservierung abbrach -- obwohl die Position in Odoo bereits
        gebucht war. Ein Retry mit demselben Key haette erneut gebucht.
        """
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 3}],
            OdooAPIError("Odoo nicht erreichbar"),
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)

        with caplog.at_level(logging.WARNING):
            result = await service.confirm_pick_line(1, 20, "4006381333931", 3.0)

        odoo.write.assert_called_once_with(
            "stock.move.line", [20], {"quantity": 3.0, "picked": True}
        )
        assert result["success"] is True, "die Position selbst wurde gebucht"
        assert result["picking_complete"] is False
        assert result["message"] != "Bestätigt.", (
            "die Meldung muss den degradierten Fall benennen, sonst legt der "
            "Picker das Geraet weg"
        )
        assert "nicht erreichbar" in caplog.text, (
            f"der Grund muss im Log stehen. Log war: {caplog.text!r}"
        )
        # Kein Abschluss ohne bekannten Zeilenstand. Geprueft wird auf
        # execute_kw, weil der Abschluss seit dem 2026-09-05 darueber laeuft:
        # call_method stellte die Id-Liste voran und die Odoo-Methode
        # (`@api.model`) starb an `int([id])`.
        abschluesse = [
            aufruf
            for aufruf in odoo.execute_kw.await_args_list
            if aufruf.args[1] == "api_complete_and_request_label"
        ]
        assert abschluesse == []

    @pytest.mark.anyio
    async def test_unexpected_validate_failure_does_not_escape_either(
        self, service, odoo, caplog
    ):
        """`button_validate` wirft etwas anderes als OdooAPIError.

        Auch dieser Fall darf den Abbruchpfad nicht mehr ausloesen: die Position
        ist gebucht.
        """
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 3}],
            [{"id": 20, "picked": True}],
            RuntimeError("Verbindung abgerissen"),
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)

        with caplog.at_level(logging.WARNING):
            result = await service.confirm_pick_line(1, 20, "4006381333931", 3.0)

        assert result["success"] is True
        assert result["picking_complete"] is False
        assert result["message"] != "Bestätigt."
        assert "abgerissen" in caplog.text, (
            f"der Grund muss im Log stehen. Log war: {caplog.text!r}"
        )


class TestFinalizeExternalIntentIsGuarded:
    def _finalize(self, action, confidence, text):
        return finalize_external_intent(
            action,
            confidence,
            raw_text=text,
            normalized_text=normalize_text(text),
            surface=VoiceSurface.DETAIL,
            remaining_line_count=1,
            active_line_present=True,
        )

    def test_unusable_confidence_yields_unknown_instead_of_raising(self, caplog):
        """Das Modell liefert Muell statt einer Zahl.

        Vorher riss `float(...)` den ganzen Voice-Request mit; der
        deterministisch erkannte Intent ging dabei verloren.
        """
        with caplog.at_level(logging.WARNING):
            intent = self._finalize("confirm", "sehr sicher", "jawohl bitte")

        assert intent.action == "unknown", (
            "der Aufrufer verwirft `unknown` und behaelt das deterministische "
            "Ergebnis -- genau das ist gewollt"
        )
        assert "confirm" in caplog.text

    def test_failure_inside_the_guards_is_logged_and_contained(
        self, caplog, monkeypatch
    ):
        def boom(*_args, **_kwargs):
            raise RuntimeError("Guard kaputt")

        monkeypatch.setattr(intent_engine, "_resolve_with_context", boom)

        with caplog.at_level(logging.WARNING):
            intent = self._finalize("next", 0.95, "geh weiter")

        assert intent.action == "unknown"
        assert "Guard kaputt" in caplog.text, (
            f"der Grund muss im Log stehen. Log war: {caplog.text!r}"
        )
