"""The v2 verifier must prove the graph, not sample one hop of it.

Regression cover for whole-branch review finding #3. Before this suite, a graph
of Gate -> Signed Request -> Business Effect passed, because the only check was
"the first node after the gate is some signed request".

The route literals below are the ones the backend actually mounts
(app/main.py mounts routers/n8n_v2.py at "/api", the router itself adds
"/internal", and V2 adds "/n8n/v2"), NOT the abbreviated forms used in the
task brief -- a verifier pinned to a path the backend does not serve would
reject every real workflow.
"""

import json
from pathlib import Path

import pytest

from infrastructure.scripts.workflow_verifier import verify_v2_workflow

FIXTURES = Path(__file__).parent / "fixtures" / "v2_adversarial"

SPEC = {
    "file": "task15_reference_graph.json",
    "name": "pwr.v2.smoke",
    "generation": "v2",
    "webhook_paths": ["/webhook/pwr-v2-smoke"],
    "callback_paths": ["/api/internal/n8n/v2/callbacks/status"],
    "artifact_path_templates": ["/api/internal/n8n/v2/artifacts/{event_id}/status"],
    "allowed_target_hosts": ["backend"],
    "authentication": "headerAuth",
    "managed": True,
}


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_the_task15_reference_graph_is_accepted():
    assert verify_v2_workflow(_load("task15_reference_graph.json"), SPEC) == []


@pytest.mark.parametrize(
    "fixture,expected_fragment",
    [
        ("artifact_instead_of_acceptance.json", "acceptance"),
        ("effect_directly_after_acceptance.json", "process"),
        ("effect_on_the_false_branch.json", "false"),
        ("sidepath_around_the_process_gate.json", "dominat"),
        ("wrong_gate_target.json", "target"),
        ("spoofed_rejection_node.json", "type"),
    ],
)
def test_adversarial_graphs_are_rejected(fixture, expected_fragment):
    # The spec's "file" is deliberately NOT the fixture name: the verifier
    # prefixes it onto every message, so file=fixture would let
    # "effect_on_the_false_branch.json" satisfy the "false" fragment out of
    # its own filename and the assertion would prove nothing.
    errors = verify_v2_workflow(_load(fixture), dict(SPEC, file="workflow.json"))
    assert errors, f"{fixture} was accepted"
    assert any(expected_fragment in error.lower() for error in errors), (fixture, errors)


def test_every_fixture_differs_from_the_reference_in_exactly_one_way():
    """A rejection must be attributable to one cause, or the suite proves nothing."""
    reference = _load("task15_reference_graph.json")
    for path in sorted(FIXTURES.glob("*.json")):
        if path.name == "task15_reference_graph.json":
            continue
        mutated = json.loads(path.read_text(encoding="utf-8"))
        assert mutated != reference
        assert set(mutated) == set(reference), path.name
