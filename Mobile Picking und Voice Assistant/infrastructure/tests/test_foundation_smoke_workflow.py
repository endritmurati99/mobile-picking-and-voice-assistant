"""The Foundation smoke workflow: the FIRST generation-v2 workflow this
repository ships, and the missing n8n half of the lease-token contract.

Two things were dormant before this file existed, and both are what these
tests exist to keep closed:

 1. Every entry in `n8n/workflow-registry.json` was `generation: "v1"`, so
    `verify-workflows.py` exited 0 while `verify_v2_workflow` had never once
    been applied to a real, committed workflow. A gate that has only ever run
    against fixtures is a gate nobody has watched work.
 2. After finding #5b the artifact route carries the `processing_lease_token`
    as a signed path segment, and NO workflow or node anywhere in this
    repository built that URL -- `grep -rn "leases/" n8n/ infrastructure/`
    returned nothing at all.

The reject-then-accept tests below are the point of the file. Each one mutates
the committed workflow in exactly one place, asserts the verifier rejects it
WITH THE RIGHT CAUSE, and the unmutated document is re-verified clean in
`test_the_committed_workflow_verifies_clean` -- so a mutation that happened to
be rejected for an unrelated reason cannot pass as evidence.
"""
import importlib.util
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

from infrastructure.scripts.workflow_registry import load_registry
from infrastructure.scripts.workflow_verifier import verify_v2_workflow

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "n8n" / "workflow-registry.json"
WORKFLOW_FILE = "pwr-foundation-smoke-v2.json"
WORKFLOW_PATH = ROOT / "n8n" / "workflows" / WORKFLOW_FILE
ROUTER_SOURCE = ROOT / "backend" / "app" / "routers" / "n8n_v2.py"

ARTIFACT_NODE = "PWR Signed Artifact"
ACCEPTANCE_NODE = "PWR Signed Acceptance"


