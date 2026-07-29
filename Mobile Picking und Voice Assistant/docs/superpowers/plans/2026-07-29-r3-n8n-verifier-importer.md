# R3 — n8n Verifier and Importer Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the v2 workflow verifier into a positive graph policy that actually proves acceptance-before-effects, close the registry's open generation field, and repair the credential importer whose wire format guarantees that the first credential-bound import fails.

**Architecture:** Task 1 replaces "the first node after the gate is some signed request" with eight explicit graph proofs and an adversarial fixture set. Task 2 closes the generation string so an unknown value cannot skip every v2 check. Task 3 unifies the importer's and stager's wire format and moves the permission check to where the file is actually read.

**Tech Stack:** Python 3 (`infrastructure/scripts/`), bash, Node (`n8n/scripts/`), pytest, n8n workflow JSON.

## Global Constraints

- Test command: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/ -q`
- The verifier is an **allowlist-based static checker, not a data-flow analyser**. Two bypass classes stay explicitly out of scope and must remain documented in its docstring: renamed or case-varied field names dodging substring matches (`photoCount` vs `photo_count`), and payloads assembled at runtime (`['art','ifact','_data'].join('')`). Closing either needs a JS AST pass.
- Never embed an n8n CLI's stdout or stderr in a raised exception — that leaks secrets into logs. This was already fixed once in Task 14 and must not regress.
- Enumerate what is **permitted**, never what is forbidden. An unlisted node type must fail, not pass.
- No `generation: "v2"` workflow exists in the registry yet; Task 15 lands the first one. Task 1 therefore builds its proofs against fixtures, and Task 15 owes a re-run against the real workflow.
- TDD is mandatory: adversarial fixture first, proven to be accepted today, then the check that rejects it.

---

### Task 1: Replace the acceptance check with a positive graph policy

Finding #3 (Critical). `workflow_verifier.py:1031` asserts only that the single node reached from
the Signature Gate's accepted output is *some* `PWR Signed HTTP Request`. It never checks that the
request targets the acceptance route, never requires a `process == true` gate, and never proves
that every business effect is dominated by that gate's true branch. A graph of
`Gate -> Signed Request -> Business Effect` passes. Worse,
`infrastructure/tests/test_verify_workflows_v2.py:97` currently *asserts* that an artifact call is
a valid first "acceptance" node, so the test suite pins the hole in place. Conversely the Task 15
plan mandates a builder node before acceptance, which today's verifier would reject.

**Files:**
- Modify: `infrastructure/scripts/workflow_verifier.py` (the v2 section, around line 1000-1080)
- Modify: `infrastructure/tests/test_verify_workflows_v2.py:97` (the test that pins the defect)
- Create: `infrastructure/tests/fixtures/v2_adversarial/` (seven workflow JSON fixtures)
- Create: `infrastructure/tests/test_verify_workflows_v2_graph_policy.py`

**Interfaces:**
- Consumes: `verify_v2_workflow(data: dict, spec: dict) -> list[str]`, `_first_output_targets(connections, node_name, output_index) -> list[str]`, `_reachable_node_names(connections, targets) -> set[str]`, `RESPOND_TO_WEBHOOK_NODE`, `SIGNED_HTTP_TYPES` — all existing in `infrastructure/scripts/workflow_verifier.py`.
- Produces: `ACCEPTANCE_TARGET_PATH = "/api/internal/n8n/v2/events/accept"` — this is the path the backend actually serves (`main.py` mounts the router at `prefix="/api"`, the router itself carries `prefix="/internal"`, and the route adds `V2 + "/events/accept"`). An earlier draft of this plan wrote `/api/n8n/v2/events/accept`, which would have made obligation 5 reject the real Task 15 workflow. Verify against `backend/app/routers/n8n_v2.py` rather than trusting either value; `PRE_ACCEPTANCE_ALLOWED_TYPES: frozenset[str]` (the seit-effect-free builder allowlist); `_dominated_by(connections, gate_name, output_index, node_names) -> set[str]` returning the subset of `node_names` reachable **only** through that output.

- [ ] **Step 1: Write the adversarial fixtures**

Create seven files under `infrastructure/tests/fixtures/v2_adversarial/`. Each is a complete n8n
workflow JSON differing from a known-good v2 graph in exactly one way, so a rejection message
points at one cause:

| File | Mutation | Must be rejected because |
|------|----------|--------------------------|
| `artifact_instead_of_acceptance.json` | first node after the gate is a signed request to the artifact route | acceptance target is not `/api/n8n/v2/events/accept` |
| `effect_directly_after_acceptance.json` | acceptance is followed immediately by a carrier call, no process gate | no `process == true` gate dominates the effect |
| `effect_on_the_false_branch.json` | a model node hangs off the process gate's false output | the false branch must end without effect |
| `sidepath_around_the_process_gate.json` | a second connection reaches the carrier node from before the gate | the effect is not dominated by the true branch |
| `wrong_gate_target.json` | the Signature Gate's `expectedTarget` is a different path than the registry's | gate target must literally match the registry path |
| `spoofed_rejection_node.json` | a node *named* `Respond to Webhook` but of type `n8n-nodes-base.httpRequest` on the rejection path | identity is the node type, never its name |
| `task15_reference_graph.json` | the exact graph the Task 15 plan mandates — webhook, gate, builder, acceptance, process gate, effects, respond | must be **accepted** |

Write `task15_reference_graph.json` first and derive the other six from it by a single mutation
each, so a rejection cannot be attributed to unrelated drift.

- [ ] **Step 2: Write the failing test**

Create `infrastructure/tests/test_verify_workflows_v2_graph_policy.py`:

```python
"""The v2 verifier must prove the graph, not sample one hop of it.

Regression cover for whole-branch review finding #3. Before this suite, a graph
of Gate -> Signed Request -> Business Effect passed, because the only check was
"the first node after the gate is some signed request".
"""

