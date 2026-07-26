#!/usr/bin/env python3
"""Thin CLI wrapper around infrastructure.scripts.workflow_verifier.

Applies the legacy v1 contract checks (validate_contracts) to every workflow
file on disk, then applies the v2-generation invariants (verify_v2_workflow)
to every workflow the registry marks generation="v2", using the registry as
the sole source of truth for which files exist and what their v2 spec is.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrastructure.scripts.workflow_registry import (  # noqa: E402
    DEFAULT_REGISTRY_PATH,
    load_registry,
)
from infrastructure.scripts.workflow_verifier import (  # noqa: E402
    ROOT,
    validate_contracts,
    verify_v2_workflow,
)


def _v2_spec_dict(workflow_spec) -> dict:
    return {
        "file": workflow_spec.file,
        "generation": workflow_spec.generation,
        "webhook_paths": list(workflow_spec.webhook_paths),
        "callback_paths": list(workflow_spec.callback_paths),
        "allowed_target_hosts": list(workflow_spec.allowed_target_hosts),
        "authentication": workflow_spec.authentication,
        "test_only": workflow_spec.test_only,
    }


def run_v2_checks(registry_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        registry = load_registry(registry_path)
    except (ValueError, OSError) as exc:
        return [f"workflow registry: {exc}"]

    for workflow_spec in registry.workflows:
        if workflow_spec.generation != "v2":
            continue
        workflow_path = ROOT / "n8n" / "workflows" / workflow_spec.file
        try:
            data = json.loads(workflow_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{workflow_spec.file}: could not load workflow: {exc}")
            continue
        errors.extend(verify_v2_workflow(data, _v2_spec_dict(workflow_spec)))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate n8n workflow contracts.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the validation result as JSON.",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help="Path to workflow-registry.json (default: n8n/workflow-registry.json)",
    )
    args = parser.parse_args()

    errors, warnings, summary = validate_contracts()
    v2_errors = run_v2_checks(args.registry)
    errors = [*errors, *v2_errors]
    summary["errors"] = errors
    summary["v2_errors"] = v2_errors

    if args.json:
        print(json.dumps(summary, indent=2))
        return 1 if errors else 0

    if errors:
        print("Workflow validation failed:")
        for error in errors:
            print(f"  [ERROR] {error}")
    else:
        print("Workflow validation passed.")

    for warning in warnings:
        print(f"  [WARN] {warning}")

    print(
        f"Checked {len(summary['workflow_contracts'])} workflow file(s) "
        f"against {len(summary['backend_contracts'])} backend webhook contract(s) "
        f"+ {len(summary['n8n_callback_endpoints'])} n8n callback endpoint(s)."
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
