#!/usr/bin/env python3
"""Validate n8n workflow contracts against backend webhook payloads."""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend" / "app"
WORKFLOW_ROOT = ROOT / "n8n" / "workflows"
JSON_REF_RE = re.compile(
    r"\$json(?:\.([A-Za-z_][A-Za-z0-9_]*)|\[['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\])"
)


@dataclass
class BackendContract:
    path: str
    payload_keys: set[str]
    sources: set[str]


@dataclass
class WorkflowContract:
    file: str
    name: str
    webhook_paths: list[str]
    referenced_keys: set[str]
    response_modes: list[str]
    has_response_node: bool
    trigger_types: set[str]


def literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def dict_keys(node: ast.AST) -> set[str] | None:
    if not isinstance(node, ast.Dict):
        return None

    keys: set[str] = set()
    for key_node in node.keys:
        if key_node is None:
            return None
        key_value = literal_string(key_node)
        if key_value is None:
            return None
        keys.add(key_value)
    return keys


def extract_backend_contracts() -> dict[str, BackendContract]:
    contracts: dict[str, BackendContract] = {}

    for file_path in BACKEND_ROOT.rglob("*.py"):
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        rel_path = file_path.relative_to(ROOT).as_posix()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "fire":
                continue
            if len(node.args) < 2:
                continue

            webhook_path = literal_string(node.args[0])
            payload_keys = dict_keys(node.args[1])
            if webhook_path is None or payload_keys is None:
                continue

            contract = contracts.setdefault(
                webhook_path,
                BackendContract(path=webhook_path, payload_keys=set(), sources=set()),
            )
            contract.payload_keys.update(payload_keys)
            contract.sources.add(rel_path)

    return contracts


def find_json_refs(value: Any) -> set[str]:
    refs: set[str] = set()

    if isinstance(value, dict):
        for item in value.values():
            refs.update(find_json_refs(item))
        return refs

    if isinstance(value, list):
        for item in value:
            refs.update(find_json_refs(item))
        return refs

    if isinstance(value, str):
        for match in JSON_REF_RE.finditer(value):
            refs.add(match.group(1) or match.group(2))
    return refs


def extract_workflow_contracts() -> list[WorkflowContract]:
    workflows: list[WorkflowContract] = []

    for file_path in sorted(WORKFLOW_ROOT.glob("*.json")):
        data = json.loads(file_path.read_text(encoding="utf-8"))
        nodes = data.get("nodes") or []
        webhook_paths: list[str] = []
        response_modes: list[str] = []
        trigger_types: set[str] = set()
        referenced_keys: set[str] = set()
        has_response_node = False

        for node in nodes:
            node_type = node.get("type", "")
            if node_type:
                trigger_types.add(node_type)

            params = node.get("parameters") or {}
            referenced_keys.update(find_json_refs(params))

            if node_type == "n8n-nodes-base.webhook":
                path = params.get("path")
                if isinstance(path, str) and path:
                    webhook_paths.append(path)
                response_mode = params.get("responseMode")
                if isinstance(response_mode, str) and response_mode:
                    response_modes.append(response_mode)

            if node_type == "n8n-nodes-base.respondToWebhook":
                has_response_node = True

        workflows.append(
            WorkflowContract(
                file=file_path.relative_to(ROOT).as_posix(),
                name=data.get("name", file_path.stem),
                webhook_paths=webhook_paths,
                referenced_keys=referenced_keys,
                response_modes=response_modes,
                has_response_node=has_response_node,
                trigger_types=trigger_types,
            )
        )

    return workflows


def validate_contracts() -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    backend_contracts = extract_backend_contracts()
    workflows = extract_workflow_contracts()

    workflow_by_path: dict[str, WorkflowContract] = {}

    for workflow in workflows:
        if not workflow.webhook_paths:
            if "n8n-nodes-base.scheduleTrigger" not in workflow.trigger_types:
                warnings.append(
                    f"{workflow.file}: kein Webhook- oder Schedule-Trigger erkannt"
                )
            continue

        for webhook_path in workflow.webhook_paths:
            if webhook_path in workflow_by_path:
                errors.append(
                    f"Doppelter Webhook-Pfad '{webhook_path}' in "
                    f"{workflow_by_path[webhook_path].file} und {workflow.file}"
                )
                continue
            workflow_by_path[webhook_path] = workflow

        if "responseNode" in workflow.response_modes and not workflow.has_response_node:
            errors.append(
                f"{workflow.file}: responseMode=responseNode, aber kein RespondToWebhook-Node vorhanden"
            )

    for webhook_path, contract in sorted(backend_contracts.items()):
        workflow = workflow_by_path.get(webhook_path)
        if workflow is None:
            errors.append(
                f"Backend feuert '{webhook_path}', aber kein passender n8n-Workflow-Webhooks gefunden "
                f"(Quellen: {', '.join(sorted(contract.sources))})"
            )
            continue

        missing_keys = sorted(workflow.referenced_keys - contract.payload_keys)
        if missing_keys:
            errors.append(
                f"{workflow.file}: referenziert nicht gelieferte Felder fuer '{webhook_path}': "
                f"{', '.join(missing_keys)} | Backend liefert: {', '.join(sorted(contract.payload_keys))}"
            )

        unused_keys = sorted(contract.payload_keys - workflow.referenced_keys)
        if unused_keys:
            warnings.append(
                f"{workflow.file}: Backend liefert fuer '{webhook_path}' ungenutzte Felder: "
                f"{', '.join(unused_keys)}"
            )

    for webhook_path, workflow in sorted(workflow_by_path.items()):
        if webhook_path not in backend_contracts:
            warnings.append(
                f"{workflow.file}: Webhook-Pfad '{webhook_path}' wird aktuell im Backend nicht ueber n8n.fire(...) verwendet"
            )

    summary = {
        "backend_contracts": {
            path: {
                "payload_keys": sorted(contract.payload_keys),
                "sources": sorted(contract.sources),
            }
            for path, contract in sorted(backend_contracts.items())
        },
        "workflow_contracts": {
            workflow.file: {
                "name": workflow.name,
                "webhook_paths": workflow.webhook_paths,
                "referenced_keys": sorted(workflow.referenced_keys),
                "response_modes": workflow.response_modes,
            }
            for workflow in workflows
        },
        "errors": errors,
        "warnings": warnings,
    }
    return errors, warnings, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate n8n workflow contracts.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the validation result as JSON.",
    )
    args = parser.parse_args()

    errors, warnings, summary = validate_contracts()

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
        f"against {len(summary['backend_contracts'])} backend webhook contract(s)."
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
