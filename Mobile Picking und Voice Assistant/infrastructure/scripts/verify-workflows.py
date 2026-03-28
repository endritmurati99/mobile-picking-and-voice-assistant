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
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend" / "app"
WORKFLOW_ROOT = ROOT / "n8n" / "workflows"
JSON_REF_RE = re.compile(r"\$json((?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
STANDARD_ENVELOPE_KEYS = {
    "event_name",
    "schema_version",
    "correlation_id",
    "occurred_at",
    "picker",
    "picker.user_id",
    "picker.name",
    "device_id",
    "picking_context",
    "picking_context.picking_id",
    "picking_context.move_line_id",
    "picking_context.product_id",
    "picking_context.location_id",
    "picking_context.priority",
    "picking_context.origin",
    "payload",
}
SYNC_RESPONSE_KEYS = ("status", "tts_text", "source", "correlation_id")
ENVELOPE_REF_PREFIXES = ("payload.", "picker.", "picking_context.")
# Workflows that use an Error Trigger instead of a Webhook and therefore
# do NOT receive the standard app envelope.
ERROR_TRIGGER_WORKFLOWS = {"error-trigger.json"}
# Workflows that MUST define settings.errorWorkflow.
NEEDS_ERROR_WORKFLOW = {
    "quality-alert-created.json",
    "shortage-reported.json",
    "voice-exception-query.json",
}
CALLBACK_AUDIT_WORKFLOWS = {
    "error-trigger.json",
    "quality-alert-created.json",
    "shortage-reported.json",
    "voice-exception-query.json",
}
# Endpoints called BY n8n into the backend (not fired via n8n.fire).
N8N_CALLBACK_ENDPOINTS = {
    "POST /api/internal/n8n/quality-assessment",
    "POST /api/internal/n8n/replenishment-action",
    "POST /api/internal/n8n/quality-assessment-failed",
    "POST /api/internal/n8n/manual-review-activity",
    "POST /api/obsidian/log",
}
ENVELOPE_ROOT_KEYS = {
    "event_name",
    "schema_version",
    "correlation_id",
    "occurred_at",
    "device_id",
    "payload",
    "picker",
    "picking_context",
}
EXPECTED_CALLBACK_SECRET = "={{ $env.N8N_CALLBACK_SECRET }}"
EXPECTED_IDEMPOTENCY_KEY = "={{ $json.correlation_id }}"
CALLBACK_REQUIREMENTS = {
    "/api/internal/n8n/quality-assessment": {"idempotent": True},
    "/api/internal/n8n/replenishment-action": {"idempotent": True},
    "/api/internal/n8n/quality-assessment-failed": {"idempotent": False},
    "/api/internal/n8n/manual-review-activity": {"idempotent": False},
    "/api/obsidian/log": {"idempotent": False},
}
CORRELATION_ID_AS_ALERT_ID_RE = re.compile(r"alert_id\s*:\s*\$json\.correlation_id\b")
CORRELATION_ID_AS_PICKING_ID_RE = re.compile(r"picking_id\s*:\s*\$json\.correlation_id\b")
FUNCTION_NODE_JSON_RE = re.compile(r"(?<!\{)\$json\b")


@dataclass
class BackendContract:
    path: str
    payload_keys: set[str]
    sources: set[str]
    mode: str


@dataclass
class WorkflowContract:
    file: str
    name: str
    webhook_paths: list[str]
    referenced_keys: set[str]
    response_modes: list[str]
    has_response_node: bool
    trigger_types: set[str]
    response_bodies: list[str]
    http_nodes: list["WorkflowHttpNode"]
    function_nodes: list["WorkflowFunctionNode"]


@dataclass
class WorkflowHttpNode:
    name: str
    method: str
    url: str
    headers: dict[str, str]
    body_json: str | None


@dataclass
class WorkflowFunctionNode:
    name: str
    function_code: str


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


def kwarg_dict_keys(node: ast.Call, keyword_name: str) -> set[str]:
    for keyword in node.keywords:
        if keyword.arg == keyword_name:
            return dict_keys(keyword.value) or set()
    return set()


def extract_backend_contracts() -> dict[str, BackendContract]:
    contracts: dict[str, BackendContract] = {}

    for file_path in BACKEND_ROOT.rglob("*.py"):
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        rel_path = file_path.relative_to(ROOT).as_posix()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"fire", "fire_event", "request_reply"}:
                continue
            if len(node.args) < 2:
                continue

            webhook_path = literal_string(node.args[0])
            payload_keys = dict_keys(node.args[1])
            if webhook_path is None or payload_keys is None:
                continue

            contract_keys = set(STANDARD_ENVELOPE_KEYS)
            contract_keys.update({f"payload.{key}" for key in payload_keys})
            contract_keys.update({f"picker.{key}" for key in kwarg_dict_keys(node, "picker")})
            contract_keys.update({f"picking_context.{key}" for key in kwarg_dict_keys(node, "picking_context")})

            contract = contracts.setdefault(
                webhook_path,
                BackendContract(
                    path=webhook_path,
                    payload_keys=set(),
                    sources=set(),
                    mode="sync" if node.func.attr == "request_reply" else "async",
                ),
            )
            contract.payload_keys.update(contract_keys)
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
            refs.add(match.group(1).lstrip("."))
    return refs


