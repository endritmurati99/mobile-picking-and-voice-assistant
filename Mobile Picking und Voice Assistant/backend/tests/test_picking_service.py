"""
Tests fuer PickingService.

Alle Odoo-RPC-Calls werden gemockt - kein laufendes Odoo noetig.
Testet die Business-Logik: Mapping fuer Listen-/Detailansicht,
Barcode-Validierung, quantity-Schreiben, all-done-Detection und n8n.
"""
import json
import logging
from unittest.mock import AsyncMock

import pytest

from app.services.mobile_workflow import PickerIdentity
from app.services.n8n_webhook import N8NEventResult
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


class TestGetOpenPickings:
    @pytest.mark.anyio
    async def test_returns_assigned_pickings_with_operational_preview(self, service, odoo):
        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.picking":
                return [
                    {
                        "id": 1,
                        "name": "WH/INT/00001",
                        "origin": "SO-DEMO-001",
                        "state": "assigned",
                        "partner_id": [7, "ACME Demo GmbH"],
                        "scheduled_date": "2026-03-24 08:00:00",
                        "picking_type_id": [4, "My Company: Internal Transfers"],
                        "priority": "1",
                    }
                ]
            if model == "res.partner":
                return [{
                    "id": 7,
                    "name": "ACME Demo GmbH",
                    "street": "Musterstrasse 12",
                    "street2": "",
                    "zip": "48149",
                    "city": "Muenster",
                    "country_id": [49, "Deutschland"],
                    "email": "logistik@acme-demo.example",
                    "phone": "+49 251 000001",
                }]
            if model == "stock.move":
                return [
                    {"id": 10, "product_uom_qty": 5, "picked": False},
                    {"id": 11, "product_uom_qty": 3, "picked": False},
                ]
            if model == "product.product":
                return [
                    {"id": 5, "default_code": "BS-100"},
                    {"id": 6, "default_code": "SC-200"},
                ]
            raise AssertionError(f"Unexpected search_read model {model}")

        odoo.search_read.side_effect = fake_search_read
        odoo.execute_kw.return_value = [
            {
                "id": 20,
                "picking_id": [1, "WH/INT/00001"],
                "product_id": [5, "[ABC] Bremsscheibe"],
                "quantity": 0,
                "move_id": [10, "MOVE/10"],
                "location_id": [1, "WH/Stock/Halle A/A-12"],
            },
            {
                "id": 21,
                "picking_id": [1, "WH/INT/00001"],
                "product_id": [6, "Schraube"],
                "quantity": 0,
                "move_id": [11, "MOVE/11"],
                "location_id": [1, "WH/Stock/Halle B/B-03"],
            },
        ]

        result = await service.get_open_pickings()

        assert len(result) == 1
        assert result[0]["reference_code"] == "WH/INT/00001"
        assert result[0]["primary_item_display"] == "5x Bremsscheibe"
        assert result[0]["primary_item_sku"] == "BS-100"
        assert result[0]["next_location_short"] == "A-12"
        assert result[0]["open_line_count"] == 2
        assert result[0]["total_line_count"] == 2
        assert result[0]["completed_line_count"] == 0
        assert result[0]["progress_ratio"] == 0.0
        assert result[0]["primary_zone_key"] == "halle-a"
        assert result[0]["voice_instruction_short"] == "A-12. 5 Stück. Bremsscheibe."
        assert result[0]["customer_name"] == "ACME Demo GmbH"
        assert result[0]["shipping_address"]["city"] == "Muenster"
        assert result[0]["customer_reference"] == "SO-DEMO-001"
        assert result[0]["delivery_date"] == "2026-03-24"
        assert result[0]["has_human_context"] is True

    @pytest.mark.anyio
    async def test_falls_back_to_picking_type_when_no_open_lines_exist(self, service, odoo):
        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.picking":
                return [
                    {
                        "id": 1,
                        "name": "WH/INT/00001",
                        "origin": False,
                        "state": "assigned",
                        "partner_id": False,
                        "scheduled_date": False,
                        "picking_type_id": [4, "My Company: Internal Transfers"],
                        "priority": "0",
                    }
                ]
            if model == "product.product":
                return []
            raise AssertionError(f"Unexpected search_read model {model}")

        odoo.search_read.side_effect = fake_search_read
        odoo.execute_kw.return_value = []

        result = await service.get_open_pickings()

        assert result[0]["primary_item_display"] == "Internal Transfers"
        assert result[0]["reference_code"] == "WH/INT/00001"
        assert result[0]["open_line_count"] == 0
        assert result[0]["total_line_count"] == 0
        assert result[0]["completed_line_count"] == 0
        assert result[0]["progress_ratio"] == 0.0
        assert result[0]["primary_item_sku"] == ""
        assert result[0]["primary_zone_key"] == ""
        assert result[0]["voice_instruction_short"] == "Internal Transfers."
        assert result[0]["kit_name"] == ""
        assert result[0]["has_human_context"] is False

    @pytest.mark.anyio
    async def test_uses_plain_source_document_as_human_context(self, service, odoo):
        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.picking":
                return [
                    {
                        "id": 1,
                        "name": "WH/INT/00001",
                        "origin": "Papagei Moritz",
                        "state": "assigned",
                        "partner_id": False,
                        "scheduled_date": False,
                        "picking_type_id": [4, "My Company: Internal Transfers"],
                        "priority": "0",
                    }
                ]
            if model == "product.product":
                return []
            raise AssertionError(f"Unexpected search_read model {model}")

        odoo.search_read.side_effect = fake_search_read
        odoo.execute_kw.return_value = []

        result = await service.get_open_pickings()

        assert result[0]["kit_name"] == "Papagei Moritz"
        assert result[0]["has_human_context"] is True

    @pytest.mark.anyio
    async def test_empty_list_when_no_pickings(self, service, odoo):
        odoo.search_read.return_value = []

        result = await service.get_open_pickings()

        assert result == []


