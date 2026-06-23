"""
Tests fuer ClusterService (Cluster-/Batch-Picking).

Alle Odoo-RPC-Calls werden gemockt - kein laufendes Odoo noetig.
"""
from unittest.mock import AsyncMock

import pytest

from app.services.cluster_service import (
    BOX_PALETTE,
    ClusterService,
    assign_boxes,
    build_cluster_lines,
)


class TestAssignBoxes:
    def test_assigns_one_based_index_by_sorted_picking_id(self):
        result = assign_boxes([30, 10, 20])
        assert result[10]["box_index"] == 1
        assert result[20]["box_index"] == 2
        assert result[30]["box_index"] == 3

    def test_color_is_deterministic_and_from_palette(self):
        a = assign_boxes([10, 20])
        b = assign_boxes([20, 10])
        assert a == b
        assert a[10]["box_color"] in BOX_PALETTE
        assert a[20]["box_color"] in BOX_PALETTE

    def test_more_pickings_than_palette_cycles(self):
        ids = list(range(1, len(BOX_PALETTE) + 2))
        result = assign_boxes(ids)
        first = result[1]["box_color"]
        wrapped = result[len(BOX_PALETTE) + 1]["box_color"]
        assert first == wrapped  # palette cycles


class TestBuildClusterLines:
    def test_merges_tags_and_route_sorts(self):
        lines_by_picking = {
            10: [{"id": 100, "product_name": "A", "location_src": "WH/Stock/Mitte/E2-P5", "picked": False}],
            20: [{"id": 200, "product_name": "B", "location_src": "WH/Stock/Links/E1-P1", "picked": False}],
        }
        box_map = assign_boxes([10, 20])
        result = build_cluster_lines(lines_by_picking, box_map)
        # Links-Zone wird vor Mitte einsortiert (route_optimizer)
        assert [l["id"] for l in result] == [200, 100]
        tagged = {l["id"]: l for l in result}
        assert tagged[200]["box_index"] == box_map[20]["box_index"]
        assert tagged[200]["picking_id"] == 20
        assert tagged[100]["box_color"] == box_map[10]["box_color"]


@pytest.fixture
def odoo():
    return AsyncMock()


@pytest.fixture
def n8n():
    return AsyncMock()


@pytest.fixture
def service(odoo, n8n):
    return ClusterService(odoo, n8n)


class TestSuggestBatches:
    @pytest.mark.anyio
    async def test_groups_assigned_pickings_without_batch_by_zone(self, service, odoo):
        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.picking":
                return [
                    {"id": 1, "name": "WH/OUT/001", "batch_id": False},
                    {"id": 2, "name": "WH/OUT/002", "batch_id": False},
                ]
            if model == "stock.move.line":
                return [
                    {"id": 10, "picking_id": [1, "WH/OUT/001"], "location_id": [5, "WH/Stock/Links/E1-P1"]},
                    {"id": 11, "picking_id": [2, "WH/OUT/002"], "location_id": [6, "WH/Stock/Links/E1-P2"]},
                ]
            raise AssertionError(model)

        odoo.search_read.side_effect = fake_search_read
        result = await service.suggest_batches()
        assert len(result) == 1
        group = result[0]
        assert group["zone"] == "Links"
        assert sorted(group["picking_ids"]) == [1, 2]
        assert group["order_count"] == 2
        assert group["line_count"] == 2

    @pytest.mark.anyio
    async def test_returns_empty_when_no_open_pickings(self, service, odoo):
        odoo.search_read.return_value = []
        assert await service.suggest_batches() == []


class TestCreateBatch:
    @pytest.mark.anyio
    async def test_creates_batch_with_six_zero_command_and_confirms(self, service, odoo):
        odoo.create.return_value = 99

        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.picking.batch":
                return [{"id": 99, "name": "BATCH/0099", "state": "in_progress",
                         "picking_ids": [1, 2], "user_id": [7, "Max Picker"]}]
            if model == "stock.picking":
                return [{"id": 1, "name": "WH/OUT/001", "company_id": [1, "MyCo"]},
                        {"id": 2, "name": "WH/OUT/002", "company_id": [1, "MyCo"]}]
            if model in ("stock.move.line", "stock.move", "product.product"):
                return []
            raise AssertionError(model)

        odoo.search_read.side_effect = fake_search_read

        from app.services.mobile_workflow import PickerIdentity
        result = await service.create_batch([1, 2], PickerIdentity(user_id=7))

        create_args = odoo.create.call_args
        assert create_args.args[0] == "stock.picking.batch"
        vals = create_args.args[1]
        assert vals["picking_ids"] == [(6, 0, [1, 2])]
        assert vals["user_id"] == 7
        assert vals["company_id"] == 1
        assert "name" not in vals
        odoo.call_method.assert_any_call("stock.picking.batch", "action_confirm", [99])
        assert result["batch_id"] == 99

    @pytest.mark.anyio
    async def test_rejects_empty_picking_ids(self, service):
        with pytest.raises(ValueError):
            await service.create_batch([])