import json
from pathlib import Path

import pytest

from workflow_verifier import verify_v2_workflow

FIXTURES = Path(__file__).parent / "fixtures" / "v2_adversarial"

SPEC = {
    "file": "task15_reference_graph.json",
    "name": "pwr.v2.smoke",
    "generation": "v2",
    "webhook_paths": ["/webhook/pwr-v2-smoke"],
    "callback_paths": ["/api/n8n/v2/jobs/callback"],
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
    # The spec's `file` MUST stay neutral. Passing the fixture name through
    # puts it into every error message, so `"false"`, `"process"`, `"target"`
    # and `"acceptance"` would match the FILENAME rather than the cause -- a
    # test that asserts nothing while looking thorough.
    errors = verify_v2_workflow(_load(fixture), dict(SPEC, file="workflow.json"))
    assert errors, f"{fixture} was accepted"
    assert any(expected_fragment in error.lower() for error in errors), errors


def test_every_fixture_differs_from_the_reference_in_exactly_one_way():
    """A rejection must be attributable to one cause, or the suite proves nothing."""
    reference = _load("task15_reference_graph.json")
    for path in sorted(FIXTURES.glob("*.json")):
        if path.name == "task15_reference_graph.json":
            continue
        mutated = json.loads(path.read_text(encoding="utf-8"))
        assert mutated != reference
        assert set(mutated) == set(reference), path.name
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/test_verify_workflows_v2_graph_policy.py -q`
Expected: `test_the_task15_reference_graph_is_accepted` FAILS (the builder before acceptance is
rejected by the current one-hop rule), and at least
`artifact_instead_of_acceptance.json`, `effect_directly_after_acceptance.json`,
`effect_on_the_false_branch.json` and `sidepath_around_the_process_gate.json` FAIL because they are
accepted.

- [ ] **Step 4: Implement the eight proofs**

Replace the one-hop check in `workflow_verifier.py` with checks that prove, in this order:

```python
# Der Verifier beweist den Graphen, er tastet ihn nicht ab. Acht Pflichten:
#
#  1. Genau ein Webhook-Knoten, mit dem Registry-Pfad und Methode POST.
#  2. Genau ein Signature Gate, mit literalem expectedMethod und expectedTarget,
#     die exakt zum Registry-Eintrag passen.
#  3. Der Rejection-Ausgang erreicht ausschliesslich einen terminalen Knoten
#     vom TYP Respond to Webhook -- ein gleichnamiger Knoten anderen Typs ist
#     ein Angriff, kein Tippfehler.
#  4. Vor Acceptance sind nur Knoten aus PRE_ACCEPTANCE_ALLOWED_TYPES erlaubt,
#     also seiteneffektfreie Builder. Allowlist, nie Denylist.
#  5. Genau ein Signed Request zeigt auf ACCEPTANCE_TARGET_PATH.
#  6. Danach existiert ein explizites Gate auf process == true.
#  7. Jeder Modell-, Carrier-, Callback- und Artifact-Knoten wird vom
#     True-Zweig dieses Gates DOMINIERT -- Erreichbarkeit genuegt nicht, denn
#     ein Nebenpfad um das Gate herum ist ebenfalls erreichbar.
#  8. Der False-Zweig endet ohne Wirkung.
```

`_dominated_by` must compute domination, not reachability: a node is dominated by an output when
**every** path from the trigger to that node passes through it. Compute it as "reachable from the
trigger with that output's edge removed" — anything still reachable is not dominated.

Point 7 is the one the previous verifier round got wrong in the same shape: reachability was
computed from the gate rather than from the trigger, so anything hung off the webhook before the
gate was invisible. Root every traversal at the **trigger**.

- [ ] **Step 5: Fix the test that pins the defect**

`infrastructure/tests/test_verify_workflows_v2.py:97` currently asserts that an artifact call is a
valid first acceptance node. Invert it: it must now assert rejection, with a comment naming this
finding. Do not delete the test.

- [ ] **Step 6: Run both suites to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/ -q`
Expected: green.

Run: `cd infrastructure && python scripts/verify-workflows.py`
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add infrastructure/scripts/workflow_verifier.py infrastructure/tests/test_verify_workflows_v2.py infrastructure/tests/test_verify_workflows_v2_graph_policy.py infrastructure/tests/fixtures/v2_adversarial/
git commit -m "fix(n8n): prove the v2 graph instead of sampling one hop of it"
```

---

### Task 2: Close the registry's generation field

Finding #12 (Important). `workflow_registry.py:120` copies `value["generation"]` verbatim, and
`verify-workflows.py:49` skips every workflow whose generation is not exactly `"v2"`. A registry
entry with `generation: "v2-typo"`, `"V2"` or `"v3"` therefore bypasses every v2 check silently —
the same fail-open shape as R1's runtime profile.

**Files:**
- Modify: `infrastructure/scripts/workflow_registry.py:100-135`
- Modify: `infrastructure/scripts/verify-workflows.py:42-58`
- Test: `infrastructure/tests/test_workflow_registry.py` (extend)

**Interfaces:**
- Consumes: `load_registry(path) -> Registry`, `WorkflowSpec` — both in `infrastructure/scripts/workflow_registry.py`.
- Produces: `KNOWN_GENERATIONS = ("v1", "v2")` and `GRANDFATHERED_V1_FILES: frozenset[str]` in `workflow_registry.py`. `load_registry` raises `ValueError` on an unknown generation and on a new `v1` entry.

- [ ] **Step 1: Write the failing tests**

Append to `infrastructure/tests/test_workflow_registry.py`:

```python
@pytest.mark.parametrize("generation", ["v2-typo", "V2", "v3", "", "v2 ", " v2"])
def test_unknown_generation_is_rejected(tmp_path, generation):
    """An unknown generation silently skipped every v2 check.
    Regression cover for finding #12."""
    registry = tmp_path / "workflow-registry.json"
    registry.write_text(
        json.dumps(_registry_document(generation=generation)), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="generation"):
        load_registry(registry)


def test_a_new_v1_entry_is_rejected(tmp_path):
    """v1 is frozen: the listed legacy files may stay, nothing may join them."""
    registry = tmp_path / "workflow-registry.json"
    registry.write_text(
        json.dumps(_registry_document(generation="v1", file="brand-new.json")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="grandfather"):
        load_registry(registry)


def test_the_grandfathered_v1_files_still_load(tmp_path):
    from workflow_registry import GRANDFATHERED_V1_FILES

    assert GRANDFATHERED_V1_FILES, "the existing v1 workflows must be listed explicitly"
    registry = tmp_path / "workflow-registry.json"
    registry.write_text(
        json.dumps(
            _registry_document(generation="v1", file=sorted(GRANDFATHERED_V1_FILES)[0])
        ),
        encoding="utf-8",
    )
    assert load_registry(registry).workflows


def test_the_real_registry_still_loads():
    """The grandfather list must actually match what is on disk."""
    load_registry(REAL_REGISTRY_PATH)
```

`_registry_document(...)` is a helper this module already has for building a minimal valid registry
document; extend its signature with `generation` and `file` keyword arguments rather than writing a
second builder. `REAL_REGISTRY_PATH` points at `n8n/workflow-registry.json`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/test_workflow_registry.py -q`
Expected: the unknown generations load without error; `GRANDFATHERED_V1_FILES` does not import.

- [ ] **Step 3: Close the generation field**

In `workflow_registry.py`:

```python
KNOWN_GENERATIONS = ("v1", "v2")

# v1 ist eingefroren. Diese Dateien existierten, bevor die v2-Kette gebaut
# wurde, und duerfen bleiben; neue v1-Eintraege sind verboten, weil v1 keine
# der v2-Pruefungen durchlaeuft. Ein offenes Generationsfeld war ein
# Fail-open: "v2-typo" hat jede einzelne v2-Pruefung stillschweigend
# uebersprungen.
GRANDFATHERED_V1_FILES = frozenset({
    # Fill from the current registry: every entry whose generation is "v1".
})
```

Validate inside `load_registry` before constructing the `WorkflowSpec`:

```python
        generation = value["generation"]
        if generation not in KNOWN_GENERATIONS:
            raise ValueError(
                f"{value['file']}: unknown generation {generation!r}; "
                f"expected one of {KNOWN_GENERATIONS}"
            )
        if generation == "v1" and value["file"] not in GRANDFATHERED_V1_FILES:
            raise ValueError(
                f"{value['file']}: new v1 entries are forbidden (not grandfathered); "
                "new workflows must be v2"
            )
```

Populate `GRANDFATHERED_V1_FILES` from the actual registry. Note `workflows` is a **list** of
objects, not a mapping — an earlier draft of this plan wrote `.values()` here and was wrong:
`python -c "import json;print(sorted(w['file'] for w in json.load(open('n8n/workflow-registry.json'))['workflows'] if w['generation']=='v1'))"`

- [ ] **Step 4: Make the verifier's skip explicit**

In `verify-workflows.py`, replace the silent `continue` with a branch that is visible in the
output, so a skipped workflow is a reported fact rather than an absence:

```python
        if workflow_spec.generation != "v2":
            skipped.append(f"{workflow_spec.file} (generation {workflow_spec.generation})")
            continue
```

and print the `skipped` list before returning. Silent truncation reads as "covered everything".

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/ -q` — green.
Run: `cd infrastructure && python scripts/verify-workflows.py` — exit 0, and the skip list is
printed.

- [ ] **Step 6: Commit**

```bash
git add infrastructure/scripts/workflow_registry.py infrastructure/scripts/verify-workflows.py infrastructure/tests/test_workflow_registry.py
git commit -m "fix(n8n): close the registry generation field and report skipped workflows"
```

---

### Task 3: Repair the credential importer wire format and permission check

Findings #13 and #16 (Important). `import-workflows.sh:341` emits each row with the key
`"credential"` holding a single object or `None`; `stage_workflow.py:227` reads
`row.get("credentials")` expecting a list. Every real binding therefore resolves to zero
candidates and fails closed — the first credential-bound v2 import will fail, and the integration
tests never caught it because they only exercise empty bindings. Separately,
`provision-n8n-credentials.sh:44` checks permissions on **host** paths and ignores missing files
there, while the files are actually read at identically named paths **inside the container**, and
`n8n/scripts/provision-credentials.mjs:115` checks neither mode, owner, symlink nor regular-file.

**Files:**
- Modify: `infrastructure/scripts/import-workflows.sh:336-346`
- Modify: `infrastructure/scripts/provision-n8n-credentials.sh:40-60`
- Modify: `n8n/scripts/provision-credentials.mjs:110-130`
- Test: `infrastructure/tests/test_import_workflows.py` (extend)
- Test: `infrastructure/tests/test_stage_workflow.py` (extend)

**Interfaces:**
- Consumes: `stage_workflow.py`'s stage command and its documented wire format for `credential_index`.
- Produces: one shared wire format, documented in **both** files. A row is
  `{"logical_name": str, "credential_type": str, "credentials": list[dict]}`, where `credentials`
  lists **every** candidate found for that key so that a genuine duplicate is representable and
  the "exactly one" check has something to reject.

- [ ] **Step 1: Write the failing tests**

Append to `infrastructure/tests/test_import_workflows.py`:

```python
def test_importer_emits_the_wire_format_the_stager_reads(mocked_docker, tmp_registry):
    """The importer emitted "credential" (one object); the stager reads
    "credentials" (a list). Every real binding resolved to zero candidates.
    Regression cover for finding #13."""
    payload = _run_importer_and_capture_stage_payload(
        mocked_docker,
        tmp_registry,
        credentials=[{"id": "id-1", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"}],
    )

    rows = payload["credential_index"]
    assert rows, "a workflow with a binding must produce at least one row"
    for row in rows:
        assert set(row) == {"logical_name", "credential_type", "credentials"}
        assert isinstance(row["credentials"], list)


def test_exactly_one_matching_credential_imports_successfully(mocked_docker, tmp_registry):
    result = _run_importer(
        mocked_docker,
        tmp_registry,
        credentials=[{"id": "id-1", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"}],
    )
    assert result.returncode == 0, result.stderr


def test_zero_matching_credentials_fails_closed(mocked_docker, tmp_registry):
    result = _run_importer(mocked_docker, tmp_registry, credentials=[])
    assert result.returncode != 0
    assert "credential" in result.stderr.lower()


def test_two_matching_credentials_fail_closed(mocked_docker, tmp_registry):
    result = _run_importer(
        mocked_docker,
        tmp_registry,
        credentials=[
            {"id": "id-1", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"},
            {"id": "id-2", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"},
        ],
    )
    assert result.returncode != 0
    assert "duplicate" in result.stderr.lower() or "exactly one" in result.stderr.lower()


def test_no_cli_output_is_embedded_in_the_error(mocked_docker, tmp_registry):
    """n8n CLI stdout can carry secrets. It must never reach a raised error."""
    result = _run_importer(
        mocked_docker, tmp_registry, credentials=[], cli_stdout="SECRET-VALUE-abc123"
    )
    assert "SECRET-VALUE-abc123" not in result.stderr
    assert "SECRET-VALUE-abc123" not in result.stdout
```

`mocked_docker` and `_run_importer` are the harness that module already has — the one that found
the `--registry`-before-subcommand bug. `_run_importer_and_capture_stage_payload` is new: run the
real shell script against the mocked docker and capture the JSON it pipes into `stage_workflow.py`.
These must go through the **actual shell script**, not a Python reimplementation of it; the whole
point of this finding is that the two halves were never run against each other.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/test_import_workflows.py -q`
Expected: `test_importer_emits_the_wire_format_the_stager_reads` fails on the key set (`credential`
vs `credentials`), and `test_exactly_one_matching_credential_imports_successfully` fails because
the stager sees zero candidates.

- [ ] **Step 3: Unify the wire format**

In `infrastructure/scripts/import-workflows.sh`, change the `credential_index` construction:

```python
credential_index = [
    {
        "logical_name": binding["logical_name"],
        "credential_type": binding["credential_type"],
        # Eine LISTE aller Kandidaten, nicht der eine "beste" Treffer: nur so
        # ist ein echtes Duplikat ueberhaupt darstellbar und die
        # "genau einer"-Pruefung in stage_workflow.py hat etwas abzulehnen.
        "credentials": [
            item
            for item in credential_metadata.get("credentials", [])
            if item["name"] == binding["logical_name"]
            and item["type"] == binding["credential_type"]
        ],
    }
    for binding in bindings
]
```

`credentials_by_name_type` becomes unused — delete it rather than leaving it as a second, diverging
source of truth. Copy the wire-format comment block from `stage_workflow.py:227-233` into the shell
script above this list so both sides carry the same specification.

- [ ] **Step 4: Move the permission check to where the file is read**

In `n8n/scripts/provision-credentials.mjs`, immediately before reading each secret file:

```javascript
// Der Host-Pfad-Check in provision-n8n-credentials.sh prueft eine andere
// Datei als die, die hier gelesen wird -- gleicher Name, anderer Namespace.
// Die einzige Pruefung, die zaehlt, sitzt unmittelbar vor dem Lesen, im
// Container, und benutzt lstat: mit stat wuerde ein Symlink auf eine
// world-readable Datei die Rechte des Ziels zeigen, nicht die des Links.
const info = await fs.lstat(filePath);
if (!info.isFile()) {
  throw new Error(`credential file ${filePath} is not a regular file`);
}
if ((info.mode & 0o077) !== 0) {
  throw new Error(`credential file ${filePath} is group- or world-accessible`);
}
if (info.uid !== process.getuid()) {
  throw new Error(`credential file ${filePath} is not owned by the runtime user`);
}
```

In `infrastructure/scripts/provision-n8n-credentials.sh`, the host-side check must **fail** on a
missing file instead of ignoring it, and its comment must state plainly that it is an early
convenience check and not the boundary.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/ -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add infrastructure/scripts/import-workflows.sh infrastructure/scripts/provision-n8n-credentials.sh n8n/scripts/provision-credentials.mjs infrastructure/tests/test_import_workflows.py infrastructure/tests/test_stage_workflow.py
git commit -m "fix(n8n): unify the credential wire format and check permissions where files are read"
```

---

### Task 4: Allowlist node types after acceptance

Added 2026-07-29, raised by Task 1's reviewer. Task 1's obligation 7 requires every business
effect to be *dominated* by the process gate's true branch — it never constrains *what* those
effects may be. Post-acceptance the only remaining net is `ABSOLUTE_URL_RE`, which needs a literal
absolute URL. The reviewer demonstrated all of these passing with **zero errors** on the dominated
true branch:

- `n8n-nodes-base.executeCommand` carrying a shell command that exfiltrates a local file
- `@n8n/n8n-nodes-langchain.openAi`
- an invented `n8n-nodes-community.evilThing` with `host` and `path` parameters

They are gated behind backend acceptance, which is what obligation 7 promised — but "gated" is not
"blocked", and the threat model here is a tampered or malicious workflow definition, where the
verifier *is* the boundary. The pre-acceptance side already allowlists; the post-acceptance side
must too. Enumerate what is permitted, never what is forbidden.

**Files:**
- Modify: `infrastructure/scripts/workflow_verifier.py`
- Modify: `infrastructure/tests/test_verify_workflows_v2_graph_policy.py`
- Create: three fixtures under `infrastructure/tests/fixtures/v2_adversarial/`

**Interfaces:**
- Consumes: `PRE_ACCEPTANCE_ALLOWED_TYPES`, `_dominated_by(connections, gate_name, output_index, node_names, *, trigger_name)` — both from Task 1.
- Produces: `POST_ACCEPTANCE_ALLOWED_TYPES: frozenset[str]`, enumerating exactly the node types a v2 workflow may run after acceptance. Obligation 10: every node on the dominated true branch must be of an allowlisted type.

- [ ] **Step 1: Write the failing fixtures and tests**

Three new single-mutation fixtures derived from `task15_reference_graph.json`, each placing one
node on the dominated true branch: `post_accept_execute_command.json`,
`post_accept_langchain.json`, `post_accept_unknown_community_node.json`. Extend the parametrised
rejection test with all three, expecting the fragment `"not permitted after acceptance"`.

Add one test proving the allowlist is an allowlist:

```python
def test_post_acceptance_allowlist_rejects_an_invented_type():
    graph = _load("task15_reference_graph.json")
    for node in graph["nodes"]:
        if node["name"] == "Publish Artifact":
            node["type"] = "n8n-nodes-community.brand-new-thing"
    errors = verify_v2_workflow(graph, dict(SPEC, file="workflow.json"))
    assert any("not permitted after acceptance" in error.lower() for error in errors), errors
```

- [ ] **Step 2: Run to verify they fail**

Expected: all four accepted today, zero errors.

- [ ] **Step 3: Derive the allowlist from the real workflow, not from imagination**

`POST_ACCEPTANCE_ALLOWED_TYPES` must contain exactly the node types
`task15_reference_graph.json` uses after acceptance, plus any type the Task 15 plan mandates. Do
not pre-add types "we might need" — a speculative entry is a permanent hole. Task 15 widens it by
one commit if it genuinely needs more, and that commit is reviewable.

- [ ] **Step 4: Implement obligation 10 and document it**

Add the check next to obligations 7 and 8, and extend the module's KNOWN LIMITS docstring to say
what the allowlist does and does not constrain — parameters inside an allowlisted node are still
unchecked beyond the absolute-URL rule.

- [ ] **Step 5: Run both suites**

Run: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/ -q` — green.
Run: `cd infrastructure && python scripts/verify-workflows.py` — exit 0.

- [ ] **Step 6: Commit**

```bash
git add infrastructure/scripts/workflow_verifier.py infrastructure/tests/test_verify_workflows_v2_graph_policy.py infrastructure/tests/fixtures/v2_adversarial/
git commit -m "fix(n8n): allowlist node types after acceptance, not only before it"
```

---

### Task 5: Close the registry's second reader

Added 2026-07-29, raised by Task 2's reviewer. Task 2 closed the generation field in
`infrastructure/scripts/workflow_registry.py`, but that is not the only code that reads
`n8n/workflow-registry.json`. `backend/app/services/workflow_targets.py:29`
(`load_event_targets`) parses the same file independently and does:

```python
        if workflow.get("generation") != "v2":
            continue
```

That is the identical silent-skip shape finding #12 was about, and because it never calls
`load_registry`, it inherits none of Task 2's `KNOWN_GENERATIONS` validation or grandfather list.
A misspelled generation silently drops that workflow's webhook target from `targets` instead of
being rejected. No live effect today — the registry has zero v2 entries — but the vulnerability
class survives in a second reader, which is exactly how the original finding escaped notice.

Two readers of one file with independently maintained validation is the root problem; closing the
skip without unifying them just resets the clock.

**Files:**
- Modify: `backend/app/services/workflow_targets.py`
- Test: `backend/tests/` — add a module covering the loader, or extend the existing one if there is one

**Note on lane ownership:** this file lives under `backend/` but is in no other lane's file list —
R1 touches `config.py`, `main.py`, `dependencies.py`, `n8n_internal.py` and `binary_validation.py`
only. Verify that is still true before you start.

**Interfaces:**
- Consumes: `KNOWN_GENERATIONS` and `GRANDFATHERED_V1_FILES` from `infrastructure/scripts/workflow_registry.py`, if they can be imported from the backend; if they cannot, the values must be derived from one shared declaration rather than copied.
- Produces: `load_event_targets` rejects an unknown generation instead of skipping it.

- [ ] **Step 1: Write the failing tests**

```python
def test_unknown_generation_is_rejected_rather_than_skipped(tmp_path):
    """The silent skip is finding #12 in a second reader of the same file."""
    registry = tmp_path / "workflow-registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "workflows": [
                    {
                        "file": "x.json",
                        "generation": "v2-typo",
                        "webhook_paths": ["pwr-v2-smoke"],
                        "event_names": ["pwr.v2.smoke"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="generation"):
        load_event_targets(registry)


def test_grandfathered_v1_entries_are_still_skipped_without_error(tmp_path):
    """v1 entries legitimately have no v2 target; they must not raise."""
    registry = tmp_path / "workflow-registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "workflows": [
                    {"file": "pick-confirmed.json", "generation": "v1", "webhook_paths": []}
                ],
            }
        ),
        encoding="utf-8",
    )
    assert load_event_targets(registry) == {}
```

`workflows` is a **list** of objects — do not write `.values()`.

- [ ] **Step 2: Run to verify they fail**

Expected: the unknown generation is skipped and no `ValueError` is raised.

- [ ] **Step 3: Decide how the two readers share one declaration**

Either import the allowlist from `workflow_registry.py`, or — if the backend cannot import from
`infrastructure/scripts/` — declare it once in a location both can read and have a test that fails
when the two diverge. Do **not** copy the tuple; a copied allowlist is the drift this task exists
to prevent.

- [ ] **Step 4: Reject instead of skipping**

```python
        generation = workflow.get("generation")
        if generation not in KNOWN_GENERATIONS:
            raise ValueError(
                f"{workflow.get('file')}: unknown generation {generation!r}"
            )
        if generation != "v2":
            continue
```

- [ ] **Step 5: Run both suites**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q` — green.
Run: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/ -q` — green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/workflow_targets.py backend/tests/
git commit -m "fix(n8n): reject unknown generations in the registry's second reader"
```

---

## Lane exit gate

- [ ] `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/ -q` — green
- [ ] `cd infrastructure && python scripts/verify-workflows.py` — exit 0, skip list printed
- [ ] `cd n8n/custom-nodes/n8n-nodes-pwr && npm test` — green
- [ ] The `task15_reference_graph.json` fixture is accepted, and all six mutations are rejected with a message naming the right cause
- [ ] Adversarial review: `codex exec --sandbox read-only "<diff brief>"`, focused on: can any graph reach an effect without passing the process gate's true branch; can any generation string still skip a check; does the importer/stager pair now agree on every key; is any CLI output reachable from an exception
- [ ] Update the debt register in `docs/superpowers/parallel/2026-07-23-program-status.md` — mark #3, #12, #13, #16 closed with their commit hashes
- [ ] Record the Task 15 handoff obligations: the smoke workflow's registry path must match `^/webhook/[a-z0-9][a-z0-9-]*$` (no underscores), `host` is mandatory for v2 target validation and needs a concrete value such as `backend` in `allowed_target_hosts`, and the verifier must be re-run against the real workflow once it exists
