import os
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infrastructure" / "scripts" / "reconcile-odoo-lego.py"
FIXTURE = ROOT / "infrastructure" / "fixtures" / "lego-catalog-o19.json"


@unittest.skipUnless(
    os.environ.get("RUN_ODOO_RECONCILE_LIVE_TESTS") == "1",
    "set RUN_ODOO_RECONCILE_LIVE_TESTS=1 for read-only Docker/Odoo coverage",
)
class OdooReconciliationDryRunTests(unittest.TestCase):
    @staticmethod
    def expected_relevant_fk_count(output):
        preflight = re.search(
            r"nonlego_pickings=(\d+).*?nonlego_moves=(\d+) "
            r"move_lines=(\d+) quants=(\d+)",
            output,
        )
        plan = re.search(r"plan delete_products=(\d+)", output)
        if preflight is None or plan is None:
            raise AssertionError("dry-run output is missing deletion-target counts")
        has_delete_targets = any(
            int(count) for count in (*preflight.groups(), plan.group(1))
        )
        return 70 if has_delete_targets else 0

    def compose(self, *args, input_bytes=None):
        return subprocess.run(
            ["docker", "compose", *args],
            cwd=ROOT,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def database_state(self, database):
        result = self.compose(
            "exec", "-T", "db", "psql", "-U", "odoo", "-d", database,
            "-At", "-c",
            "BEGIN READ ONLY; SELECT count(*) FROM product_product; "
            "SELECT count(*) FROM product_template; "
            "SELECT count(*) FROM stock_move; ROLLBACK;",
        )
        self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace"))
        return result.stdout

    def test_both_real_odoo_sessions_dry_run_and_leave_database_state_unchanged(self):
        script = SCRIPT.read_bytes()
        for service, database in (
            ("odoo", "masterfischer_o19"),
            ("odoo-lager-2", "lager2_o19"),
        ):
            with self.subTest(database=database):
                copied = self.compose(
                    "cp", str(FIXTURE), f"{service}:/tmp/lego-catalog-o19.json"
                )
                self.assertEqual(
                    copied.returncode, 0, copied.stdout.decode(errors="replace")
                )
                before = self.database_state(database)
                result = self.compose(
                    "exec", "-T", "-e",
                    "RECONCILE_FIXTURE=/tmp/lego-catalog-o19.json",
                    service, "sh", "-lc",
                    f'odoo shell -d {database} --no-http --db_password "$PASSWORD"',
                    input_bytes=script,
                )
                output = result.stdout.decode(errors="replace")
                self.assertEqual(result.returncode, 0, output)
                self.assertIn(f"database={database} mode=dry-run", output)
                self.assertIn("ROLLBACK: dry-run", output)
                expected_fk_count = self.expected_relevant_fk_count(output)
                self.assertIn(f"fk_constraints={expected_fk_count}", output)
                self.assertEqual(self.database_state(database), before)


if __name__ == "__main__":
    unittest.main()