class TestGetBatch:
    @pytest.mark.anyio
    async def test_returns_route_sorted_lines_with_box_tags_and_progress(self, service, odoo):
        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.picking.batch":
                return [{"id": 99, "name": "BATCH/0099", "state": "in_progress",
                         "picking_ids": [1, 2], "user_id": [7, "Max Picker"]}]
            if model == "stock.picking":
                return [{"id": 1, "name": "WH/OUT/001"}, {"id": 2, "name": "WH/OUT/002"}]
            if model == "stock.move.line":
                return [
                    {"id": 100, "picking_id": [1, "WH/OUT/001"], "product_id": [5, "[X] Wal"],
                     "quantity": 0, "move_id": [50, "m"], "location_id": [9, "WH/Stock/Mitte/E2-P5"]},
                    {"id": 200, "picking_id": [2, "WH/OUT/002"], "product_id": [6, "Ente"],
                     "quantity": 0, "move_id": [60, "m"], "location_id": [8, "WH/Stock/Links/E1-P1"]},
                ]
            if model == "stock.move":
                # Mitte (Linie 100) ist erledigt, Links (Linie 200) noch offen
                return [{"id": 50, "product_uom_qty": 2, "picked": True},
                        {"id": 60, "product_uom_qty": 1, "picked": False}]
            if model == "product.product":
                return [{"id": 5, "default_code": "WAL", "barcode": "111", "tracking": "serial"},
                        {"id": 6, "default_code": "ENT", "barcode": "222", "tracking": "none"}]
            raise AssertionError(model)

        odoo.search_read.side_effect = fake_search_read

        result = await service.get_batch(99)
        assert result["batch_id"] == 99
        assert result["state"] == "in_progress"
        ids = [l["id"] for l in result["lines"]]
        assert ids[0] == 200  # Links (offen) vor Mitte
        by_id = {l["id"]: l for l in result["lines"]}
        assert by_id[100]["box_index"] == 1 and by_id[200]["box_index"] == 2
        assert by_id[100]["tracking"] == "serial"
        assert by_id[100]["product_name"] == "Wal"  # [X]-Prefix entfernt
        assert result["progress"]["total"] == 2
        assert result["progress"]["done"] == 1

    @pytest.mark.anyio
    async def test_returns_error_for_unknown_batch(self, service, odoo):
        odoo.search_read.return_value = []
        result = await service.get_batch(123)
        assert result.get("error")

    @pytest.mark.anyio
    async def test_forbidden_for_other_picker(self, service, odoo):
        odoo.search_read.return_value = [
            {"id": 99, "name": "B", "state": "in_progress",
             "picking_ids": [1], "user_id": [7, "Max"]}
        ]
        from app.services.mobile_workflow import PickerIdentity
        result = await service.get_batch(99, PickerIdentity(user_id=8))
        assert result.get("forbidden") is True


