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
import re
from pathlib import Path

import pytest

from infrastructure.scripts.workflow_verifier import (
    POST_ACCEPTANCE_ALLOWED_TYPES,
    SIGNED_HTTP_TYPES,
    _dominated_by,
    _reachable_node_names,
    verify_v2_workflow,
)

FIXTURES = Path(__file__).parent / "fixtures" / "v2_adversarial"

SPEC = {
    "file": "task15_reference_graph.json",
    "name": "pwr.v2.smoke",
    "generation": "v2",
    # Bare kebab path and native_header_hmac: this SPEC must be a shape a real
    # registry can actually produce. `load_registry` rejects any v2 entry whose
    # authentication is not "native_header_hmac", and the backend's second
    # reader (app/services/workflow_targets.py) RAISES on a webhook_path
    # spelled "/webhook/..." -- it matches ^[a-z0-9][a-z0-9-]*$ against
    # paths[0] and prefixes "/webhook/" itself. Proving graph policy against a
    # registry entry that could never exist proves it for nothing.
    "webhook_paths": ["pwr-v2-smoke"],
    "callback_paths": ["/api/internal/n8n/v2/callbacks/status"],
    "artifact_path_templates": ["/api/internal/n8n/v2/artifacts/{event_id}/status"],
    "allowed_target_hosts": ["backend"],
    "authentication": "native_header_hmac",
    "managed": True,
}


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_the_spec_is_a_shape_a_real_registry_can_produce():
    """Whole-branch review finding: this SPEC once declared
    authentication="headerAuth" (which `load_registry` rejects for v2) and a
    webhook path spelled "/webhook/pwr-v2-smoke" (on which the backend's
    `load_event_targets` raises). Every rejection below is proven against this
    SPEC, so if the SPEC is unbuildable the whole proof set is about nothing.
    Both constraints are restated here rather than imported: this file must not
    depend on the backend package being importable."""
    assert SPEC["authentication"] == "native_header_hmac"
    assert SPEC["webhook_paths"], "a v2 entry declares exactly one webhook path"
    for path in SPEC["webhook_paths"]:
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", path), (
            f"{path!r} is not a bare kebab-case path; the backend reader "
            "prefixes '/webhook/' itself and rejects anything else"
        )


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
        # Obligation 10. All three are DOMINATED by the process gate's true
        # branch and so satisfy obligation 7 completely; each one differs from
        # the reference by a single node TYPE. Before obligation 10 existed the
        # verifier returned zero errors for every one of them, because the only
        # post-acceptance net was ABSOLUTE_URL_RE and none of them carries a
        # literal absolute URL.
        ("post_accept_execute_command.json", "not permitted after acceptance"),
        ("post_accept_langchain.json", "not permitted after acceptance"),
        ("post_accept_unknown_community_node.json", "not permitted after acceptance"),
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


def test_post_acceptance_allowlist_rejects_an_invented_type():
    """The list must be an ALLOWLIST, not a denylist.

    A type nobody has ever written down anywhere -- not in the verifier, not in
    a fixture, not in n8n -- must fail for exactly that reason. This lane was
    already bitten once by an outbound rule that enumerated forbidden types and
    let an unlisted `graphql` node with an external endpoint through.
    """
    graph = _load("task15_reference_graph.json")
    for node in graph["nodes"]:
        if node["name"] == "Publish Artifact":
            node["type"] = "n8n-nodes-community.brand-new-thing"
    errors = verify_v2_workflow(graph, dict(SPEC, file="workflow.json"))
    assert any("not permitted after acceptance" in error.lower() for error in errors), errors


SIGNED_HTTP_ALTERNATE_SPELLING = "n8n-nodes-pwr.pwrSignedHttpRequest"


REPO_ROOT = Path(__file__).resolve().parents[2]
# The COMMITTED v2 workflow -- the real one the registry ships and
# verify-workflows.py checks, not a fixture. Task 15 widened
# POST_ACCEPTANCE_ALLOWED_TYPES by three types; the derivation guard only
# stays a guard if those three are observed running post-acceptance in a
# workflow that actually exists, so it is a second source graph here rather
# than an exception carved into the assertion.
SMOKE_WORKFLOW_PATH = REPO_ROOT / "n8n" / "workflows" / "pwr-foundation-smoke-v2.json"

# (graph document, process-gate node name, trigger node name)
OBSERVED_GRAPHS = (
    ("task15_reference_graph.json", "Process Gate", "Webhook"),
    ("pwr-foundation-smoke-v2.json", "If Process", "Webhook"),
)


