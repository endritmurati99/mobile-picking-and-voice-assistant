"""
Tests fuer PickingService.

Alle Odoo-RPC-Calls werden gemockt - kein laufendes Odoo noetig.
Testet die Business-Logik: Mapping fuer Listen-/Detailansicht,
Barcode-Validierung, quantity-Schreiben, all-done-Detection und n8n.
"""
from unittest.mock import AsyncMock

import pytest

from app.services.mobile_workflow import PickerIdentity
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
                        "origin": "[324876] LEGO Ente (BOM 324876)",
                        "state": "assigned",
                        "partner_id": [7, "Werk 1"],
                        "scheduled_date": "2026-03-24 08:00:00",
                        "picking_type_id": [4, "My Company: Internal Transfers"],
                        "priority": "1",
                    }
                ]
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
        assert result[0]["voice_instruction_short"] == "A-12. 5 Stueck. Bremsscheibe."
        assert result[0]["kit_name"] == "LEGO Ente"
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
                        "name": "WH/INT/00001",
                        "origin": "[324876] LEGO Ente (BOM 324876)",
                        "state": "assigned",
                        "move_ids": [10],
                        "location_id": [1, "Stock"],
                        "location_dest_id": [2, "Out"],
                        "partner_id": False,
                        "scheduled_date": False,
                        "picking_type_id": [4, "My Company: Internal Transfers"],
                        "priority": "1",
                    }
                ]
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

        assert result["reference_code"] == "WH/INT/00001"
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
        assert result["move_lines"][0]["voice_instruction_short"] == "A-01. 10 Stueck. Schraube M8."
        assert result["route_plan"]["next_move_line_id"] == 20
        assert result["kit_name"] == "LEGO Ente"
        assert result["voice_intro"] == "LEGO Ente. A-01. 10 Stueck. Schraube M8."
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
        odoo.write.assert_called_once_with("stock.move.line", [20], {"quantity": 10.0})

    @pytest.mark.anyio
    async def test_uses_demand_quantity_when_zero_passed(self, service, odoo):
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 5.0}],
            [{"id": 20, "picked": True}],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)

        await service.confirm_pick_line(1, 20, "4006381333931", 0)

        odoo.write.assert_called_once_with("stock.move.line", [20], {"quantity": 5.0})

    @pytest.mark.anyio
    async def test_fires_n8n_webhook_when_picking_complete(self, service, odoo, n8n):
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 3}],
            [{"id": 20, "picked": True}],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)
        odoo.call_method = AsyncMock(return_value=True)

        result = await service.confirm_pick_line(1, 20, "4006381333931", 3.0)

        assert result["picking_complete"] is True
        n8n.fire_event.assert_called_once()
        call_args = n8n.fire_event.call_args
        assert call_args[0][0] == "pick-confirmed"
        assert call_args[0][1]["picking_id"] == 1
        assert call_args[0][1]["completed_by"] == "mobile-picking-assistant"
        assert call_args[0][1]["completed_by_user_id"] is False
        assert call_args[0][1]["completed_by_device_id"] == ""
        assert call_args[1]["picker"]["name"] == "mobile-picking-assistant"
        assert call_args[1]["picking_context"]["move_line_id"] == 20

    @pytest.mark.anyio
    async def test_includes_picker_identity_in_completion_webhook(self, service, odoo, n8n):
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
        n8n.fire_event.assert_called_once()
        payload = n8n.fire_event.call_args[0][1]
        assert payload["completed_by"] == "Mina Muster"
        assert payload["completed_by_user_id"] == 7
        assert payload["completed_by_device_id"] == "device-42"
        assert n8n.fire_event.call_args[1]["picker"]["user_id"] == 7
        assert n8n.fire_event.call_args[1]["device_id"] == "device-42"

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