class TestGetPickingDetail:
    @pytest.mark.anyio
    async def test_returns_error_for_unknown_picking(self, service, odoo):
        odoo.search_read.return_value = []

        result = await service.get_picking_detail(9999)

        assert "error" in result

    @pytest.mark.anyio
    async def test_enriches_with_move_lines_and_operational_fields(self, service, odoo):
        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.picking":
                return [
                    {
                        "id": 1,
                        "name": "WH/OUT/00001",
                        "origin": "SO-DEMO-001",
                        "state": "assigned",
                        "move_ids": [10],
                        "location_id": [1, "Stock"],
                        "location_dest_id": [2, "Out"],
                        "partner_id": [7, "ACME Demo GmbH"],
                        "scheduled_date": "2026-07-09 08:00:00",
                        "picking_type_id": [4, "My Company: Internal Transfers"],
                        "priority": "1",
                    }
                ]
            if model == "res.partner":
                return [{
                    "id": 7,
                    "name": "ACME Demo GmbH",
                    "street": "Musterstrasse 12",
                    "street2": "",
                    "zip": "48149",
                    "city": "Muenster",
                    "country_id": [49, "Deutschland"],
                    "email": "logistik@acme-demo.example",
                    "phone": "+49 251 000001",
                }]
            if model == "product.product":
                return [{"id": 5, "barcode": "4006381333931", "default_code": "SC-M8"}]
            if model == "stock.move":
                return [{"id": 10, "product_uom_qty": 10, "picked": False}]
            raise AssertionError(f"Unexpected search_read model {model}")

        odoo.search_read.side_effect = fake_search_read
        odoo.execute_kw.return_value = [
            {
                "id": 20,
                "product_id": [5, "[BR-1] Schraube M8"],
                "quantity": 10,
                "move_id": [10, "MOVE/10"],
                "location_id": [1, "WH/Stock/Aisle 1/A-01"],
                "location_dest_id": [2, "C-01"],
                "lot_id": False,
            }
        ]

        result = await service.get_picking_detail(1)

        assert result["reference_code"] == "WH/OUT/00001"
        assert result["customer_name"] == "ACME Demo GmbH"
        assert result["shipping_address"] == {
            "street": "Musterstrasse 12",
            "street2": "",
            "zip": "48149",
            "city": "Muenster",
            "country": "Deutschland",
        }
        assert result["customer_reference"] == "SO-DEMO-001"
        assert result["delivery_date"] == "2026-07-09"
        assert result["primary_item_display"] == "10x Schraube M8"
        assert result["primary_item_sku"] == "SC-M8"
        assert result["next_location_short"] == "A-01"
        assert result["total_line_count"] == 1
        assert result["completed_line_count"] == 0
        assert result["progress_ratio"] == 0.0
        assert result["primary_zone_key"] == "aisle-1"
        assert result["move_lines"][0]["product_barcode"] == "4006381333931"
        assert result["move_lines"][0]["product_short_name"] == "Schraube M8"
        assert result["move_lines"][0]["product_sku"] == "SC-M8"
        assert result["move_lines"][0]["location_src_id"] == 1
        assert result["move_lines"][0]["location_src_short"] == "A-01"
        assert result["move_lines"][0]["location_src_zone"] == "Aisle 1"
        assert result["move_lines"][0]["ui_display"] == "Schraube M8"
        assert result["move_lines"][0]["voice_instruction_short"] == "A-01. 10 Stück. Schraube M8."
        assert result["route_plan"]["next_move_line_id"] == 20
        assert result["kit_name"] == "SO-DEMO-001"
        assert result["voice_intro"] == "SO-DEMO-001. A-01. 10 Stück. Schraube M8."
        assert result["has_human_context"] is True

    @pytest.mark.anyio
    async def test_filters_picked_lines_out_of_active_route(self, service, odoo):
        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.picking":
                return [
                    {
                        "id": 1,
                        "name": "WH/INT/00001",
                        "state": "assigned",
                        "move_ids": [10, 11],
                        "location_id": [1, "Stock"],
                        "location_dest_id": [2, "Out"],
                        "partner_id": False,
                        "scheduled_date": False,
                        "picking_type_id": [4, "My Company: Internal Transfers"],
                        "priority": "1",
                    }
                ]
            if model == "product.product":
                return [
                    {"id": 5, "barcode": "4006381333931", "default_code": "OLD-1"},
                    {"id": 6, "barcode": "9780201379624", "default_code": "OFF-2"},
                ]
            if model == "stock.move":
                return [
                    {"id": 10, "product_uom_qty": 1, "picked": True},
                    {"id": 11, "product_uom_qty": 2, "picked": False},
                ]
            raise AssertionError(f"Unexpected search_read model {model}")

        odoo.search_read.side_effect = fake_search_read
        odoo.execute_kw.return_value = [
            {
                "id": 20,
                "product_id": [5, "Bereits gepickt"],
                "quantity": 1,
                "move_id": [10, "MOVE/10"],
                "location_id": [1, "WH/Stock/Lager Links/L-E1-P1"],
                "location_dest_id": [2, "WH/Output"],
                "lot_id": False,
            },
            {
                "id": 21,
                "product_id": [6, "Offen"],
                "quantity": 2,
                "move_id": [11, "MOVE/11"],
                "location_id": [1, "WH/Stock/Lager Rechts/L-E2-P4"],
                "location_dest_id": [2, "WH/Output"],
                "lot_id": False,
            },
        ]

        result = await service.get_picking_detail(1)

        assert [line["id"] for line in result["move_lines"]] == [21]
        assert result["primary_item_display"] == "2x Offen"
        assert result["primary_item_sku"] == "OFF-2"
        assert result["open_line_count"] == 1
        assert result["total_line_count"] == 2
        assert result["completed_line_count"] == 1
        assert result["progress_ratio"] == 0.5
        assert result["primary_zone_key"] == "lager-rechts"
        assert result["route_plan"]["completed_stops"] == 1
        assert result["route_plan"]["remaining_stops"] == 1

    @pytest.mark.anyio
    async def test_detail_without_source_document_has_no_human_context(self, service, odoo):
        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.picking":
                return [
                    {
                        "id": 1,
                        "name": "WH/INT/00001",
                        "origin": False,
                        "state": "assigned",
                        "move_ids": [],
                        "location_id": [1, "Stock"],
                        "location_dest_id": [2, "Out"],
                        "partner_id": False,
                        "scheduled_date": False,
                        "picking_type_id": [4, "My Company: Internal Transfers"],
                        "priority": "1",
                    }
                ]
            raise AssertionError(f"Unexpected search_read model {model}")

        odoo.search_read.side_effect = fake_search_read
        odoo.execute_kw.return_value = []

        result = await service.get_picking_detail(1)

        assert result["kit_name"] == ""
        assert result["voice_intro"] == ""
        assert result["has_human_context"] is False