def _load_observed(name):
    if name == SMOKE_WORKFLOW_PATH.name:
        return json.loads(SMOKE_WORKFLOW_PATH.read_text(encoding="utf-8"))
    return _load(name)


def _types_dominated_by_the_true_branch_of(name, gate_name, trigger_name):
    graph = _load_observed(name)
    connections = graph["connections"]
    by_name = {node["name"]: node for node in graph["nodes"]}
    dominated = _dominated_by(
        connections,
        gate_name,
        0,
        set(_reachable_node_names(connections, [trigger_name])) & set(by_name),
        trigger_name=trigger_name,
    )
    assert dominated, f"{name} has an empty true branch; guard is vacuous"
    return {by_name[node_name]["type"] for node_name in dominated}


def _types_dominated_by_the_true_branch():
    """Every post-acceptance node type observed across the committed v2 graphs.

    Computed with the SAME `_dominated_by(..., output_index=0, ...)` call that
    obligation 10 makes, over the same every-namespace reachable set rooted at
    the trigger -- so if obligation 10's notion of "after acceptance" ever
    changes, this guard changes with it instead of silently drifting apart.
    """
    observed = set()
    for name, gate_name, trigger_name in OBSERVED_GRAPHS:
        observed |= _types_dominated_by_the_true_branch_of(name, gate_name, trigger_name)
    return observed


def test_post_acceptance_allowlist_is_derived_from_the_reference_workflow():
    """Guard against a speculative entry: every listed type must run POST-acceptance.

    "In use somewhere in the reference graph" is too weak to be this guard: the
    graph also contains `n8n-nodes-base.set`, `n8n-nodes-base.if`, the webhook
    and the signature gate, all of them PRE-acceptance. A first version of this
    test compared against every node type in the file, so adding `set` to
    POST_ACCEPTANCE_ALLOWED_TYPES -- precisely the speculative widening this
    guard exists to catch -- kept the suite green (fix round 1, finding 2).

    So the comparison set is computed with the SAME `_dominated_by` call
    obligation 10 makes, against the same graph: the types that actually run on
    the process gate's true branch, and nothing else.

    The one exemption is the alternate spelling of the signed-request node,
    which is justified by registration symmetry rather than by observation --
    see the comment on POST_ACCEPTANCE_ALLOWED_TYPES. It is named explicitly
    here so the exemption cannot silently grow to cover a second entry.
    """
    types_after_acceptance = _types_dominated_by_the_true_branch()
    permitted = types_after_acceptance | {SIGNED_HTTP_ALTERNATE_SPELLING}
    assert POST_ACCEPTANCE_ALLOWED_TYPES <= permitted, sorted(
        POST_ACCEPTANCE_ALLOWED_TYPES - permitted
    )
    # And the exemption really is the alternate spelling of a type that IS
    # observed, not a free pass for an unrelated node.
    assert SIGNED_HTTP_ALTERNATE_SPELLING in SIGNED_HTTP_TYPES
    assert types_after_acceptance & SIGNED_HTTP_TYPES


def test_the_derivation_guard_rejects_a_pre_acceptance_only_type():
    """Guard the guard: the negative control finding 2 was actually about.

    Every type below IS present in the reference graph but only BEFORE
    acceptance. The old guard compared against every node type in the file and
    so accepted all of them; this asserts both halves -- that they really are in
    the graph (or the control proves nothing) and that widening
    POST_ACCEPTANCE_ALLOWED_TYPES with any one of them now FAILS the guard.

    `n8n-nodes-base.set` and `n8n-nodes-base.if` were controls here until Task
    15. They no longer are, and NOT because the guard was relaxed: the
    committed smoke workflow runs both of them on its process gate's true
    branch, so they are now observed post-acceptance and the guard is telling
    the truth about them. The trigger and the Signature Gate remain controls --
    no committed graph runs either after acceptance, and if one ever did, this
    test failing is the correct outcome.
    """
    reference = _load("task15_reference_graph.json")
    types_in_reference = {node["type"] for node in reference["nodes"]}
    permitted = _types_dominated_by_the_true_branch() | {SIGNED_HTTP_ALTERNATE_SPELLING}

    for pre_acceptance_only in (
        "n8n-nodes-base.webhook",
        "CUSTOM.pwrSignatureGate",
    ):
        # Half one: the old, too-weak guard really would have accepted this.
        assert pre_acceptance_only in types_in_reference, pre_acceptance_only
        # Half two: the new guard does not.
        widened = POST_ACCEPTANCE_ALLOWED_TYPES | {pre_acceptance_only}
        assert not widened <= permitted, pre_acceptance_only


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
