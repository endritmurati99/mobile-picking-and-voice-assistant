"""Run with backend requirements installed: python infrastructure/scripts/test-confirm-quantity.py."""

import asyncio
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import httpx
from fastapi import FastAPI
from pydantic import ValidationError

from app import dependencies
from app.routers import cluster, pickings


class ConfirmQuantityTests(unittest.TestCase):
    def test_valid_quantities_keep_scan_defaults_and_partial_amounts(self):
        for model in (pickings.ConfirmLineRequest, cluster.ClusterConfirmRequest):
            body = {"picking_id": 1, "move_line_id": 2}
            with self.subTest(model=model.__name__):
                self.assertEqual(model(**body).quantity, 0)
                for quantity in (0, 0.5, 2, 5):
                    self.assertEqual(model(**body, quantity=quantity).quantity, quantity)

    def test_invalid_quantities_are_rejected_by_both_request_models(self):
        for model in (pickings.ConfirmLineRequest, cluster.ClusterConfirmRequest):
            for quantity in (-1, -0.5, float("nan"), float("inf"), float("-inf")):
                with self.subTest(model=model.__name__, quantity=quantity):
                    with self.assertRaises(ValidationError):
                        model(picking_id=1, move_line_id=2, quantity=quantity)

    def test_routes_reject_invalid_quantities_before_booking(self):
        app = FastAPI()
        app.include_router(pickings.router)
        app.include_router(cluster.router)
        # No database or auth connection: a route reaching booking logic fails.
        for dependency in (
            dependencies.get_picking_service,
            dependencies.get_cluster_service,
            dependencies.get_mobile_workflow_service,
            dependencies.get_write_request_context,
        ):
            app.dependency_overrides[dependency] = lambda: None

        async def check():
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                for path in ("/pickings/1/confirm-line", "/cluster/batches/1/confirm-line"):
                    for quantity in (-1, -0.5, "NaN", "Infinity", "-Infinity"):
                        with self.subTest(path=path, quantity=quantity):
                            response = await client.post(path, json={
                                "picking_id": 1, "move_line_id": 2, "quantity": quantity,
                            })
                            self.assertEqual(response.status_code, 422, response.text)
                            self.assertEqual(response.json()["detail"][0]["loc"], ["body", "quantity"])

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