class TestConfirmPickLine:
    @pytest.mark.anyio
    async def test_returns_error_when_line_not_found(self, service, odoo):
        odoo.execute_kw.return_value = []

        result = await service.confirm_pick_line(1, 99, "4006381333931", 1.0)

        assert result["success"] is False
        assert "nicht gefunden" in result["message"]

    @pytest.mark.anyio
    async def test_rejects_move_line_from_other_picking_before_product_read_or_write(
        self, service, odoo
    ):
        # Move-Line 99 exists under picking 2, so the scoped query for picking 1
        # must return no row and stop before any product lookup or mutation.
        odoo.execute_kw.return_value = []

        result = await service.confirm_pick_line(1, 99, "4006381333931", 1.0)

        assert result["success"] is False
        odoo.execute_kw.assert_awaited_once_with(
            "stock.move.line",
            "search_read",
            [[("id", "=", 99), ("picking_id", "=", 1)]],
            {
                "fields": [
                    "id", "product_id", "quantity", "move_id", "location_id", "lot_id",
                ],
                "limit": 1,
            },
        )
        odoo.search_read.assert_not_awaited()
        odoo.write.assert_not_awaited()

    @pytest.mark.anyio
    async def test_rejects_wrong_barcode(self, service, odoo):
        odoo.execute_kw.return_value = [
            {"id": 20, "product_id": [5, "Schraube M8"], "quantity": 10}
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]

        result = await service.confirm_pick_line(1, 20, "9999999999999", 1.0)

        assert result["success"] is False
        assert "Falscher Artikel" in result["message"]

    @pytest.mark.anyio
    async def test_accepts_correct_barcode_and_writes_quantity(self, service, odoo):
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 10}],
            [{"id": 20, "picked": True}],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)
        odoo.call_method = AsyncMock(return_value=True)

        result = await service.confirm_pick_line(1, 20, "4006381333931", 10.0)

        assert result["success"] is True
        odoo.write.assert_called_once_with("stock.move.line", [20], {"quantity": 10.0, "picked": True})

    @pytest.mark.anyio
    async def test_uses_demand_quantity_when_zero_passed(self, service, odoo):
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 5.0}],
            [{"id": 20, "picked": True}],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)

        await service.confirm_pick_line(1, 20, "4006381333931", 0)

        odoo.write.assert_called_once_with("stock.move.line", [20], {"quantity": 5.0, "picked": True})

    @pytest.mark.anyio
    async def test_a_failed_validate_is_reported_and_logged_not_swallowed(
        self, service, odoo, n8n, caplog
    ):
        """Bug 2, "Auftrag wird nach der letzten Position nicht beendet".

        Jede Zeile ist gepickt, `button_validate` schlaegt fehl -- typisch bei
        Mehrzeilen-Auftraegen, wo eine Zeile noch ein Los oder eine
        Seriennummer verlangt. Bisher fing `except OdooAPIError` das ohne eine
        einzige Logzeile ab: der Auftrag blieb in Odoo offen, der Picker las
        "Bestaetigt.", und niemand konnte hinterher sagen, warum. Genau diese
        Kombination -- sichtbar falsch, unsichtbar begruendet -- macht den
        Fehler im Betrieb unauffindbar.

        Der Aufruf darf NICHT scheitern: die Position ist wirklich gebucht.
        Aber `picking_complete` muss falsch sein, die Meldung muss den
        Unterschied benennen, und der Grund muss im Log stehen.
        """
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 3}],
            [{"id": 20, "picked": True}, {"id": 21, "picked": True}],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)
        odoo.call_method = AsyncMock(
            side_effect=OdooAPIError("Sie müssen ein Los für das Produkt angeben.")
        )

        with caplog.at_level(logging.WARNING):
            result = await service.confirm_pick_line(1, 20, "4006381333931", 3.0)

        assert result["success"] is True, "die Position selbst wurde gebucht"
        assert result["picking_complete"] is False
        assert "Bestätigt." != result["message"], (
            "the message must distinguish 'line booked, order still open' from "
            "an ordinary confirmation, or the picker walks away from an open order"
        )
        assert "1" in caplog.text and "Los" in caplog.text, (
            "the reason Odoo refused must reach the log; without it this failure "
            f"is undiagnosable. Log was: {caplog.text!r}"
        )
        # Kein Abschluss-Event fuer einen Auftrag, der nicht abgeschlossen ist.
        n8n.fire_event.assert_not_called()

    @pytest.mark.anyio
    async def test_completion_does_not_call_n8n(self, service, odoo, n8n):
        """Der Abschluss ist eine reine Odoo-Sache.

        Frueher ging von hier der v1-Workflow `pick-confirmed` raus. Den gibt
        es nicht mehr; die Buchung und ihre Meldung haengen an nichts Externem.
        """
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 3}],
            [{"id": 20, "picked": True}],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)
        odoo.call_method = AsyncMock(return_value=True)

        result = await service.confirm_pick_line(
            1,
            20,
            "4006381333931",
            3.0,
            picker_identity=PickerIdentity(
                user_id=7,
                device_id="device-42",
                picker_name="Mina Muster",
            ),
        )

        assert result["picking_complete"] is True
        assert result["message"] == "Auftrag abgeschlossen."
        assert "integration_status" not in result
        n8n.fire_event.assert_not_called()

    @pytest.mark.anyio
    async def test_no_n8n_when_picking_incomplete(self, service, odoo, n8n):
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 3}],
            [{"id": 20, "picked": True}, {"id": 21, "picked": False}],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)

        result = await service.confirm_pick_line(1, 20, "4006381333931", 3.0)

        assert result["picking_complete"] is False
        n8n.fire_event.assert_not_called()


