"""
Tests für PickingService.

Alle Odoo-RPC-Calls werden gemockt — kein laufendes Odoo nötig.
Testet die Business-Logik: Barcode-Validierung, quantity-Schreiben,
all-done-Detection und n8n fire-and-forget.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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


# ── get_open_pickings ────────────────────────────────────────

class TestGetOpenPickings:
    @pytest.mark.asyncio
    async def test_returns_assigned_pickings(self, service, odoo):
        odoo.search_read.return_value = [
            {"id": 1, "name": "WH/INT/00001", "state": "assigned", "move_ids": [10, 11]},
        ]
        odoo.search_read.side_effect = [
            # First call: pickings
            [{"id": 1, "name": "WH/INT/00001", "state": "assigned", "move_ids": [10, 11]}],
            # Second call: moves for picking 1
            [
                {"id": 10, "product_id": [1, "Schraube M8"], "product_uom_qty": 5,
                 "quantity": 5, "location_id": [1, "A-01"], "location_dest_id": [2, "C-01"], "state": "assigned"},
                {"id": 11, "product_id": [2, "Mutter M8"], "product_uom_qty": 10,
                 "quantity": 10, "location_id": [1, "A-02"], "location_dest_id": [2, "C-01"], "state": "assigned"},
            ],
        ]
        result = await service.get_open_pickings()
        assert len(result) == 1
        assert result[0]["name"] == "WH/INT/00001"

    @pytest.mark.asyncio
    async def test_empty_list_when_no_pickings(self, service, odoo):
        odoo.search_read.return_value = []
        result = await service.get_open_pickings()
        assert result == []


# ── get_picking_detail ───────────────────────────────────────

class TestGetPickingDetail:
    @pytest.mark.asyncio
    async def test_returns_error_for_unknown_picking(self, service, odoo):
        odoo.search_read.return_value = []
        result = await service.get_picking_detail(9999)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_enriches_with_move_lines_and_barcodes(self, service, odoo):
        odoo.search_read.side_effect = [
            # Picking
            [{"id": 1, "name": "WH/INT/00001", "state": "assigned",
              "move_ids": [10], "location_id": [1, "Stock"], "location_dest_id": [2, "Out"],
              "partner_id": False, "scheduled_date": False}],
            # Produkt-Barcodes
            [{"id": 5, "barcode": "4006381333931"}],
        ]
        odoo.execute_kw.side_effect = [
            # move_line search
            [20],
            # move_line read
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 10,
              "quantity_done": 0, "location_id": [1, "A-01"], "location_dest_id": [2, "C-01"],
              "lot_id": False}],
        ]
        result = await service.get_picking_detail(1)
        assert result["name"] == "WH/INT/00001"
        assert len(result["move_lines"]) == 1
        assert result["move_lines"][0]["product_barcode"] == "4006381333931"


# ── confirm_pick_line ────────────────────────────────────────

class TestConfirmPickLine:
    @pytest.mark.asyncio
    async def test_returns_error_when_line_not_found(self, service, odoo):
        odoo.execute_kw.return_value = []
        result = await service.confirm_pick_line(1, 99, "4006381333931", 1.0)
        assert result["success"] is False
        assert "nicht gefunden" in result["message"]

    @pytest.mark.asyncio
    async def test_rejects_wrong_barcode(self, service, odoo):
        odoo.execute_kw.return_value = [
            {"id": 20, "product_id": [5, "Schraube M8"], "quantity": 10}
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        result = await service.confirm_pick_line(1, 20, "9999999999999", 1.0)
        assert result["success"] is False
        assert "Falscher Artikel" in result["message"]

    @pytest.mark.asyncio
    async def test_accepts_correct_barcode_and_writes_quantity(self, service, odoo, n8n):
        # Line exists
        odoo.execute_kw.side_effect = [
            # read line
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 10}],
            # search all lines for picking
            [20],
            # read all lines (completion check)
            [{"quantity": 10, "quantity_done": 10}],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)
        # button_validate returns True → picking complete
        odoo.call_method = AsyncMock(return_value=True)

        result = await service.confirm_pick_line(1, 20, "4006381333931", 10.0)
        assert result["success"] is True
        # Verify quantity was written with correct Odoo 18 field name
        odoo.write.assert_called_once_with(
            "stock.move.line", [20], {"quantity": 10.0}
        )

    @pytest.mark.asyncio
    async def test_uses_demand_quantity_when_zero_passed(self, service, odoo, n8n):
        """Wenn quantity=0 übergeben wird, soll die Bedarfsmenge aus Odoo verwendet werden."""
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 5.0}],
            [20],
            [{"quantity": 5.0, "quantity_done": 0}],  # not done yet
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)

        await service.confirm_pick_line(1, 20, "4006381333931", 0)
        # Should use demand quantity 5.0
        odoo.write.assert_called_once_with(
            "stock.move.line", [20], {"quantity": 5.0}
        )

    @pytest.mark.asyncio
    async def test_fires_n8n_webhook_when_picking_complete(self, service, odoo, n8n):
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 3}],
            [20],
            [{"quantity": 3, "quantity_done": 3}],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)
        odoo.call_method = AsyncMock(return_value=True)

        result = await service.confirm_pick_line(1, 20, "4006381333931", 3.0)
        assert result["picking_complete"] is True
        n8n.fire.assert_called_once()
        call_args = n8n.fire.call_args
        assert call_args[0][0] == "pick-confirmed"
        assert call_args[0][1]["picking_id"] == 1

    @pytest.mark.asyncio
    async def test_no_n8n_when_picking_incomplete(self, service, odoo, n8n):
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Schraube M8"], "quantity": 3}],
            [20, 21],  # two lines
            [
                {"quantity": 3, "quantity_done": 3},   # line 20 done
                {"quantity": 5, "quantity_done": 0},   # line 21 not done
            ],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": "4006381333931"}]
        odoo.write = AsyncMock(return_value=True)

        result = await service.confirm_pick_line(1, 20, "4006381333931", 3.0)
        assert result["picking_complete"] is False
        n8n.fire.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_barcode_check_if_no_barcode_in_odoo(self, service, odoo, n8n):
        """Produkte ohne Barcode sollen ohne Scan-Validierung akzeptiert werden."""
        odoo.execute_kw.side_effect = [
            [{"id": 20, "product_id": [5, "Bulk-Ware"], "quantity": 1}],
            [20],
            [{"quantity": 1, "quantity_done": 0}],
        ]
        odoo.search_read.return_value = [{"id": 5, "barcode": False}]
        odoo.write = AsyncMock(return_value=True)

        result = await service.confirm_pick_line(1, 20, "irgendetwas", 1.0)
        assert result["success"] is True
