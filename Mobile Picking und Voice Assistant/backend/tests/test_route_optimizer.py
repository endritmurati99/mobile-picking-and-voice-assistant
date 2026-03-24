"""Tests fuer die deterministische Routenheuristik."""
from app.services.route_optimizer import build_route_plan


class TestBuildRoutePlan:
    def test_sorts_remaining_lines_by_zone_and_slot(self):
        move_lines = [
            {
                "id": 3,
                "product_name": "Mutter",
                "location_src": "WH/Stock/Lager Rechts/L-E2-P4",
                "picked": False,
            },
            {
                "id": 1,
                "product_name": "Schraube",
                "location_src": "WH/Stock/Lager Links/L-E1-P1",
                "picked": False,
            },
            {
                "id": 2,
                "product_name": "Bereits gepickt",
                "location_src": "WH/Stock/Lager Links/L-E1-P2",
                "picked": True,
            },
        ]

        result = build_route_plan(move_lines)

        assert result["completed_stops"] == 1
        assert result["remaining_stops"] == 2
        assert result["next_move_line_id"] == 1
        assert [line["id"] for line in result["ordered_move_lines"]] == [1, 3]
        assert result["zone_sequence"] == ["Lager Links", "Lager Rechts"]

    def test_falls_back_for_simple_slot_codes(self):
        move_lines = [
            {"id": 11, "product_name": "B", "location_src": "A-02", "picked": False},
            {"id": 10, "product_name": "A", "location_src": "A-01", "picked": False},
            {"id": 12, "product_name": "C", "location_src": "B-01", "picked": False},
        ]

        result = build_route_plan(move_lines)

        assert [line["id"] for line in result["ordered_move_lines"]] == [10, 11, 12]
        assert result["estimated_travel_steps"] >= 1