class TestConfirmPickLineSerial:
    @pytest.mark.anyio
    async def test_writes_lot_name_for_serial_tracked_product(self, service, odoo, n8n):
        async def fake_execute_kw(model, method, args, kwargs=None):
            if (model == "stock.move.line" and method == "search_read"
                    and args == [[("id", "=", 50), ("picking_id", "=", 1)]]):
                return [{"id": 50, "product_id": [5, "[CPU] Xeon"], "quantity": 1,
                         "move_id": [10, "MOVE/10"], "location_id": [1, "WH/Stock/A-1"],
                         "lot_id": False}]
            if model == "stock.move.line" and method == "search_read":
                return [{"id": 10, "picked": True}]
            raise AssertionError(f"unexpected execute_kw {model}.{method}")

        async def fake_search_read(model, domain, fields, limit=100):
            if model == "product.product" and "barcode" in fields:
                return [{"barcode": "CPU-XEON-1"}]
            if model == "product.product" and "tracking" in fields:
                return [{"tracking": "serial"}]
            if model == "stock.lot":
                return [{"id": 99, "name": "SN-0001", "product_id": [5, "[CPU] Xeon"]}]
            if model == "stock.quant":
                return [{"quantity": 10, "reserved_quantity": 0, "location_id": [1, "WH/Stock/A-1"]}]
            raise AssertionError(f"unexpected search_read {model} {fields}")

        odoo.execute_kw.side_effect = fake_execute_kw
        odoo.search_read.side_effect = fake_search_read
        odoo.write.return_value = True
        odoo.call_method.return_value = True
        n8n.fire_event.return_value = N8NEventResult(delivered=True, correlation_id="c1", error=None)

        result = await service.confirm_pick_line(
            picking_id=1, move_line_id=50, scanned_barcode="CPU-XEON-1",
            quantity=1, serial_number="SN-0001",
        )

        assert result["success"] is True
        assert result["recorded_serial"] == "SN-0001"
        # Quantity and serial lot are written in a single move-line write (no redundant round-trip).
        odoo.write.assert_any_call("stock.move.line", [50], {"quantity": 1, "picked": True, "lot_id": 99})
        move_line_writes = [
            call for call in odoo.write.call_args_list if call.args[0] == "stock.move.line"
        ]
        assert len(move_line_writes) == 1

    @pytest.mark.anyio
    async def test_skips_barcode_check_if_no_barcode_in_odoo(self, service, odoo):
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Bulk-Ware"], "quantity": 1}],
            [{"id": 20, "picked": True}],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": False}]
        odoo.write = AsyncMock(return_value=True)

        result = await service.confirm_pick_line(1, 20, "irgendetwas", 1.0)

        assert result["success"] is True

    @pytest.mark.anyio
    async def test_does_not_write_lot_name_for_untracked_product(self, service, odoo, n8n):
        async def fake_execute_kw(model, method, args, kwargs=None):
            if (model == "stock.move.line" and method == "search_read"
                    and args == [[("id", "=", 50), ("picking_id", "=", 1)]]):
                return [{"id": 50, "product_id": [5, "[X] Brick"], "quantity": 1,
                         "move_id": [10, "MOVE/10"], "location_id": [1, "WH/Stock/A-1"],
                         "lot_id": False}]
            if model == "stock.move.line" and method == "search_read":
                return [{"id": 10, "picked": True}]
            raise AssertionError(f"unexpected execute_kw {model}.{method}")

        async def fake_search_read(model, domain, fields, limit=100):
            if model == "product.product" and "barcode" in fields:
                return [{"barcode": "BRICK-1"}]
            if model == "product.product" and "tracking" in fields:
                return [{"tracking": "none"}]
            if model == "stock.quant":
                return [{"quantity": 10, "reserved_quantity": 0, "location_id": [1, "WH/Stock/A-1"]}]
            raise AssertionError(f"unexpected search_read {model} {fields}")

        odoo.execute_kw.side_effect = fake_execute_kw
        odoo.search_read.side_effect = fake_search_read
        odoo.write.return_value = True
        odoo.call_method.return_value = True
        n8n.fire_event.return_value = N8NEventResult(delivered=True, correlation_id="c1", error=None)

        result = await service.confirm_pick_line(
            picking_id=1, move_line_id=50, scanned_barcode="BRICK-1",
            quantity=1, serial_number="SN-9",
        )

        assert result["recorded_serial"] == ""
        for call in odoo.write.call_args_list:
            vals = call.args[2] if len(call.args) > 2 else call.kwargs.get("vals", {})
            assert "lot_name" not in vals

    @pytest.mark.anyio
    async def test_whitespace_only_serial_is_rejected_for_serial_product(self, service, odoo, n8n):
        """Serial-tracked products must not be confirmed without a concrete serial."""
        async def fake_execute_kw(model, method, args, kwargs=None):
            if (model == "stock.move.line" and method == "search_read"
                    and args == [[("id", "=", 50), ("picking_id", "=", 1)]]):
                return [{"id": 50, "product_id": [5, "[CPU] Xeon"], "quantity": 1,
                         "move_id": [10, "MOVE/10"], "location_id": [1, "WH/Stock/A-1"],
                         "lot_id": False}]
            if model == "stock.move.line" and method == "search_read":
                return [{"id": 10, "picked": True}]
            raise AssertionError(f"unexpected execute_kw {model}.{method}")

        async def fake_search_read(model, domain, fields, limit=100):
            if model == "product.product" and "barcode" in fields:
                return [{"barcode": "CPU-XEON-1"}]
            if model == "product.product" and "tracking" in fields:
                return [{"tracking": "serial"}]
            if model == "stock.quant":
                return [{"quantity": 10, "reserved_quantity": 0, "location_id": [1, "WH/Stock/A-1"]}]
            raise AssertionError(f"unexpected search_read {model} {fields}")

        odoo.execute_kw.side_effect = fake_execute_kw
        odoo.search_read.side_effect = fake_search_read
        odoo.write.return_value = True
        odoo.call_method.return_value = True
        n8n.fire_event.return_value = N8NEventResult(delivered=True, correlation_id="c1", error=None)

        result = await service.confirm_pick_line(
            picking_id=1, move_line_id=50, scanned_barcode="CPU-XEON-1",
            quantity=1, serial_number="   ",
        )

        assert result["success"] is False
        assert result["serial_required"] is True
        odoo.write.assert_not_called()

    @pytest.mark.anyio
    async def test_rejects_unknown_serial_for_serial_tracked_product(self, service, odoo, n8n):
        async def fake_execute_kw(model, method, args, kwargs=None):
            if (model == "stock.move.line" and method == "search_read"
                    and args == [[("id", "=", 50), ("picking_id", "=", 1)]]):
                return [{"id": 50, "product_id": [5, "[CPU] Xeon"], "quantity": 1,
                         "move_id": [10, "MOVE/10"], "location_id": [1, "WH/Stock/A-1"],
                         "lot_id": False}]
            raise AssertionError(f"unexpected execute_kw {model}.{method}")

        async def fake_search_read(model, domain, fields, limit=100):
            if model == "product.product" and "barcode" in fields:
                return [{"barcode": "CPU-XEON-1"}]
            if model == "product.product" and "tracking" in fields:
                return [{"tracking": "serial"}]
            if model == "stock.quant":
                return [{"quantity": 10, "reserved_quantity": 0, "location_id": [1, "WH/Stock/A-1"]}]
            if model == "stock.lot":
                return []
            raise AssertionError(f"unexpected search_read {model} {fields}")

        odoo.execute_kw.side_effect = fake_execute_kw
        odoo.search_read.side_effect = fake_search_read

        result = await service.confirm_pick_line(
            picking_id=1, move_line_id=50, scanned_barcode="CPU-XEON-1",
            quantity=1, serial_number="SN-MISSING",
        )

        assert result["success"] is False
        assert result["serial_not_found"] is True
        odoo.write.assert_not_called()