def extract_http_headers(params: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    header_params = ((params.get("headerParametersUi") or {}).get("parameter") or [])
    if isinstance(header_params, list):
        for item in header_params:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if isinstance(name, str) and isinstance(value, str):
                headers[name] = value

    header_json = params.get("headerParametersJson")
    if isinstance(header_json, str):
        if "\"X-N8N-Callback-Secret\"" in header_json and "$env.N8N_CALLBACK_SECRET" in header_json:
            headers["X-N8N-Callback-Secret"] = EXPECTED_CALLBACK_SECRET
        if "\"Idempotency-Key\"" in header_json and "$json.correlation_id" in header_json:
            headers["Idempotency-Key"] = EXPECTED_IDEMPOTENCY_KEY
    return headers


def extract_backend_callback_path(url: str) -> str | None:
    if not isinstance(url, str) or not url.startswith("http://backend:8000"):
        return None

    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.netloc != "backend:8000":
        return None
    return parsed.path or None


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
        response_bodies: list[str] = []
        http_nodes: list[WorkflowHttpNode] = []
        function_nodes: list[WorkflowFunctionNode] = []

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
                response_body = params.get("responseBody")
                if isinstance(response_body, str):
                    response_bodies.append(response_body)

            if node_type == "n8n-nodes-base.httpRequest":
                url = params.get("url")
                method = params.get("requestMethod", "GET")
                if isinstance(url, str):
                    http_nodes.append(
                        WorkflowHttpNode(
                            name=node.get("name", "HTTP Request"),
                            method=str(method),
                            url=url,
                            headers=extract_http_headers(params),
                            body_json=params.get("bodyParametersJson")
                            if isinstance(params.get("bodyParametersJson"), str)
                            else None,
                        )
                    )

            if node_type == "n8n-nodes-base.function":
                function_code = params.get("functionCode")
                if isinstance(function_code, str):
                    function_nodes.append(
                        WorkflowFunctionNode(
                            name=node.get("name", "Function"),
                            function_code=function_code,
                        )
                    )

        workflows.append(
            WorkflowContract(
                file=file_path.relative_to(ROOT).as_posix(),
                name=data.get("name", file_path.stem),
                webhook_paths=webhook_paths,
                referenced_keys=referenced_keys,
                response_modes=response_modes,
                has_response_node=has_response_node,
                trigger_types=trigger_types,
                response_bodies=response_bodies,
                http_nodes=http_nodes,
                function_nodes=function_nodes,
            )
        )

    return workflows


def validate_callback_http_nodes(workflow: WorkflowContract) -> list[str]:
    errors: list[str] = []
    wf_basename = Path(workflow.file).name
    if wf_basename not in CALLBACK_AUDIT_WORKFLOWS:
        return errors

    for node in workflow.http_nodes:
        callback_path = extract_backend_callback_path(node.url)
        if callback_path not in CALLBACK_REQUIREMENTS:
            continue

        secret_value = node.headers.get("X-N8N-Callback-Secret")
        if secret_value != EXPECTED_CALLBACK_SECRET:
            errors.append(
                f"{workflow.file}: Node '{node.name}' ruft '{callback_path}' ohne "
                f"korrekten X-N8N-Callback-Secret Header auf"
            )

        if CALLBACK_REQUIREMENTS[callback_path]["idempotent"]:
            idempotency_value = node.headers.get("Idempotency-Key")
            if idempotency_value != EXPECTED_IDEMPOTENCY_KEY:
                errors.append(
                    f"{workflow.file}: Node '{node.name}' ruft '{callback_path}' ohne "
                    f"korrekten Idempotency-Key Header auf"
                )

    return errors


def validate_error_trigger_business_ids(workflow: WorkflowContract) -> list[str]:
    errors: list[str] = []
    if Path(workflow.file).name != "error-trigger.json":
        return errors

    for node in workflow.http_nodes:
        callback_path = extract_backend_callback_path(node.url)
        if not callback_path:
            continue

        body = node.body_json or ""
        if callback_path == "/api/internal/n8n/quality-assessment-failed":
            if CORRELATION_ID_AS_ALERT_ID_RE.search(body):
                errors.append(
                    f"{workflow.file}: Node '{node.name}' missbraucht correlation_id als alert_id"
                )
            if "$json.alert_id" not in body:
                errors.append(
                    f"{workflow.file}: Node '{node.name}' schreibt Quality-Fehler ohne explizite alert_id"
                )

        if callback_path == "/api/internal/n8n/manual-review-activity":
            if CORRELATION_ID_AS_PICKING_ID_RE.search(body):
                errors.append(
                    f"{workflow.file}: Node '{node.name}' missbraucht correlation_id als picking_id"
                )
            if "$json.picking_id" not in body:
                errors.append(
                    f"{workflow.file}: Node '{node.name}' schreibt Manual-Review ohne explizite picking_id"
                )

    return errors


def validate_function_nodes(workflow: WorkflowContract) -> list[str]:
    errors: list[str] = []
    for node in workflow.function_nodes:
        if FUNCTION_NODE_JSON_RE.search(node.function_code):
            errors.append(
                f"{workflow.file}: Function-Node '{node.name}' referenziert '$json' direkt im functionCode; "
                "verwende stattdessen 'items[0]?.json' oder item.json."
            )
    return errors


def validate_contracts() -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    backend_contracts = extract_backend_contracts()
    workflows = extract_workflow_contracts()

    workflow_by_path: dict[str, WorkflowContract] = {}

    for workflow in workflows:
        wf_basename = Path(workflow.file).name

        errors.extend(validate_callback_http_nodes(workflow))
        errors.extend(validate_error_trigger_business_ids(workflow))
        errors.extend(validate_function_nodes(workflow))

        # --- errorWorkflow reference check (change 3) ---
        if wf_basename in NEEDS_ERROR_WORKFLOW:
            wf_path = ROOT / workflow.file
            wf_data = json.loads(wf_path.read_text(encoding="utf-8"))
            wf_settings = wf_data.get("settings") or {}
            if not wf_settings.get("errorWorkflow"):
                warnings.append(
                    f"{workflow.file}: settings.errorWorkflow fehlt – "
                    f"Fehlerfaelle werden nicht an den Error-Trigger weitergeleitet"
                )

        # --- skip envelope validation for error-trigger workflows (change 2) ---
        if wf_basename in ERROR_TRIGGER_WORKFLOWS:
            continue

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

        missing_keys = sorted(
            key
            for key in workflow.referenced_keys
            if _is_envelope_reference(key) and key not in contract.payload_keys
        )
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

        if contract.mode == "sync":
            response_blob = "\n".join(workflow.response_bodies)
            missing_response_keys = [key for key in SYNC_RESPONSE_KEYS if key not in response_blob]
            if missing_response_keys:
                errors.append(
                    f"{workflow.file}: Sync-Workflow '{webhook_path}' antwortet ohne Pflichtfelder: "
                    f"{', '.join(missing_response_keys)}"
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
                "mode": contract.mode,
            }
            for path, contract in sorted(backend_contracts.items())
        },
        "workflow_contracts": {
            workflow.file: {
                "name": workflow.name,
                "webhook_paths": workflow.webhook_paths,
                "referenced_keys": sorted(workflow.referenced_keys),
                "response_modes": workflow.response_modes,
                "response_bodies": workflow.response_bodies,
                "http_nodes": [
                    {
                        "name": node.name,
                        "method": node.method,
                        "url": node.url,
                        "headers": node.headers,
                    }
                    for node in workflow.http_nodes
                ],
            }
            for workflow in workflows
        },
        "n8n_callback_endpoints": sorted(N8N_CALLBACK_ENDPOINTS),
        "errors": errors,
        "warnings": warnings,
    }
    return errors, warnings, summary


def _is_envelope_reference(key: str) -> bool:
    return key in ENVELOPE_ROOT_KEYS or key.startswith(ENVELOPE_REF_PREFIXES)


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
        f"against {len(summary['backend_contracts'])} backend webhook contract(s) "
        f"+ {len(N8N_CALLBACK_ENDPOINTS)} n8n callback endpoint(s)."
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
