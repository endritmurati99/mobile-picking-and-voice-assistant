import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "populate-odoo-demo-orders.py"


class PopulateDemoOrdersTests(unittest.TestCase):
    def test_plan_adds_only_the_missing_orders_and_caps_cluster_at_eight(self):
        spec = importlib.util.spec_from_file_location("populate_demo_orders", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertEqual(module.population_plan(12, 120, list(range(20))), (108, list(range(8))))
        self.assertEqual(module.population_plan(12, 120, list(range(20, 0, -1))), (108, list(range(13, 21))))
        self.assertEqual(module.population_plan(120, 120, list(range(20))), (0, list(range(8))))
        self.assertEqual(module.population_plan(130, 120, [1]), (0, []))


if __name__ == "__main__":
    unittest.main()