class TestReturnSerialReconcile:
    @pytest.mark.anyio
    async def test_reconcile_detects_missing_unknown_and_duplicate_return_serials(self, service, odoo):
        async def fake_execute_kw(model, method, args, kwargs=None):
            assert model == "stock.move.line"
            assert method == "search_read"
            assert args == [[("picking_id", "=", 77)]]
            return [
                {"id": 501, "product_id": [5, "[BRICK] Brick 2x2"], "lot_id": [91, "SN-1"], "lot_name": False},
                {"id": 502, "product_id": [5, "[BRICK] Brick 2x2"], "lot_id": [92, "SN-2"], "lot_name": False},
                {"id": 503, "product_id": [6, "[BULK] Bulk Teil"], "lot_id": False, "lot_name": False},
            ]

        async def fake_search_read(model, domain, fields, limit=100):
            assert model == "product.product"
            assert domain == [("id", "in", [5, 6])]
            return [
                {"id": 5, "tracking": "serial", "display_name": "[BRICK] Brick 2x2", "name": "Brick 2x2"},
                {"id": 6, "tracking": "none", "display_name": "[BULK] Bulk Teil", "name": "Bulk Teil"},
            ]

        odoo.execute_kw.side_effect = fake_execute_kw
        odoo.search_read.side_effect = fake_search_read

        result = await service.reconcile_return_serials(77, ["SN-1", "SN-X", "SN-X"])

        assert result["success"] is True
        assert result["ok"] is False
        assert result["shipped_serials"] == ["SN-1", "SN-2"]
        assert result["returned_serials"] == ["SN-1", "SN-X", "SN-X"]
        assert result["reconcile"] == {
            "ok": False,
            "missing": ["SN-2"],
            "unknown": ["SN-X"],
            "duplicates": ["SN-X"],
        }
        assert result["summary"] == {
            "shipped_count": 2,
            "returned_count": 3,
            "missing_count": 1,
            "unknown_count": 1,
            "duplicate_count": 1,
        }
        assert result["shipped_items"][0]["product_name"] == "Brick 2x2"

    @pytest.mark.anyio
    async def test_reconcile_uses_lot_name_fallback_for_older_serial_writes(self, service, odoo):
        odoo.execute_kw.return_value = [
            {"id": 501, "product_id": [5, "[CPU] Xeon"], "lot_id": False, "lot_name": "SN-LEGACY"}
        ]
        odoo.search_read.return_value = [
            {"id": 5, "tracking": "serial", "display_name": "[CPU] Xeon", "name": "Xeon"}
        ]

        result = await service.reconcile_return_serials(77, [" SN-LEGACY "])

        assert result["success"] is True
        assert result["ok"] is True
        assert result["shipped_serials"] == ["SN-LEGACY"]
        assert result["returned_serials"] == ["SN-LEGACY"]

    @pytest.mark.anyio
    async def test_reconcile_returns_failure_when_picking_has_no_lines(self, service, odoo):
        odoo.execute_kw.return_value = []

        result = await service.reconcile_return_serials(404, ["SN-X"])

        assert result["success"] is False
        assert result["picking_id"] == 404
        assert result["reconcile"] == {
            "ok": False,
            "missing": [],
            "unknown": ["SN-X"],
            "duplicates": [],
        }


