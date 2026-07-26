"""Validate n8n workflow contracts against backend webhook payloads.

This module holds all verification logic as importable, pure functions.
``infrastructure/scripts/verify-workflows.py`` is a thin CLI wrapper around
``validate_contracts()`` (legacy v1 contract checks, still applied to every
workflow file on disk) and ``verify_v2_workflow()`` (the new v2-generation
invariants, applied per-workflow using the registry's per-file spec).
"""
from __future__ import annotations

import ast
import json
import re
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
    "quality-alert-ai-evaluation.json",
    "shortage-reported.json",
    "voice-exception-query.json",
}
CALLBACK_AUDIT_WORKFLOWS = {
    "error-trigger.json",
    "quality-alert-created.json",
    "shortage-reported.json",
    "voice-exception-query.json",
}
ROLLOUT_WORKFLOWS = CALLBACK_AUDIT_WORKFLOWS
# Endpoints called BY n8n into the backend (not fired via n8n.fire).
N8N_CALLBACK_ENDPOINTS = {
    "POST /api/internal/n8n/quality-assessment",
    "POST /api/internal/n8n/quality-assessment-ai",
    "POST /api/internal/n8n/replenishment-action",
    "POST /api/internal/n8n/quality-assessment-failed",
    "POST /api/internal/n8n/manual-review-activity",
    "POST /api/integration/log",
    "POST /api/obsidian/log",
    # Internal LLM disposition helper: n8n cannot reach Ollama directly (SSRF
    # policy only allows the backend host), so it calls this backend endpoint,
    # which proxies to the local LLM and falls back to llm_ok=False on error.
    "POST /api/internal/llm/quality-disposition",
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
    "/api/internal/n8n/quality-assessment-ai": {"idempotent": True},
    "/api/internal/n8n/replenishment-action": {"idempotent": True},
    "/api/internal/n8n/quality-assessment-failed": {"idempotent": True},
    "/api/internal/n8n/manual-review-activity": {"idempotent": True},
    "/api/integration/log": {"idempotent": False},
    "/api/obsidian/log": {"idempotent": False},
    "/api/internal/llm/quality-disposition": {"idempotent": True},
}
REQUIRED_CALLBACK_BODY_FIELDS = {
    "/api/internal/n8n/quality-assessment": {
        "correlation_id",
        "alert_id",
        "schema_version",
        "execution_id",
        "latency_tracking",
        "ai_disposition",
        "ai_confidence",
        "ai_summary",
    },
    "/api/internal/n8n/quality-assessment-ai": {
        "schema_version",
        "execution_id",
        "latency_tracking",
        "correlation_id",
        "alert_id",
        "category",
        "confidence",
        "reason",
        "model",
    },
    "/api/internal/n8n/replenishment-action": {
        "correlation_id",
        "picking_id",
        "product_id",
        "location_id",
        "recommended_location_id",
        "reason",
        "schema_version",
        "execution_id",
        "latency_tracking",
    },
    "/api/internal/n8n/quality-assessment-failed": {
        "correlation_id",
        "alert_id",
        "failure_reason",
        "schema_version",
        "execution_id",
        "latency_tracking",
    },
    "/api/internal/n8n/manual-review-activity": {
        "correlation_id",
        "picking_id",
        "reason",
        "schema_version",
        "execution_id",
        "latency_tracking",
    },
    "/api/internal/llm/quality-disposition": {
        "correlation_id",
        "alert_id",
        "description",
        "priority",
        "photo_count",
    },
}
CORRELATION_ID_AS_ALERT_ID_RE = re.compile(r"alert_id\s*:\s*\$json\.correlation_id\b")
CORRELATION_ID_AS_PICKING_ID_RE = re.compile(r"picking_id\s*:\s*\$json\.correlation_id\b")
FUNCTION_NODE_JSON_RE = re.compile(r"(?<!\{)\$json\b")
BODY_FIELD_RE_TEMPLATE = r'(?<![A-Za-z0-9_])(?:{field}\s*:|"{field}"\s*:)'
DIRECT_ODOO_URL_RE = re.compile(r"https?://(?:[^/]*odoo[^/]*|localhost:8069|127\.0\.0\.1:8069)", re.IGNORECASE)
LEGACY_LOG_PATH = "/api/obsidian/log"
PRIMARY_LOG_PATH = "/api/integration/log"
LOG_ALIAS_PATHS = {PRIMARY_LOG_PATH, LEGACY_LOG_PATH}


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


