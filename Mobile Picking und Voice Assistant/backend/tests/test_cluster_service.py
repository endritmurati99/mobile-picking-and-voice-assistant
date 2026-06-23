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