class TestRequestReplenishment:
    @pytest.mark.anyio
    async def test_names_the_alternative_location_without_claiming_a_request(self, service, odoo, n8n):
        """Befund statt Versprechen.

        Der v1-Workflow `shortage-reported` ist weg und niemand bucht den
        Nachschub. Eine Meldung "Nachschub angefordert" waere damit eine
        Zusage, der nichts folgt -- der Picker wartet auf Ware, die keiner
        bewegt. Also nennt die Antwort den Alternativplatz und sagt, wer
        weitermachen muss.
        """
        odoo.execute_kw.return_value = [
            {
                "id": 20,
                "product_id": [5, "Schraube M8"],
                "location_id": [9, "WH/Stock/A-01"],
            }
        ]
        odoo.search_read.return_value = [
            {"quantity": 0, "reserved_quantity": 0, "location_id": [9, "WH/Stock/A-01"]},
            {"quantity": 4, "reserved_quantity": 0, "location_id": [12, "WH/Stock/B-01"]},
        ]

        result = await service.request_replenishment(44, 20, reason="Fehlmenge")

        assert result["success"] is True
        assert result["replenishment_triggered"] is False
        assert result["recommended_location_id"] == 12
        assert result["recommended_location"] == "WH/Stock/B-01"
        assert "WH/Stock/B-01" in result["message"]
        assert "angefordert" not in result["message"]
        n8n.fire_event.assert_not_called()