class TestConfirmClusterLine:
    @staticmethod
    def _line_reader(line):
        """search_read-Fake: Move-Line nur zurueckgeben, wenn die Batch-Domain matcht."""
        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.move.line":
                return [line]
            return []
        return fake_search_read

    @pytest.mark.anyio
    async def test_writes_quantity_and_picked_without_validate(self, service, odoo):
        line = {"id": 100, "product_id": [5, "Wal"], "quantity": 0,
                "move_id": [50, "m"], "location_id": [9, "L"]}
        odoo.search_read.side_effect = self._line_reader(line)

        await service.confirm_cluster_line(99, 1, 100, scanned_barcode="", quantity=2)

        odoo.write.assert_any_call("stock.move.line", [100], {"quantity": 2})
        odoo.write.assert_any_call("stock.move", [50], {"picked": True})
        # KEIN button_validate
        for call in odoo.call_method.call_args_list:
            assert call.args[1] != "button_validate"

    @pytest.mark.anyio
    async def test_rejects_move_line_outside_batch(self, service, odoo):
        # Scoped search_read matcht nichts -> fremde/ungueltige Position (IDOR-Schutz).
        odoo.search_read.return_value = []
        result = await service.confirm_cluster_line(99, 1, 100, quantity=1)
        assert result["success"] is False
        odoo.write.assert_not_called()

    @pytest.mark.anyio
    async def test_scopes_domain_to_owner_when_picker_known(self, service, odoo):
        # Gate-Paritaet: bei bekanntem Picker enthaelt die Domain den Owner-Filter.
        odoo.search_read.return_value = []
        from app.services.mobile_workflow import PickerIdentity
        await service.confirm_cluster_line(99, 1, 100, quantity=1,
                                           picker_identity=PickerIdentity(user_id=7))
        first_call = odoo.search_read.call_args_list[0]
        domain = first_call.args[1]
        assert ("picking_id.batch_id.user_id", "=", 7) in domain

    @pytest.mark.anyio
    async def test_records_serial_for_tracked_product(self, service, odoo):
        line = {"id": 100, "product_id": [5, "Wal"], "quantity": 0,
                "move_id": [50, "m"], "location_id": [9, "L"]}

        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.move.line":
                return [line]
            if model == "product.product":
                return [{"id": 5, "tracking": "serial", "barcode": "111"}]
            return []

        odoo.search_read.side_effect = fake_search_read

        result = await service.confirm_cluster_line(99, 1, 100, scanned_barcode="111",
                                                    quantity=1, serial_number="SN-1")
        written = [c.args[2] for c in odoo.write.call_args_list if c.args[0] == "stock.move.line"]
        assert any(v.get("lot_name") == "SN-1" for v in written)
        assert result["recorded_serial"] == "SN-1"

    @pytest.mark.anyio
    async def test_rejects_wrong_barcode(self, service, odoo):
        line = {"id": 100, "product_id": [5, "Wal"], "quantity": 0,
                "move_id": [50, "m"], "location_id": [9, "L"]}

        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.move.line":
                return [line]
            if model == "product.product":
                return [{"id": 5, "barcode": "111", "tracking": "none"}]
            return []

        odoo.search_read.side_effect = fake_search_read
        result = await service.confirm_cluster_line(99, 1, 100, scanned_barcode="999", quantity=1)
        assert result["success"] is False
        odoo.write.assert_not_called()


class TestValidateBatch:
    @pytest.mark.anyio
    async def test_calls_action_done_with_backorder_ctx_and_fires_n8n(self, service, odoo, n8n):
        from app.services.n8n_webhook import N8NEventResult
        odoo.search_read.return_value = [{"id": 99, "picking_ids": [1, 2]}]
        odoo.call_method.return_value = True
        n8n.fire_event.return_value = N8NEventResult(delivered=True, error=None, correlation_id="c1")

        from app.services.mobile_workflow import PickerIdentity
        result = await service.validate_batch(99, PickerIdentity(user_id=7))

        done_call = [c for c in odoo.call_method.call_args_list
                     if c.args[:2] == ("stock.picking.batch", "action_done")]
        assert done_call, "action_done must be called"
        assert done_call[0].args[2] == [99]
        assert done_call[0].kwargs["context"]["skip_backorder"] is True
        assert done_call[0].kwargs["context"]["picking_ids_not_to_backorder"] == [1, 2]
        n8n.fire_event.assert_called_once()
        assert result["batch_complete"] is True

    @pytest.mark.anyio
    async def test_reports_pending_when_action_done_returns_wizard(self, service, odoo, n8n):
        odoo.search_read.return_value = [{"id": 99, "picking_ids": [1, 2]}]
        odoo.call_method.return_value = {"res_model": "stock.backorder.confirmation",
                                         "type": "ir.actions.act_window"}
        result = await service.validate_batch(99)
        assert result["success"] is False
        assert result["batch_complete"] is False
        assert result["pending_action"] == "stock.backorder.confirmation"
        n8n.fire_event.assert_not_called()

    @pytest.mark.anyio
    async def test_reports_failure_when_action_done_raises(self, service, odoo, n8n):
        from app.services.odoo_client import OdooAPIError
        odoo.search_read.return_value = [{"id": 99, "picking_ids": [1, 2]}]
        odoo.call_method.side_effect = OdooAPIError("rpc error")
        result = await service.validate_batch(99)
        assert result["success"] is False
        assert result["batch_complete"] is False

    @pytest.mark.anyio
    async def test_rejects_validate_from_other_picker(self, service, odoo, n8n):
        # Batch gehoert Picker 7, Anfrage kommt von Picker 8 -> abgelehnt, kein action_done.
        odoo.search_read.return_value = [{"id": 99, "picking_ids": [1, 2], "user_id": [7, "Max"]}]
        from app.services.mobile_workflow import PickerIdentity
        result = await service.validate_batch(99, PickerIdentity(user_id=8))
        assert result["success"] is False
        assert result["batch_complete"] is False
        odoo.call_method.assert_not_called()
        n8n.fire_event.assert_not_called()