def _verify_workflows_module():
    """Import the CLI runner despite its hyphenated file name.

    The spec these tests verify against is built by the SAME `_v2_spec_dict`
    the production gate uses. Hand-rolling an equivalent dict here would mean
    that a field the runner stops passing (or starts passing differently)
    leaves this suite green while the real gate goes blind -- exactly the
    class of drift this programme keeps finding.
    """
    path = ROOT / "infrastructure" / "scripts" / "verify-workflows.py"
    spec = importlib.util.spec_from_file_location("pwr_verify_workflows_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY_CLI = _verify_workflows_module()


def _registry_spec():
    registry = load_registry(REGISTRY_PATH)
    return VERIFY_CLI._v2_spec_dict(registry.by_file(WORKFLOW_FILE))


def _workflow():
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _node(workflow, name):
    for node in workflow["nodes"]:
        if node["name"] == name:
            return node
    raise AssertionError(f"node not found: {name}")


# --- the registry entry ---------------------------------------------------


def test_registry_entry_shape():
    entry = load_registry(REGISTRY_PATH).by_file(WORKFLOW_FILE)
    assert entry.name == "PWR Foundation Smoke v2"
    assert entry.generation == "v2"
    assert entry.authentication == "native_header_hmac"
    assert entry.managed is True
    assert entry.test_only is True
    assert entry.event_names == ("quality.assessment.requested.v1",)
    assert entry.webhook_paths == ("quality-assessment-v2",)
    assert entry.allowed_target_hosts == ("backend",)


def test_the_smoke_workflow_can_never_be_activated_in_production():
    """`production_activation: false` is a contract, not a comment.

    Asserted three ways, because the flag alone is only a value in a file:
    the flag itself, the registry's derived production activation order, and
    the guard `import-workflows.sh` actually calls before activating.
    """
    from infrastructure.scripts.stage_workflow import (
        ActivationError,
        assert_activatable,
    )

    registry = load_registry(REGISTRY_PATH)
    entry = registry.by_file(WORKFLOW_FILE)
    assert entry.production_activation is False
    assert WORKFLOW_FILE not in registry.activation_order()
    with pytest.raises(ActivationError, match="production_activation is false"):
        assert_activatable(
            {
                "file": entry.file,
                "managed": entry.managed,
                "production_activation": entry.production_activation,
                "test_only": entry.test_only,
                "generation": entry.generation,
            },
            credentials_verified=True,
            duplicate=False,
        )


def test_credential_bindings_name_nodes_that_exist_and_cover_every_signed_node():
    """A binding naming a node that does not exist is a credential that never
    gets attached; a signed node with no binding is a node that runs without
    one. `stage_workflow` fails closed on the first, and nothing at all
    catches the second -- so it is caught here.
    """
    workflow = _workflow()
    entry = load_registry(REGISTRY_PATH).by_file(WORKFLOW_FILE)
    node_names = {node["name"] for node in workflow["nodes"]}
    bound = {binding.node for binding in entry.credential_bindings}

    for binding in entry.credential_bindings:
        assert binding.node in node_names, binding.node

    signed_nodes = {
        node["name"]
        for node in workflow["nodes"]
        if node["type"].endswith(".pwrSignedHttpRequest")
    }
    assert signed_nodes, "vacuous: the workflow has no signed request node"
    assert signed_nodes <= bound, sorted(signed_nodes - bound)
    assert {"Webhook", "PWR Signature Gate"} <= bound


# --- the lease-bound artifact route ---------------------------------------


def _backend_artifact_route():
    """The artifact route AS THE BACKEND MOUNTS IT, read out of the router
    source rather than restated here.

    The plan (Task 15) still shows this path WITHOUT the `/leases/{token}/`
    segment -- it predates finding #5b, whose remediation bound the artifact
    endpoint to the lease. Restating the path as a literal in this test would
    have let the plan's stale shape sit here unnoticed; deriving it from
    `backend/app/routers/n8n_v2.py` means the day the backend route changes,
    this test is what fails.
    """
    source = ROUTER_SOURCE.read_text(encoding="utf-8")
    prefix = re.search(r'APIRouter\(prefix="(?P<p>[^"]+)"\)', source).group("p")
    v2_router_mount = "/api"  # app/main.py mounts routers/n8n_v2.py at "/api"
    match = re.search(
        r'@router\.post\(\s*\n\s*"(?P<a>/instances/[^"]*)"\s*\n\s*"(?P<b>[^"]*artifacts[^"]*)"',
        source,
    )
    assert match, "could not locate the artifact route in the router source"
    return v2_router_mount + prefix + match.group("a") + match.group("b")


def test_the_registered_artifact_template_is_the_backend_lease_bound_route():
    backend_route = _backend_artifact_route()
    assert "/leases/{processing_lease_token}/" in backend_route, backend_route

    entry = load_registry(REGISTRY_PATH).by_file(WORKFLOW_FILE)
    assert len(entry.artifact_path_templates) == 1
    template = entry.artifact_path_templates[0]

    # The template pins artifact_kind to the smoke's synthetic ZPL and is
    # otherwise the backend's route segment for segment.
    assert template == backend_route.replace("{artifact_kind}", "zpl")


def test_the_artifact_node_target_resolves_to_the_lease_bound_route():
    """The workflow's target, with its expressions replaced by concrete
    values, must be the backend's route -- segment for segment, including the
    lease segment.
    """
    target = _node(_workflow(), ARTIFACT_NODE)["parameters"]["target"]
    assert target.startswith("="), "an artifact target must be an n8n expression"

    resolved = target[1:]
    substitutions = {
        "odoo_instance": "smoke",
        "job_id": "11111111-1111-4111-8111-111111111111",
        "processing_lease_token": "lease-token-0123456789abcdef0123456789abcdef",
        "event_id": "22222222-2222-4222-8222-222222222222",
    }
    for field, value in substitutions.items():
        resolved = resolved.replace(
            "{{ encodeURIComponent($json.%s) }}" % field, value
        )
    assert "{{" not in resolved, resolved

    template = _backend_artifact_route().replace("{artifact_kind}", "zpl")
    expected = template
    for field, value in (
        ("{odoo_instance}", substitutions["odoo_instance"]),
        ("{job_id}", substitutions["job_id"]),
        ("{processing_lease_token}", substitutions["processing_lease_token"]),
        ("{source_event_id}", substitutions["event_id"]),
    ):
        expected = expected.replace(field, value)
    assert resolved == expected


def test_every_variable_artifact_segment_is_encodeuricomponent_wrapped():
    """The signed target is `request.scope["raw_path"]` on the backend side and
    `verify_signature` refuses query strings outright, so a runtime value that
    smuggled a "/" or a "?" into the path would change the signed bytes rather
    than fail gracefully. encodeURIComponent is what statically prevents that.
    """
    target = _node(_workflow(), ARTIFACT_NODE)["parameters"]["target"]
    expressions = re.findall(r"\{\{.*?\}\}", target)
    assert len(expressions) == 4, expressions
    for expression in expressions:
        assert re.fullmatch(
            r"\{\{\s*encodeURIComponent\([^{}]+\)\s*\}\}", expression
        ), expression


def test_the_smoke_carries_no_real_label_and_only_synthetic_bytes():
    """A test-only scaffold: no feature model, no carrier, no Quality
    decision, one deterministic synthetic artifact.
    """
    workflow = _workflow()
    artifact = _node(workflow, ARTIFACT_NODE)["parameters"]
    assert artifact["bodyMode"] == "literalUtf8"
    assert artifact["contentType"] == "application/zpl"
    assert artifact["literalBody"] == "^XA^FO20,20^FDFoundation smoke^FS^XZ"

    blob = json.dumps(workflow)
    for forbidden in ("openai", "langchain", "executeCommand", "dhl", "ups", "gls"):
        assert forbidden.lower() not in blob.lower(), forbidden


# --- accept ---------------------------------------------------------------


def test_the_committed_workflow_verifies_clean():
    assert verify_v2_workflow(_workflow(), _registry_spec()) == []


def test_the_production_gate_actually_applies_v2_checks_to_this_workflow():
    """Not vacuous: the runner must report this file as VERIFIED, not skipped.

    Before Task 15 every registry entry was v1, so `run_v2_checks` skipped all
    eight and returned no errors -- a green gate that had proved nothing.
    """
    errors, skipped = VERIFY_CLI.run_v2_checks(REGISTRY_PATH)
    assert errors == []
    assert not any(entry.startswith(WORKFLOW_FILE) for entry in skipped)
    registry = load_registry(REGISTRY_PATH)
    v2_files = [item.file for item in registry.workflows if item.generation == "v2"]
    assert v2_files == [WORKFLOW_FILE]
    assert len(skipped) == len(registry.workflows) - len(v2_files)


# --- reject ---------------------------------------------------------------
#
# One mutation each. The assertion is on the CAUSE, never merely on
# "errors != []" -- a rejection for the wrong reason is not evidence that the
# guard being tested works.


def _reject(mutate):
    workflow = _workflow()
    mutate(workflow)
    errors = verify_v2_workflow(workflow, _registry_spec())
    assert errors, "the mutated workflow was accepted"
    return errors


def test_reject_when_the_process_gate_is_removed():
    def mutate(workflow):
        workflow["nodes"] = [
            node for node in workflow["nodes"] if node["name"] != "If Process"
        ]
        workflow["connections"]["Accepted Response"] = {
            "main": [[{"node": "Smoke Wait", "type": "main", "index": 0}]]
        }
        del workflow["connections"]["If Process"]

    errors = _reject(mutate)
    assert any("gate on process == true" in error for error in errors), errors


def test_reject_when_the_process_gate_operator_is_inverted():
    """Far more dangerous than a missing gate: every effect then runs
    precisely when the backend answered process == false.
    """

    def mutate(workflow):
        conditions = _node(workflow, "If Process")["parameters"]["conditions"]
        conditions["boolean"][0]["operation"] = "notEqual"

    errors = _reject(mutate)
    assert any("gate on process == true" in error for error in errors), errors


def test_reject_when_a_signed_node_points_at_a_host_outside_the_allowlist():
    def mutate(workflow):
        _node(workflow, ARTIFACT_NODE)["parameters"]["host"] = "attacker.example.net"

    errors = _reject(mutate)
    assert any(
        "resolved host 'attacker.example.net' is not in allowed_target_hosts" in error
        for error in errors
    ), errors


def test_reject_when_the_lease_segment_is_dropped_from_the_artifact_target():
    """The whole point of finding #5b. The pre-#5b path -- the one the plan
    still shows -- must not verify against the registered template.
    """

    def mutate(workflow):
        node = _node(workflow, ARTIFACT_NODE)
        node["parameters"]["target"] = re.sub(
            r"/leases/\{\{[^}]*\}\}", "", node["parameters"]["target"]
        )

    errors = _reject(mutate)
    assert any("dynamic/unresolved n8n expression" in error for error in errors), errors


def test_reject_when_an_artifact_segment_drops_encodeuricomponent():
    def mutate(workflow):
        node = _node(workflow, ARTIFACT_NODE)
        node["parameters"]["target"] = node["parameters"]["target"].replace(
            "encodeURIComponent($json.processing_lease_token)",
            "$json.processing_lease_token",
        )

    errors = _reject(mutate)
    assert any("dynamic/unresolved n8n expression" in error for error in errors), errors


def test_reject_when_the_artifact_target_is_repointed_at_another_route():
    def mutate(workflow):
        node = _node(workflow, ARTIFACT_NODE)
        node["parameters"]["target"] = node["parameters"]["target"].replace(
            "/artifacts/zpl", "/artifacts/shipping-label"
        )

    errors = _reject(mutate)
    assert any("dynamic/unresolved n8n expression" in error for error in errors), errors


def test_reject_when_the_wait_node_opens_a_webhook_resume_ingress():
    """A `resume: webhook` Wait node mints an unauthenticated URL that
    continues this execution mid-flight -- a second ingress that never passes
    the Signature Gate.
    """

    def mutate(workflow):
        _node(workflow, "Smoke Wait")["parameters"]["resume"] = "webhook"

    errors = _reject(mutate)
    assert any("second ingress" in error for error in errors), errors


def test_reject_when_an_effect_is_moved_onto_a_side_path_around_the_process_gate():
    def mutate(workflow):
        workflow["connections"]["Accepted Response"]["main"][0].append(
            {"node": "Build Running Callback", "type": "main", "index": 0}
        )

    errors = _reject(mutate)
    assert any("not dominated by the true branch" in error for error in errors), errors


def test_reject_when_the_gate_verifies_another_workflows_target():
    def mutate(workflow):
        _node(workflow, "PWR Signature Gate")["parameters"][
            "expectedTarget"
        ] = "/webhook/shortage-reported"

    errors = _reject(mutate)
    assert any("expectedTarget" in error for error in errors), errors


def test_reject_when_the_acceptance_call_is_removed():
    def mutate(workflow):
        _node(workflow, ACCEPTANCE_NODE)["parameters"][
            "target"
        ] = "/api/internal/n8n/v2/callbacks/status"

    errors = _reject(mutate)
    assert any("acceptance route" in error for error in errors), errors


def test_reject_when_literal_utf8_is_used_outside_a_test_only_entry():
    """The synthetic-bytes mode is restricted to a reviewed `test_only: true`
    registry entry; production Shipping must use binary input instead.
    """
    workflow = _workflow()
    spec = dict(_registry_spec(), test_only=False)
    errors = verify_v2_workflow(workflow, spec)
    assert any("bodyMode=literalUtf8" in error for error in errors), errors


def test_reject_when_an_unlisted_node_type_runs_after_acceptance():
    def mutate(workflow):
        _node(workflow, "Build Terminal Callback")[
            "type"
        ] = "n8n-nodes-base.executeCommand"

    errors = _reject(mutate)
    assert any("not permitted after acceptance" in error for error in errors), errors


def test_the_mutations_above_are_single_edits_of_the_committed_document():
    """Guard the evidence: each rejection must come from ONE change to the
    real file, or "the verifier rejected it" says nothing about which guard
    fired.
    """
    baseline = _workflow()
    mutated = deepcopy(baseline)
    _node(mutated, ARTIFACT_NODE)["parameters"]["host"] = "attacker.example.net"
    assert mutated != baseline
    assert json.loads(WORKFLOW_PATH.read_text(encoding="utf-8")) == baseline
    # ... and the untouched document is still clean, so the restore is real.
    assert verify_v2_workflow(baseline, _registry_spec()) == []
