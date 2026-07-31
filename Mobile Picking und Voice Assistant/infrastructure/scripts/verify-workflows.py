#!/usr/bin/env python3
"""Thin CLI wrapper around infrastructure.scripts.workflow_verifier.

Applies the legacy v1 contract checks (validate_contracts) to every workflow
file belonging to the registry under verification, then applies the
v2-generation invariants (verify_v2_workflow) to every workflow the registry
marks generation="v2", using the registry as the sole source of truth for
which files exist and what their v2 spec is.

Both halves resolve workflow files relative to --registry, so pointing the
gate at another registry checks that registry's files rather than the repo's.
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
        "artifact_path_templates": list(workflow_spec.artifact_path_templates),
    }


def run_v2_checks(registry_path: Path) -> tuple[list[str], list[str]]:
    """Return (errors, skipped). `skipped` names every workflow that did not
    get the v2 checks applied, and why -- a silent `continue` here reads as
    "covered everything" when it is really "covered everything generation
    == 'v2'", which is exactly the bypass finding #12 describes.
    """
    errors: list[str] = []
    skipped: list[str] = []
    try:
        registry = load_registry(registry_path)
    except (ValueError, OSError) as exc:
        return [f"workflow registry: {exc}"], skipped

    for workflow_spec in registry.workflows:
        if workflow_spec.generation != "v2":
            skipped.append(f"{workflow_spec.file} (generation {workflow_spec.generation})")
            continue
        # Resolved relative to the registry being verified, not to the repo
        # root: verifying registry X while reading workflow files belonging
        # to registry Y is the same vacuous gate as not passing --registry
        # at all. For the default registry (n8n/workflow-registry.json)
        # this is the identical path, which is also how load_registry
        # locates the files for its own registry/disk consistency check.
        workflow_path = registry_path.parent / "workflows" / workflow_spec.file
        try:
            data = json.loads(workflow_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{workflow_spec.file}: could not load workflow: {exc}")
            continue
        errors.extend(verify_v2_workflow(data, _v2_spec_dict(workflow_spec)))

    return errors, skipped


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

    # Both halves of the gate read the workflow files belonging to the
    # registry under verification. The v1 half used to walk the repo's
    # n8n/workflows regardless of --registry, so an alternate registry's v1
    # entries got a contract check against the REPO's same-named bytes -- a
    # gate that reports on files the run would never import.
    workflow_root = args.registry.parent / "workflows"

    errors, warnings, summary = validate_contracts(workflow_root)
    v2_errors, skipped = run_v2_checks(args.registry)
    errors = [*errors, *v2_errors]
    summary["errors"] = errors
    summary["v2_errors"] = v2_errors
    summary["v2_skipped"] = skipped

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

    if skipped:
        print(f"Skipped v2 checks for {len(skipped)} workflow(s) (not generation v2):")
        for entry in skipped:
            print(f"  [SKIP] {entry}")
    else:
        print("No workflows skipped v2 checks.")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
