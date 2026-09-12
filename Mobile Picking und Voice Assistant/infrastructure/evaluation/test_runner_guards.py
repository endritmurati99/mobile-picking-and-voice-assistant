"""Offline guard regressions. No Docker service or application imports needed."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_isolated_evaluation as runner


class RunnerGuards(unittest.TestCase):
    def invoke(self, output, *, source_name="/source-db"):
        metadata = {
            "backend": {"Name": "/source-backend", "Image": "sha256:backend", "Config": {"Image": "backend:latest", "Env": ["ODOO_DB=synthetic"]}},
            "odoo": {"Name": "/source-odoo", "Image": "sha256:odoo", "Config": {"Image": "odoo:latest", "Env": []}},
            "database": {"Name": source_name, "Image": "sha256:db", "Config": {"Image": "db:latest", "Env": ["POSTGRES_USER=synthetic"]}},
        }
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", ["runner", "--output", str(output), "--replace"]))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(runner, "application_tree", return_value="test-tree"))
            stack.enter_context(patch.object(runner, "docker_json", side_effect=lambda label, args: metadata[label.split()[-1]]))
            clear = stack.enter_context(patch.object(runner, "clear_previous"))
            launch = stack.enter_context(patch.object(runner, "launch"))
            for name in ("wait_for", "pipe_clone", "pipe_private_fixtures"):
                stack.enter_context(patch.object(runner, name))
            stack.enter_context(patch.object(runner, "run", return_value=subprocess.CompletedProcess([], 0, b"{}", b"")))
            stack.enter_context(patch.object(runner, "capture_script", return_value=0))
            code = runner.main()
            return code, clear, launch

    def test_array_failure_and_blocked_are_not_success(self):
        for status in ("fail", "failed", "error", "blocked"):
            with self.subTest(status=status):
                self.assertTrue(runner.reported_failure(json.dumps([{"case": "T9", "status": status}], indent=2).encode()))
        self.assertFalse(runner.reported_failure(b'{"case":"T9","status":"pass"}'))

    def test_launches_immutable_source_images(self):
        with tempfile.TemporaryDirectory() as temp:
            code, _, launch = self.invoke(Path(temp) / "new")
        self.assertEqual(code, 0)
        self.assertEqual([c.args[1] for c in launch.call_args_list], ["sha256:db", "sha256:odoo", "sha256:backend"])

    def test_source_alias_is_protected_before_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            code, clear, launch = self.invoke(Path(temp) / "new", source_name="/bachelor-eval-db")
        self.assertEqual(code, 1)
        clear.assert_not_called()
        launch.assert_not_called()

    def test_existing_evidence_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            evidence = output / "environment.json"
            evidence.write_text('{"suite_status":"passed"}', encoding="utf8")
            code, clear, launch = self.invoke(output)
            self.assertEqual(evidence.read_text(encoding="utf8"), '{"suite_status":"passed"}')
        self.assertEqual(code, 1)
        clear.assert_not_called()
        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
