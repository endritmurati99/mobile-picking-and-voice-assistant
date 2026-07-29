"""Generate the v2 adversarial fixture set. Run: `python _generate.py`.

The reference graph is defined once, here. Every adversarial fixture is a deep
copy of it with EXACTLY ONE mutation applied, so a rejection is attributable to
a single cause. Single-mutation purity is therefore a property of how these
files are produced, not a claim about how carefully they were hand-edited --
and `test_every_fixture_differs_from_the_reference_in_exactly_one_way` counts
the mutations independently, so drift fails the suite even if someone edits a
fixture without re-running this script.

Committed deliberately (fix round 1, finding 2): the fixtures are unreadable as
a diff without the thing that produced them.
"""

import json
from copy import deepcopy
from pathlib import Path

OUT = Path(__file__).resolve().parent

ACCEPT = "/api/internal/n8n/v2/events/accept"
ARTIFACT = "/api/internal/n8n/v2/artifacts/evt-123/status"
CALLBACK = "/api/internal/n8n/v2/callbacks/status"
WEBHOOK_TARGET = "/webhook/pwr-v2-smoke"


def edge(name):
    return {"node": name, "type": "main", "index": 0}


REFERENCE = {
    "name": "PWR v2 Smoke",
    "active": False,
    "nodes": [
        {
            "name": "Webhook",
            "type": "n8n-nodes-base.webhook",
            "parameters": {
                "path": "pwr-v2-smoke",
                "httpMethod": "POST",
                "authentication": "headerAuth",
                "responseMode": "responseNode",
                "options": {"rawBody": True},
            },
        },
        {
            "name": "PWR Signature Gate",
            "type": "CUSTOM.pwrSignatureGate",
            "parameters": {
                "expectedMethod": "POST",
                "expectedTarget": WEBHOOK_TARGET,
            },
        },
        {
            "name": "Build Acceptance Payload",
            "type": "n8n-nodes-base.set",
            "parameters": {
                "mode": "manual",
                "assignments": {
                    "assignments": [
                        {"name": "event_id", "type": "string", "value": "={{ $json.event_id }}"},
                        {"name": "odoo_instance", "type": "string", "value": "={{ $json.odoo_instance }}"},
                        {"name": "idempotency_key", "type": "string", "value": "={{ $json.idempotency_key }}"},
                        {"name": "delivery_generation", "type": "number", "value": "={{ $json.delivery_generation }}"},
                    ]
                },
            },
        },
        {
            "name": "Acceptance",
            "type": "CUSTOM.pwrSignedHttpRequest",
            "parameters": {
                "target": ACCEPT,
                "host": "backend",
                "eventIdField": "event_id",
                "odooInstanceField": "odoo_instance",
                "idempotencyKeyProperty": "idempotency_key",
            },
        },
        {
            "name": "Process Gate",
            "type": "n8n-nodes-base.if",
            "parameters": {
                "conditions": {
                    "boolean": [
                        {"value1": "={{ $json.process }}", "operation": "equal", "value2": True}
                    ]
                }
            },
        },
        {
            "name": "Publish Artifact",
            "type": "CUSTOM.pwrSignedHttpRequest",
            "parameters": {
                "target": ARTIFACT,
                "host": "backend",
                "eventIdField": "event_id",
                "odooInstanceField": "odoo_instance",
                "idempotencyKeyProperty": "idempotency_key",
            },
        },
        {
            "name": "Status Callback",
            "type": "CUSTOM.pwrSignedHttpRequest",
            "parameters": {
                "target": CALLBACK,
                "host": "backend",
                "eventIdField": "event_id",
                "odooInstanceField": "odoo_instance",
                "deliveryGenerationProperty": "delivery_generation",
            },
        },
        {
            "name": "Respond Accepted",
            "type": "n8n-nodes-base.respondToWebhook",
            "parameters": {"respondWith": "json"},
        },
        {
            "name": "Respond Skipped",
            "type": "n8n-nodes-base.respondToWebhook",
            "parameters": {"respondWith": "json"},
        },
        {
            "name": "Respond to Webhook",
            "type": "n8n-nodes-base.respondToWebhook",
            "parameters": {"respondWith": "json"},
        },
    ],
    "connections": {
        "Webhook": {"main": [[edge("PWR Signature Gate")]]},
        "PWR Signature Gate": {
            "main": [[edge("Build Acceptance Payload")], [edge("Respond to Webhook")]]
        },
        "Build Acceptance Payload": {"main": [[edge("Acceptance")]]},
        "Acceptance": {"main": [[edge("Process Gate")]]},
        "Process Gate": {"main": [[edge("Publish Artifact")], [edge("Respond Skipped")]]},
        "Publish Artifact": {"main": [[edge("Status Callback")]]},
        "Status Callback": {"main": [[edge("Respond Accepted")]]},
    },
}


def artifact_instead_of_acceptance(g):
    """The one signed request after the builder targets the artifact route."""
    g["nodes"][3]["parameters"]["target"] = ARTIFACT


def effect_directly_after_acceptance(g):
    """Acceptance hands straight to an effect; the process gate is bypassed."""
    g["connections"]["Acceptance"]["main"][0] = [edge("Publish Artifact")]


def effect_on_the_false_branch(g):
    """The process gate's FALSE output runs a business effect."""
    g["connections"]["Process Gate"]["main"][1] = [edge("Publish Artifact")]


def sidepath_around_the_process_gate(g):
    """A second inbound edge reaches the effect from before the process gate."""
    g["connections"]["Build Acceptance Payload"]["main"][0].append(edge("Publish Artifact"))


def wrong_gate_target(g):
    g["nodes"][1]["parameters"]["expectedTarget"] = "/webhook/pwr-v2-other"


def spoofed_rejection_node(g):
    """Same NAME on the rejection path, different TYPE."""
    g["nodes"][9]["type"] = "n8n-nodes-base.httpRequest"


def process_gate_bypasses_acceptance(g):
    """The builder reaches the process gate directly, around the acceptance call.

    Every effect stays dominated by the true branch, so obligation 7 is
    satisfied by the letter -- but the gate now decides on items that never
    touched the backend. With an allowlisted Code builder passing the webhook
    body through, `process: true` is attacker-supplied.
    """
    g["connections"]["Build Acceptance Payload"]["main"][0].append(edge("Process Gate"))


def inverted_process_gate_operator(g):
    """The gate fires on process != true -- exactly when the backend said no."""
    g["nodes"][4]["parameters"]["conditions"]["boolean"][0]["operation"] = "notEqual"


MUTATIONS = {
    "artifact_instead_of_acceptance.json": artifact_instead_of_acceptance,
    "effect_directly_after_acceptance.json": effect_directly_after_acceptance,
    "effect_on_the_false_branch.json": effect_on_the_false_branch,
    "sidepath_around_the_process_gate.json": sidepath_around_the_process_gate,
    "wrong_gate_target.json": wrong_gate_target,
    "spoofed_rejection_node.json": spoofed_rejection_node,
    "process_gate_bypasses_acceptance.json": process_gate_bypasses_acceptance,
    "inverted_process_gate_operator.json": inverted_process_gate_operator,
}


def write(name, data):
    (OUT / name).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main():
    write("task15_reference_graph.json", REFERENCE)
    for name, mutate in MUTATIONS.items():
        graph = deepcopy(REFERENCE)
        mutate(graph)
        assert graph != REFERENCE, name
        write(name, graph)
    print(f"wrote {1 + len(MUTATIONS)} fixtures to {OUT}")


if __name__ == "__main__":
    main()
