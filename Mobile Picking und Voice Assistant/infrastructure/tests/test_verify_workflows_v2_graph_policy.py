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
        ("process_gate_bypasses_acceptance.json", "dominated by the acceptance"),
        ("inverted_process_gate_operator.json", "process"),
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


def _mutations(reference, mutated, path="$"):
    """Every structural difference between two JSON documents, as a list.

    One replaced scalar counts as one mutation; one appended list item counts
    as one mutation. This is what makes the single-mutation claim a *test*
    rather than a comment: the previous version of this function asserted only
    `mutated != reference` plus matching top-level keys, which a fixture with
    ten mutations passes (fix round 1, finding 2).
    """
    if isinstance(reference, dict) and isinstance(mutated, dict):
        changes = []
        for key in sorted(set(reference) | set(mutated)):
            if key not in mutated:
                changes.append(f"{path}.{key}: removed")
            elif key not in reference:
                changes.append(f"{path}.{key}: added")
            else:
                changes += _mutations(reference[key], mutated[key], f"{path}.{key}")
        return changes
    if isinstance(reference, list) and isinstance(mutated, list):
        if len(reference) == len(mutated):
            changes = []
            for index, (before, after) in enumerate(zip(reference, mutated)):
                changes += _mutations(before, after, f"{path}[{index}]")
            return changes
        # An appended edge is ONE mutation, not one per leaf of the new item.
        if len(mutated) > len(reference) and mutated[: len(reference)] == reference:
            return [
                f"{path}[{i}]: appended" for i in range(len(reference), len(mutated))
            ]
        return [f"{path}: list replaced ({len(reference)} -> {len(mutated)} items)"]
    if reference != mutated:
        return [f"{path}: {reference!r} -> {mutated!r}"]
    return []


def test_the_mutation_counter_itself_counts():
    """Guard the guard: a two-mutation document must NOT look single-mutation."""
    reference = _load("task15_reference_graph.json")
    assert _mutations(reference, reference) == []

    one = _load("wrong_gate_target.json")
    assert len(_mutations(reference, one)) == 1

    two = _load("wrong_gate_target.json")
    two["nodes"][9]["type"] = "n8n-nodes-base.httpRequest"
    assert len(_mutations(reference, two)) == 2

    appended = _load("sidepath_around_the_process_gate.json")
    assert len(_mutations(reference, appended)) == 1


def test_every_fixture_differs_from_the_reference_in_exactly_one_way():
    """A rejection must be attributable to one cause, or the suite proves nothing."""
    reference = _load("task15_reference_graph.json")
    fixtures = [
        path
        for path in sorted(FIXTURES.glob("*.json"))
        if path.name != "task15_reference_graph.json"
    ]
    assert fixtures, "no adversarial fixtures found"
    for path in fixtures:
        mutated = json.loads(path.read_text(encoding="utf-8"))
        changes = _mutations(reference, mutated)
        assert len(changes) == 1, (path.name, changes)