def extract_workflow_contracts() -> tuple[list[WorkflowContract], list[str]]:
    workflows: list[WorkflowContract] = []
    errors: list[str] = []

    for file_path in sorted(WORKFLOW_ROOT.glob("*.json")):
        rel_path = file_path.relative_to(ROOT).as_posix()
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(
                f"{rel_path}: JSON-Syntaxfehler: {exc.msg} (line {exc.lineno}, column {exc.colno})"
            )
            continue
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
                file=rel_path,
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

    return workflows, errors


def _body_contains_field(body_json: str | None, field_name: str) -> bool:
    if not body_json:
        return False
    pattern = re.compile(BODY_FIELD_RE_TEMPLATE.format(field=re.escape(field_name)))
    return bool(pattern.search(body_json))


def _is_direct_odoo_writeback(url: Any) -> bool:
    # Callers pass values pulled straight out of parsed JSON (workflow node
    # parameters), which are not guaranteed to be strings even where the
    # common case is -- widen the annotation instead of asserting str so
    # this guard stays meaningful rather than a redundant, always-true check.
    if not isinstance(url, str):
        return False
    return bool(DIRECT_ODOO_URL_RE.search(url))


def validate_callback_http_nodes(workflow: WorkflowContract) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    wf_basename = Path(workflow.file).name
    if wf_basename not in ROLLOUT_WORKFLOWS:
        return errors, warnings

    for node in workflow.http_nodes:
        if _is_direct_odoo_writeback(node.url):
            errors.append(
                f"{workflow.file}: Node '{node.name}' verwendet einen direkten Odoo-Writeback-URL "
                f"('{node.url}') statt der FastAPI-Grenze"
            )

        callback_path = extract_backend_callback_path(node.url)
        if callback_path is None:
            continue
        if callback_path not in CALLBACK_REQUIREMENTS:
            errors.append(
                f"{workflow.file}: Node '{node.name}' ruft nicht freigegebenen Backend-Endpunkt "
                f"'{callback_path}' auf"
            )
            continue

        if callback_path == LEGACY_LOG_PATH:
            errors.append(
                f"{workflow.file}: Node '{node.name}' verwendet den veralteten Produktpfad "
                f"'{LEGACY_LOG_PATH}' statt '{PRIMARY_LOG_PATH}'"
            )

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

        required_fields = REQUIRED_CALLBACK_BODY_FIELDS.get(callback_path, set())
        missing_fields = sorted(
            field_name
            for field_name in required_fields
            if not _body_contains_field(node.body_json, field_name)
        )
        if missing_fields:
            errors.append(
                f"{workflow.file}: Node '{node.name}' sendet an '{callback_path}' ohne Pflichtfelder: "
                f"{', '.join(missing_fields)}"
            )

        if callback_path not in LOG_ALIAS_PATHS and not _body_contains_field(node.body_json, "schema_version"):
            warnings.append(
                f"{workflow.file}: Node '{node.name}' sendet an '{callback_path}' ohne schema_version "
                "und wuerde als Legacy-Producer gelten"
            )

    return errors, warnings


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