def _serial_confirm_events(caplog) -> list[dict]:
    """Extract structured serial_confirm telemetry events from captured logs."""
    events = []
    for record in caplog.records:
        try:
            payload = json.loads(record.getMessage())
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("event_type") == "serial_confirm":
            events.append(payload)
    return events


class TestConfirmPickLineTelemetry:
    """Every confirm attempt must emit exactly one serial_confirm event, so the
    Design-Science success_rate metric can measure failures (not only successes)."""

    @pytest.mark.anyio
    async def test_emits_failure_event_when_line_not_found(self, service, odoo, caplog):
        odoo.execute_kw.return_value = []

        with caplog.at_level(logging.INFO, logger="app.services.picking_service"):
            result = await service.confirm_pick_line(1, 99, "x", 1.0)

        assert result["success"] is False
        events = _serial_confirm_events(caplog)
        assert len(events) == 1
        assert events[0]["success"] is False
        assert events[0]["serial_recorded"] is False

    @pytest.mark.anyio
    async def test_emits_failure_event_on_wrong_barcode(self, service, odoo, caplog):
        odoo.execute_kw.return_value = [
            {"id": 20, "product_id": [5, "Schraube M8"], "quantity": 10}
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]

        with caplog.at_level(logging.INFO, logger="app.services.picking_service"):
            result = await service.confirm_pick_line(1, 20, "9999999999999", 1.0)

        assert result["success"] is False
        events = _serial_confirm_events(caplog)
        assert len(events) == 1
        assert events[0]["success"] is False

    @pytest.mark.anyio
    async def test_emits_exactly_one_event_on_happy_path(self, service, odoo, n8n, caplog):
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 3, "move_id": [10, "MOVE/10"]}],
            [{"id": 20, "picked": True}],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)
        odoo.call_method = AsyncMock(return_value=True)
        n8n.fire_event = AsyncMock(
            return_value=N8NEventResult(delivered=True, correlation_id="c1", error=None)
        )

        with caplog.at_level(logging.INFO, logger="app.services.picking_service"):
            result = await service.confirm_pick_line(1, 20, "4006381333931", 3.0)

        assert result["success"] is True
        events = _serial_confirm_events(caplog)
        assert len(events) == 1
        assert events[0]["success"] is True

    @pytest.mark.anyio
    async def test_emits_exactly_one_event_on_completion(self, service, odoo, n8n, caplog):
        """Genau EIN Telemetrie-Event pro Confirm -- die Invariante bleibt.

        Frueher pruefte dieser Test den degradierten n8n-Zweig, in dem das
        Event doppelt zu emittieren drohte. Der Zweig ist mit dem v1-Workflow
        weggefallen; die Invariante gilt weiter und wird hier auf dem
        verbliebenen Erfolgspfad festgehalten.
        """
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 3, "move_id": [10, "MOVE/10"]}],
            [{"id": 20, "picked": True}],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)
        odoo.call_method = AsyncMock(return_value=True)

        with caplog.at_level(logging.INFO, logger="app.services.picking_service"):
            result = await service.confirm_pick_line(1, 20, "4006381333931", 3.0)

        assert result["success"] is True
        events = _serial_confirm_events(caplog)
        assert len(events) == 1
        assert events[0]["success"] is True