def validate_quality_alert_live_path(workflow: WorkflowContract, workflow_data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if Path(workflow.file).name != "quality-alert-created.json":
        return errors

    for node in workflow_data.get("nodes") or []:
        if node.get("name") == "Execute Shadow AI Evaluation":
            errors.append(
                f"{workflow.file}: produktiver Quality-Flow enthaelt noch den Shadow-AI-Node "
                "'Execute Shadow AI Evaluation'"
            )
            break

    return errors


def validate_contracts() -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    backend_contracts = extract_backend_contracts()
    workflows, workflow_parse_errors = extract_workflow_contracts()
    errors.extend(workflow_parse_errors)

    workflow_by_path: dict[str, WorkflowContract] = {}

    for workflow in workflows:
        wf_basename = Path(workflow.file).name
        wf_path = ROOT / workflow.file
        wf_data = json.loads(wf_path.read_text(encoding="utf-8"))

        http_errors, http_warnings = validate_callback_http_nodes(workflow)
        errors.extend(http_errors)
        warnings.extend(http_warnings)
        errors.extend(validate_error_trigger_business_ids(workflow))
        errors.extend(validate_function_nodes(workflow))
        errors.extend(validate_quality_alert_live_path(workflow, wf_data))

        # --- errorWorkflow reference check (change 3) ---
        if wf_basename in NEEDS_ERROR_WORKFLOW:
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
            if (
                "n8n-nodes-base.scheduleTrigger" not in workflow.trigger_types
                and "n8n-nodes-base.executeWorkflowTrigger" not in workflow.trigger_types
            ):
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


# ---------------------------------------------------------------------------
# V2 generation invariants
#
# These are enforced per-workflow, driven by the registry's per-file spec
# (generation="v2"), rather than by the hardcoded workflow-name sets above
# that the legacy v1 checks use. verify_v2_workflow() is a pure function:
# given a parsed workflow dict and its registry spec, it returns the list of
# violation messages (empty means the workflow passes).
# ---------------------------------------------------------------------------

SIGNATURE_GATE_TYPES = {"CUSTOM.pwrSignatureGate", "n8n-nodes-pwr.pwrSignatureGate"}
SIGNED_HTTP_TYPES = {"CUSTOM.pwrSignedHttpRequest", "n8n-nodes-pwr.pwrSignedHttpRequest"}
RESPOND_TO_WEBHOOK_NODE = "Respond to Webhook"
WEBHOOK_TYPE = "n8n-nodes-base.webhook"
HTTP_REQUEST_TYPE = "n8n-nodes-base.httpRequest"
CODE_FIELD_TYPES = {
    "n8n-nodes-base.code",
    "n8n-nodes-base.function",
    "n8n-nodes-base.functionItem",
    "n8n-nodes-base.set",
}
TEMPLATE_SEGMENT_RE = re.compile(r"^\{[A-Za-z_][A-Za-z0-9_]*\}$")
# n8n marks a field as a dynamic expression either by prefixing the whole
# string with "=" or by embedding a "{{ ... }}" expression inside it. A
# statically-verified target must be neither -- if it can vary at runtime,
# this verifier cannot know what it will resolve to, so it must reject it
# rather than silently approve an unresolved value.
UNRESOLVED_EXPRESSION_RE = re.compile(r"\{\{.*\}\}")
EVENT_ID_TOKEN_RE = re.compile(r"event_id", re.IGNORECASE)
ODOO_INSTANCE_TOKEN_RE = re.compile(r"odoo_instance", re.IGNORECASE)
DELIVERY_TOKEN_RE = re.compile(r"delivery_generation|deliverygenerationproperty", re.IGNORECASE)
LEASE_TOKEN_RE = re.compile(r"\blease\b", re.IGNORECASE)
IDEMPOTENCY_TOKEN_RE = re.compile(r"idempotency", re.IGNORECASE)
IMAGE_ANALYSIS_CLAIM_RE = re.compile(r"image_analysis|vision_result|photo_analysis", re.IGNORECASE)
IMAGE_EVIDENCE_RE = re.compile(r"binary|image_base64|image_url|photo_base64|attachment", re.IGNORECASE)
PHOTO_COUNT_TOKEN_RE = re.compile(r"photo_count", re.IGNORECASE)
ARTIFACT_OR_BASE64_TOKEN_RE = re.compile(
    r"\b(?:base64|artifact_data|photo_base64|image_base64|artifact_content)\b", re.IGNORECASE
)
# A long run of base64-alphabet characters is a strong signal of an inlined
# binary/artifact blob living directly in item JSON, even without one of the
# named tokens above.
BASE64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")


def _webhook_node(nodes: list[dict]) -> dict | None:
    return next((node for node in nodes if node.get("type") == WEBHOOK_TYPE), None)


def _gate_node(nodes: list[dict]) -> dict | None:
    return next((node for node in nodes if node.get("type") in SIGNATURE_GATE_TYPES), None)


def _first_output_targets(connections: dict, source_name: str | None, output_index: int = 0) -> list[str]:
    if not source_name:
        return []
    edges = (connections.get(source_name) or {}).get("main") or []
    if output_index >= len(edges) or not edges[output_index]:
        return []
    return [edge.get("node") for edge in edges[output_index] if edge.get("node")]


def _reachable_node_names(connections: dict, start_names: list[str]) -> set[str]:
    """Forward reachability across EVERY connection namespace (main, ai,
    tool, memory, or any other n8n connection type), not just "main". A
    node wired through a non-"main" namespace (e.g. an AI sub-node
    attached via "ai") runs at execution time exactly like a "main"-wired
    node; a reachability check that only looked at "main" would be
    completely blind to it.
    """
    seen: set[str] = set()
    queue = list(start_names)
    while queue:
        name = queue.pop()
        if name in seen or not name:
            continue
        seen.add(name)
        for connection_type_edges in (connections.get(name) or {}).values():
            for output_edges in connection_type_edges or []:
                for edge in output_edges or []:
                    target = edge.get("node")
                    if target and target not in seen:
                        queue.append(target)
    return seen


def _reachable_node_names_main_only(connections: dict, start_names: list[str]) -> set[str]:
    """Forward reachability restricted to the "main" execution namespace --
    the legitimate, visible control-flow path. Used only to diff against
    _reachable_node_names' every-namespace result, to surface any node
    that is reachable ONLY through a non-"main" namespace and therefore
    invisible to the ordinary "first node after X" checks.
    """
    seen: set[str] = set()
    queue = list(start_names)
    while queue:
        name = queue.pop()
        if name in seen or not name:
            continue
        seen.add(name)
        for output_edges in (connections.get(name) or {}).get("main") or []:
            for edge in output_edges or []:
                target = edge.get("node")
                if target and target not in seen:
                    queue.append(target)
    return seen


def _reverse_adjacency(connections: dict) -> dict[str, set[str]]:
    """Reverse adjacency across every connection namespace -- see
    _reachable_node_names for why "main"-only would miss real edges.
    """
    reverse: dict[str, set[str]] = {}
    for source_name, source_edges in connections.items():
        for connection_type_edges in (source_edges or {}).values():
            for output_edges in connection_type_edges or []:
                for edge in output_edges or []:
                    target = edge.get("node")
                    if target:
                        reverse.setdefault(target, set()).add(source_name)
    return reverse


def _backward_reachable_node_names(connections: dict, start_name: str) -> set[str]:
    reverse = _reverse_adjacency(connections)
    seen: set[str] = set()
    queue = [start_name]
    while queue:
        name = queue.pop()
        if name in seen or not name:
            continue
        seen.add(name)
        for source in reverse.get(name) or ():
            if source not in seen:
                queue.append(source)
    return seen


def _extract_host(url: str) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    if "://" not in url:
        return None
    return urlparse(url).hostname


def _is_unresolved_expression(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    return value.startswith("=") or bool(UNRESOLVED_EXPRESSION_RE.search(value))


def _target_matches_template(target_segments: list[str], template_segments: list[str]) -> bool:
    if len(target_segments) != len(template_segments):
        return False
    for target_segment, template_segment in zip(target_segments, template_segments):
        if TEMPLATE_SEGMENT_RE.match(template_segment):
            if not target_segment:
                return False
            continue
        if target_segment != template_segment:
            return False
    return True


def _is_registered_target(target: str, spec: dict[str, Any]) -> bool:
    if target in (spec.get("callback_paths") or []):
        return True
    target_segments = target.split("/")
    for template in spec.get("artifact_path_templates") or []:
        if _target_matches_template(target_segments, template.split("/")):
            return True
    return False


def _is_event_or_callback_target(target: str, spec: dict[str, Any]) -> bool:
    return _is_registered_target(target, spec)


def _node_text_blob(node: dict[str, Any]) -> str:
    """Stringify everything about a node's parameters (including nested
    functionCode / jsonParameters) for cheap substring scanning. Used only
    for coarse, defense-in-depth heuristics -- not a substitute for a real
    data-flow analysis, which JSON-only static verification cannot provide.
    """
    try:
        return json.dumps(node.get("parameters") or {}, default=str)
    except TypeError:
        return str(node.get("parameters") or {})


def _combined_text_blob(nodes_by_name: dict[str, dict], names: set[str]) -> str:
    return "\n".join(_node_text_blob(nodes_by_name[name]) for name in names if name in nodes_by_name)


def verify_v2_workflow(workflow: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    """Verify the v2-generation invariants for a single workflow.

    Enforces: authentication/rawBody on the Webhook trigger; PWR Signature
    Gate being the mandatory first node after the Webhook; the rejection
    output only ever reaching "Respond to Webhook"; the very first node
    reached after the Signature Gate's accepted output must itself be a
    PWR Signed HTTP Request (no model/carrier/Odoo/callback/business node
    may run before acceptance completes); raw httpRequest nodes never being
    used for internal targets (PWR Signed HTTP Request required instead);
    PWR Signed HTTP Request targets being static (non-expression) relative
    paths registered either as an exact callback path or matching a
    registered {field} artifact-path template segment-by-segment; a
    concrete resolved host that is present in allowed_target_hosts; direct
    Odoo targets being rejected; bodyMode=literalUtf8 being restricted to
    test_only=true specs; event/callback nodes referencing event_id,
    odoo_instance, and at least one delivery/lease/idempotency field; a
    Quality workflow never claiming image analysis from photo_count alone;
    Code/Set ("Edit Fields") nodes never embedding artifact or base64
    content directly in item JSON; every node reachable from the Signature
    Gate through ANY connection namespace (main, ai, tool, ...) -- not just
    "main" -- must be on the ordinary main execution path; and every raw
    HTTP Request node's resolved host must be in allowed_target_hosts, with
    no third "unlisted host" case left unrejected.

    KNOWN, ACCEPTED LIMITS (do not mistake this for a data-flow analyzer):
    this module does static JSON/text substring matching, nothing more.
    Two classes of bypass are known and explicitly out of scope until a
    real fix is possible (a JS AST pass over Code-node bodies, or
    verification against a live, executing workflow -- neither exists yet,
    and no v2 workflow exists in the registry until Task 15 lands the
    smoke workflow):
      - Renamed/case-varied field names (e.g. "photoCount" instead of
        "photo_count", or "eventId" instead of "event_id") silently dodge
        every regex-based token check in this module.
      - Content assembled at runtime rather than written as a literal in
        node parameters (e.g. `['art','ifact','_data'].join('')`, or any
        string built from an expression) is invisible to a text scan that
        only ever sees the literal JSON the workflow file contains.
    """
    errors: list[str] = []
    nodes = workflow.get("nodes") or []
    connections = workflow.get("connections") or {}
    file_name = spec.get("file") or workflow.get("name", "<unknown>")
    by_name = {node.get("name"): node for node in nodes}

    webhook = _webhook_node(nodes)
    if webhook is None:
        errors.append(f"{file_name}: v2 workflow has no Webhook trigger")
    else:
        params = webhook.get("parameters") or {}
        if params.get("authentication") != "headerAuth":
            errors.append(
                f"{file_name}: Webhook '{webhook.get('name')}' must use authentication=headerAuth"
            )
        if not (params.get("options") or {}).get("rawBody"):
            errors.append(
                f"{file_name}: Webhook '{webhook.get('name')}' must set options.rawBody=true"
            )

    gate = _gate_node(nodes)
    if gate is None:
        errors.append(f"{file_name}: v2 workflow has no PWR Signature Gate node")
    else:
        if webhook is not None:
            webhook_targets = _first_output_targets(connections, webhook.get("name"))
            if webhook_targets != [gate.get("name")]:
                found = ", ".join(webhook_targets) if webhook_targets else "none"
                errors.append(
                    f"{file_name}: PWR Signature Gate must be first node after Webhook "
                    f"(found: {found})"
                )

        rejected_targets = _first_output_targets(connections, gate.get("name"), output_index=1)
        rejected_reachable = _reachable_node_names(connections, rejected_targets)
        for name in sorted(rejected_reachable):
            if name != RESPOND_TO_WEBHOOK_NODE and by_name.get(name) is not None:
                errors.append(
                    f"{file_name}: rejection path reaches '{name}', only "
                    f"'{RESPOND_TO_WEBHOOK_NODE}' is allowed"
                )

        # Nothing -- no model, carrier, Odoo, callback, or other business
        # node -- may run before acceptance: the very first node reached
        # from the Signature Gate's accepted (verified) output must itself
        # be a PWR Signed HTTP Request. This mirrors the Webhook->Gate check
        # above one hop further down the graph.
        accepted_targets = _first_output_targets(connections, gate.get("name"), output_index=0)
        first_accepted_node = by_name.get(accepted_targets[0]) if accepted_targets else None
        if len(accepted_targets) != 1 or (
            first_accepted_node is None or first_accepted_node.get("type") not in SIGNED_HTTP_TYPES
        ):
            found = ", ".join(accepted_targets) if accepted_targets else "none"
            errors.append(
                f"{file_name}: node(s) '{found}' run before acceptance; the first node "
                "reached from the Signature Gate's accepted output must be a PWR Signed "
                "HTTP Request that returns process=true -- no model, carrier, Odoo, "
                "callback, or other business node may run first"
            )

        # Nothing reachable from the gate may hide behind a non-"main"
        # connection namespace (e.g. an "ai" sub-node wired straight off
        # the gate): diff the every-namespace reachable set against the
        # main-only one to find any such node.
        all_reachable_from_gate = _reachable_node_names(connections, [gate.get("name")])
        main_only_reachable_from_gate = _reachable_node_names_main_only(
            connections, [gate.get("name")]
        )
        hidden_from_gate = sorted(
            name
            for name in (all_reachable_from_gate - main_only_reachable_from_gate)
            if name in by_name
        )
        if hidden_from_gate:
            errors.append(
                f"{file_name}: node(s) {hidden_from_gate} are reachable from the "
                "Signature Gate only through a non-'main' connection namespace "
                "(e.g. 'ai'/'tool'); every node the gate can reach must be on the "
                "ordinary main execution path so it is visible to verification"
            )

    allowed_hosts = set(spec.get("allowed_target_hosts") or [])
    for node in nodes:
        if node.get("type") != HTTP_REQUEST_TYPE:
            continue
        params = node.get("parameters") or {}
        url = params.get("url", "")
        host = _extract_host(url)
        if _is_direct_odoo_writeback(url):
            errors.append(
                f"{file_name}: node '{node.get('name')}' uses a direct Odoo URL ('{url}')"
            )
        elif host and host in allowed_hosts:
            errors.append(
                f"{file_name}: node '{node.get('name')}' uses a raw HTTP Request node for "
                f"internal target '{url}'; use PWR Signed HTTP Request instead"
            )
        else:
            # Every other raw HTTP Request node -- whether its host could
            # not be resolved at all, or resolved to a host that simply
            # isn't in allowed_target_hosts -- must be rejected outright.
            # There is no host a v2 workflow may reach through a raw HTTP
            # Request node that isn't already covered by one of the two
            # branches above.
            errors.append(
                f"{file_name}: node '{node.get('name')}' makes an outbound HTTP request "
                f"to '{url}' whose resolved host is not in allowed_target_hosts "
                f"{sorted(allowed_hosts)}"
            )

    for node in nodes:
        if node.get("type") not in SIGNED_HTTP_TYPES:
            continue
        params = node.get("parameters") or {}
        target = params.get("target", "")
        node_name = node.get("name")
        host = params.get("host")
        target_is_registered = False

        if _is_unresolved_expression(target):
            errors.append(
                f"{file_name}: node '{node_name}' target is a dynamic/unresolved n8n "
                f"expression ('{target}'); a statically-verified target must be a "
                "fixed relative path"
            )
        elif not target.startswith("/"):
            errors.append(
                f"{file_name}: node '{node_name}' target must be a relative path, got '{target}'"
            )
        elif _is_direct_odoo_writeback(target):
            errors.append(
                f"{file_name}: node '{node_name}' target points at Odoo directly ('{target}')"
            )
        elif not _is_registered_target(target, spec):
            errors.append(
                f"{file_name}: node '{node_name}' target '{target}' is not a registered target "
                "(callback path or artifact-path template)"
            )
        else:
            target_is_registered = True

        # A concrete, resolved host is mandatory -- not merely checked when
        # present -- and it must be one of the registry's allowed hosts.
        if _is_unresolved_expression(host) or not host:
            errors.append(
                f"{file_name}: node '{node_name}' has no concrete resolved host; a "
                f"host from allowed_target_hosts {sorted(allowed_hosts)} is required"
            )
        elif host not in allowed_hosts:
            errors.append(
                f"{file_name}: node '{node_name}' resolved host '{host}' is not in "
                f"allowed_target_hosts {sorted(allowed_hosts)}"
            )

        if params.get("bodyMode") == "literalUtf8" and not spec.get("test_only"):
            errors.append(
                f"{file_name}: node '{node_name}' uses bodyMode=literalUtf8 outside a "
                "test_only=true registry entry"
            )

        if target_is_registered and isinstance(target, str) and _is_event_or_callback_target(target, spec):
            backward_names = _backward_reachable_node_names(connections, node_name)
            blob = _node_text_blob(node) + "\n" + _combined_text_blob(by_name, backward_names)
            missing = []
            if not EVENT_ID_TOKEN_RE.search(blob):
                missing.append("event_id")
            if not ODOO_INSTANCE_TOKEN_RE.search(blob):
                missing.append("odoo_instance")
            if not (
                DELIVERY_TOKEN_RE.search(blob)
                or LEASE_TOKEN_RE.search(blob)
                or IDEMPOTENCY_TOKEN_RE.search(blob)
            ):
                missing.append("delivery generation/lease/idempotency")
            if missing:
                errors.append(
                    f"{file_name}: event/callback node '{node_name}' is missing required "
                    f"fields: {', '.join(missing)}"
                )

    # Quality workflows must not claim image analysis from photo_count alone.
    if "quality" in file_name.lower():
        for node in nodes:
            if node.get("type") not in CODE_FIELD_TYPES:
                continue
            blob = _node_text_blob(node)
            if IMAGE_ANALYSIS_CLAIM_RE.search(blob) and PHOTO_COUNT_TOKEN_RE.search(blob):
                if not IMAGE_EVIDENCE_RE.search(blob):
                    errors.append(
                        f"{file_name}: node '{node.get('name')}' claims image analysis "
                        "using only photo_count, without any actual image/binary evidence"
                    )

    # Code/Edit Fields nodes may not place artifact or base64 content
    # directly in item JSON.
    for node in nodes:
        if node.get("type") not in CODE_FIELD_TYPES:
            continue
        blob = _node_text_blob(node)
        if ARTIFACT_OR_BASE64_TOKEN_RE.search(blob) or BASE64_BLOB_RE.search(blob):
            errors.append(
                f"{file_name}: node '{node.get('name')}' ({node.get('type')}) appears to "
                "place artifact or base64 content directly in item JSON"
            )

    return errors
