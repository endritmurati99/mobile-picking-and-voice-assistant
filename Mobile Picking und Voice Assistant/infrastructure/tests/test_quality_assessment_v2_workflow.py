"""Der committete generation-v2 Workflow: `quality-assessment-v2.json`.

Diese Datei hiess bis zur Umstellung `test_foundation_smoke_workflow.py` und
haengte an `n8n/workflows/pwr-foundation-smoke-v2.json`. Der Smoke-Workflow war
das Geruest, mit dem der v2-Vertrag ueberhaupt erst einmal an einem echten,
committeten Dokument bewiesen wurde -- er war `test_only: true`, hat einen
synthetischen ZPL-Artefakt-Upload gefahren und nie in Produktion laufen duerfen.
Mit Commit b0cbbc6 ("docs(spec): design the v2 quality chain that finally uses
the event platform") wurde er absichtlich geloescht und durch die produktive
v2-Qualitaetskette ersetzt. Die Tests wurden damals nicht nachgezogen; das holt
diese Datei nach.

Der Zweck bleibt unveraendert und ist der Grund, warum hier nichts einfach
geloescht wurde:

 1. `verify-workflows.py` darf nicht gruen sein, weil `verify_v2_workflow` auf
    kein einziges echtes Dokument angewendet wurde. Ein Gate, das nur gegen
    Fixtures gelaufen ist, hat niemand arbeiten sehen.
 2. Jeder Ablehnungstest mutiert das committete Dokument an genau EINER Stelle,
    prueft die RICHTIGE Ursache in der Fehlermeldung, und das unmutierte
    Dokument wird in `test_the_committed_workflow_verifies_clean` erneut sauber
    verifiziert -- eine Mutation, die zufaellig aus einem anderen Grund
    abgelehnt wird, gilt nicht als Beweis.
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
WORKFLOW_FILE = "quality-assessment-v2.json"
WORKFLOW_PATH = ROOT / "n8n" / "workflows" / WORKFLOW_FILE
ROUTER_SOURCE = ROOT / "backend" / "app" / "routers" / "n8n_v2.py"

ACCEPTANCE_NODE = "PWR Signed Acceptance"
# Der Effekt-Knoten hinter dem Process-Gate. Im Smoke war das der
# Artefakt-Upload ("PWR Signed Artifact"); die Qualitaetskette ruft an dieser
# Stelle die Bewertung auf.
EFFECT_NODE = "PWR Signed Assessment"
PROCESS_GATE_NODE = "If Process"
FIRST_EFFECT_BUILDER = "Build Assessment Request"


def _verify_workflows_module():
    """Importiert den CLI-Runner trotz seines Bindestrich-Dateinamens.

    Die Spec, gegen die hier geprueft wird, baut dieselbe `_v2_spec_dict`, die
    auch das Produktions-Gate benutzt. Ein hier handgeschriebenes Aequivalent
    wuerde bedeuten: ein Feld, das der Runner nicht mehr (oder anders) weiter-
    gibt, laesst diese Suite gruen und das echte Gate blind.
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


def _v2_entries():
    return [
        item for item in load_registry(REGISTRY_PATH).workflows if item.generation == "v2"
    ]


# --- der Registry-Eintrag --------------------------------------------------


def test_registry_entry_shape():
    # Frueher: die Shape des Smoke-Eintrags (test_only=True,
    # production_activation=False). Der Webhook-Pfad "quality-assessment-v2"
    # ist derselbe geblieben -- die Kette hat den Smoke an genau dieser
    # Ingress-Stelle abgeloest.
    entry = load_registry(REGISTRY_PATH).by_file(WORKFLOW_FILE)
    assert entry.name == "Quality Assessment v2"
    assert entry.generation == "v2"
    assert entry.authentication == "native_header_hmac"
    assert entry.managed is True
    assert entry.test_only is False
    assert entry.event_names == ("quality.assessment.requested.v1",)
    assert entry.webhook_paths == ("quality-assessment-v2",)
    assert entry.allowed_target_hosts == ("backend",)


def test_a_test_only_entry_can_never_be_activated_in_production():
    """`production_activation: false` ist ein Vertrag, kein Kommentar.

    Frueher haeng dieser Test am Smoke-Workflow, dem einzigen test_only-Eintrag
    den es je gab. Seit dessen Ruecknahme fuehrt die Registry keinen
    test_only-Eintrag mehr -- die Regel selbst gilt aber unveraendert fuer den
    naechsten. Also wird sie hier an einem synthetischen Eintrag geprueft
    (der Guard, den `import-workflows.sh` vor jeder Aktivierung ruft), plus
    die Positivprobe, dass der echte v2-Workflow sehr wohl aktivierbar ist.
    """
    from infrastructure.scripts.stage_workflow import (
        ActivationError,
        assert_activatable,
    )

    registry = load_registry(REGISTRY_PATH)
    assert registry.test_only_files() == ()

    # Positivprobe: der produktive v2-Workflow steht in der Aktivierungsreihe.
    entry = registry.by_file(WORKFLOW_FILE)
    assert entry.production_activation is True
    assert WORKFLOW_FILE in registry.activation_order()
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

    # Negativprobe: ein test_only-Eintrag faellt am selben Guard durch.
    with pytest.raises(ActivationError, match="production_activation is false"):
        assert_activatable(
            {
                "file": "some-future-smoke-v2.json",
                "managed": True,
                "production_activation": False,
                "test_only": True,
                "generation": "v2",
            },
            credentials_verified=True,
            duplicate=False,
        )


def test_credential_bindings_name_nodes_that_exist_and_cover_every_signed_node():
    """Ein Binding auf einen nicht existierenden Knoten ist ein Credential, das
    nie angehaengt wird; ein signierter Knoten ohne Binding ist ein Knoten, der
    ohne eines laeuft. `stage_workflow` faellt beim ersten Fall geschlossen um,
    den zweiten faengt nichts -- also hier.

    Frueher nur fuer den Smoke; jetzt ueber JEDEN v2-Eintrag der Registry, damit
    das Verschwinden eines einzelnen Workflows die Pruefung nicht wieder
    mitnimmt.
    """
    entries = _v2_entries()
    assert entries, "vacuous: die Registry fuehrt keinen v2-Workflow"

    for entry in entries:
        workflow = json.loads(
            (ROOT / "n8n" / "workflows" / entry.file).read_text(encoding="utf-8")
        )
        node_names = {node["name"] for node in workflow["nodes"]}
        bound = {binding.node for binding in entry.credential_bindings}

        for binding in entry.credential_bindings:
            assert binding.node in node_names, (entry.file, binding.node)

        signed_nodes = {
            node["name"]
            for node in workflow["nodes"]
            if node["type"].endswith(".pwrSignedHttpRequest")
        }
        assert signed_nodes, f"vacuous: {entry.file} hat keinen signierten Knoten"
        assert signed_nodes <= bound, sorted(signed_nodes - bound)
        assert {"Webhook", "PWR Signature Gate"} <= bound, entry.file


# --- die lease-gebundene Artefakt-Route ------------------------------------


def _backend_artifact_route():
    """Die Artefakt-Route SO WIE DAS BACKEND SIE MOUNTET, aus der Router-Quelle
    gelesen statt hier wiederholt.

    Der Plan (Task 15) zeigt diesen Pfad noch OHNE das `/leases/{token}/`-
    Segment -- er ist aelter als Finding #5b, dessen Behebung den Artefakt-
    Endpunkt an das Lease gebunden hat. Den Pfad hier als Literal zu
    wiederholen haette die veraltete Form des Plans unbemerkt sitzen lassen;
    ihn aus `backend/app/routers/n8n_v2.py` abzuleiten heisst: an dem Tag, an
    dem die Backend-Route sich aendert, faellt dieser Test.
    """
    source = ROUTER_SOURCE.read_text(encoding="utf-8")
    prefix = re.search(r'APIRouter\(prefix="(?P<p>[^"]+)"\)', source).group("p")
    v2_router_mount = "/api"  # app/main.py mountet routers/n8n_v2.py unter "/api"
    match = re.search(
        r'@router\.post\(\s*\n\s*"(?P<a>/instances/[^"]*)"\s*\n\s*"(?P<b>[^"]*artifacts[^"]*)"',
        source,
    )
    assert match, "could not locate the artifact route in the router source"
    return v2_router_mount + prefix + match.group("a") + match.group("b")


def test_the_artifact_route_stays_lease_bound_and_registered_templates_match_it():
    """Finding #5b bleibt zugenagelt, auch ohne Artefakt-Workflow.

    Frueher standen hier drei Tests, die alle am Artefakt-Knoten des Smoke
    hingen (registriertes Template == Backend-Route, aufgeloester Knoten-Target
    == Backend-Route, jedes variable Segment in encodeURIComponent). Kein
    heutiger Workflow laedt Artefakte hoch, und die Registry fuehrt kein
    `artifact_path_templates` mehr -- die beiden knotenbezogenen Tests haben
    damit kein Subjekt mehr.

    Was bleibt, gilt weiter: die Backend-Route MUSS lease-gebunden bleiben, und
    sobald wieder ein Eintrag ein Artefakt-Template registriert, muss es Segment
    fuer Segment die Backend-Route sein. Beides steht hier, damit der Tag, an
    dem ein Artefakt-Workflow zurueckkommt, nicht ohne Netz stattfindet.
    """
    backend_route = _backend_artifact_route()
    assert "/leases/{processing_lease_token}/" in backend_route, backend_route

    registered = [
        (entry.file, template)
        for entry in load_registry(REGISTRY_PATH).workflows
        for template in entry.artifact_path_templates
    ]
    for file_name, template in registered:
        # Das einzige, was ein Template gegenueber der Route festlegen darf,
        # ist die Artefakt-Art; alles andere muss identisch sein.
        stripped = re.sub(r"/artifacts/[^/]+$", "/artifacts/{artifact_kind}", template)
        assert stripped == backend_route, (file_name, template)


def test_no_signed_target_carries_an_unwrapped_expression_segment():
    """Das signierte Target ist backendseitig `request.scope["raw_path"]`, und
    `verify_signature` weist Query-Strings rundweg ab. Ein Laufzeitwert, der ein
    "/" oder "?" in den Pfad schmuggelt, wuerde also die signierten Bytes
    veraendern statt sauber zu scheitern. encodeURIComponent ist das, was das
    statisch verhindert.

    Frueher nur fuer die vier Segmente des Smoke-Artefakt-Targets. Heute traegt
    kein signierter Knoten mehr ein dynamisches Segment -- der Test haelt genau
    das fest UND die Regel fuer den ersten, der wieder eines bekommt.
    """
    checked = 0
    for entry in _v2_entries():
        workflow = json.loads(
            (ROOT / "n8n" / "workflows" / entry.file).read_text(encoding="utf-8")
        )
        for node in workflow["nodes"]:
            if not node["type"].endswith(".pwrSignedHttpRequest"):
                continue
            target = node["parameters"]["target"]
            checked += 1
            if not target.startswith("="):
                # Statisches Literal: kein Ausdruck, nichts zu wrappen.
                assert "{{" not in target, (entry.file, node["name"], target)
                continue
            for expression in re.findall(r"\{\{.*?\}\}", target):
                assert re.fullmatch(
                    r"\{\{\s*encodeURIComponent\([^{}]+\)\s*\}\}", expression
                ), (entry.file, node["name"], expression)
    assert checked, "vacuous: kein signierter Knoten geprueft"


def test_the_committed_v2_workflows_carry_no_synthetic_or_shell_nodes():
    """Frueher: der Smoke durfte GENAU einen synthetischen ZPL-Body haben und
    sonst nichts Echtes. Der Modus `bodyMode=literalUtf8` ist an einen
    reviewten `test_only: true`-Eintrag gebunden -- es gibt keinen mehr, also
    darf ihn heute kein committeter Workflow benutzen.

    Die frueher hier stehende Substring-Suche ueber den JSON-Blob ("dhl", "ups",
    "gls") ist ersetzt: sie war unscharf (Teilwort-Treffer) und pruefte den
    Smoke-Charakter, nicht eine Richtlinie. Was bleibt, ist die Richtlinie:
    kein Shell- und kein LLM-Knoten im Workflow selbst -- die Kette ruft das
    Modell ueber das Backend, nie direkt aus n8n heraus.
    """
    forbidden_types = ("executeCommand", "langchain", "openai")
    for entry in _v2_entries():
        workflow = json.loads(
            (ROOT / "n8n" / "workflows" / entry.file).read_text(encoding="utf-8")
        )
        for node in workflow["nodes"]:
            for forbidden in forbidden_types:
                assert forbidden.lower() not in node["type"].lower(), (
                    entry.file,
                    node["name"],
                    node["type"],
                )
            assert (node.get("parameters") or {}).get("bodyMode") != "literalUtf8", (
                entry.file,
                node["name"],
            )


# --- accept ---------------------------------------------------------------


def test_the_committed_workflow_verifies_clean():
    assert verify_v2_workflow(_workflow(), _registry_spec()) == []


def test_the_production_gate_actually_applies_v2_checks_to_this_workflow():
    """Nicht vacuous: der Runner muss diese Datei als GEPRUEFT melden, nicht als
    uebersprungen.

    Vor Task 15 war jeder Registry-Eintrag v1, also hat `run_v2_checks` alle
    uebersprungen und keine Fehler gemeldet -- ein gruenes Gate, das nichts
    bewiesen hatte.
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
# Je eine Mutation. Die Behauptung liegt auf der URSACHE, nie bloss auf
# "errors != []" -- eine Ablehnung aus dem falschen Grund ist kein Beweis, dass
# der gemeinte Guard funktioniert.


def _reject(mutate):
    workflow = _workflow()
    mutate(workflow)
    errors = verify_v2_workflow(workflow, _registry_spec())
    assert errors, "the mutated workflow was accepted"
    return errors


def test_reject_when_the_process_gate_is_removed():
    def mutate(workflow):
        workflow["nodes"] = [
            node for node in workflow["nodes"] if node["name"] != PROCESS_GATE_NODE
        ]
        workflow["connections"]["Accepted Response"] = {
            "main": [[{"node": FIRST_EFFECT_BUILDER, "type": "main", "index": 0}]]
        }
        del workflow["connections"][PROCESS_GATE_NODE]

    errors = _reject(mutate)
    assert any("gate on process == true" in error for error in errors), errors


def test_reject_when_the_process_gate_operator_is_inverted():
    """Weit gefaehrlicher als ein fehlendes Gate: jeder Effekt laeuft dann genau
    dann, wenn das Backend process == false geantwortet hat.
    """

    def mutate(workflow):
        conditions = _node(workflow, PROCESS_GATE_NODE)["parameters"]["conditions"]
        conditions["boolean"][0]["operation"] = "notEqual"

    errors = _reject(mutate)
    assert any("gate on process == true" in error for error in errors), errors


def test_reject_when_a_signed_node_points_at_a_host_outside_the_allowlist():
    def mutate(workflow):
        _node(workflow, EFFECT_NODE)["parameters"]["host"] = "attacker.example.net"

    errors = _reject(mutate)
    assert any(
        "resolved host 'attacker.example.net' is not in allowed_target_hosts" in error
        for error in errors
    ), errors


def test_reject_when_a_signed_node_is_repointed_at_an_unregistered_route():
    """Frueher war das die Variante "Artefakt-Target auf eine andere Route
    umgebogen". Der Artefakt-Knoten ist weg, die Regel nicht: ein signierter
    Knoten darf ausschliesslich auf einen in der Registry eingetragenen Ziel-
    pfad zeigen.
    """

    def mutate(workflow):
        _node(workflow, EFFECT_NODE)["parameters"][
            "target"
        ] = "/api/internal/n8n/v2/assessments/other"

    errors = _reject(mutate)
    assert any("is not a registered target" in error for error in errors), errors


def test_reject_when_a_wait_node_opens_a_webhook_resume_ingress():
    """Ein `resume: webhook`-Wait-Knoten praegt eine unauthentifizierte URL, die
    diese Ausfuehrung mitten im Lauf fortsetzt -- ein zweiter Ingress, der nie
    durch das Signature Gate geht.

    Frueher mutierte dieser Test den Wait-Knoten des Smoke ("Smoke Wait").
    Heute hat kein committeter Workflow einen Wait-Knoten, deshalb wird einer
    eingefuegt: der Guard scannt alle Knoten unabhaengig von ihrer Position,
    also bleibt die gepruefte Ursache dieselbe.
    """

    def mutate(workflow):
        workflow["nodes"].append(
            {
                "name": "Injected Wait",
                "type": "n8n-nodes-base.wait",
                "typeVersion": 1,
                "position": [0, 0],
                "parameters": {"resume": "webhook"},
            }
        )

    errors = _reject(mutate)
    assert any("second ingress" in error for error in errors), errors


def test_reject_when_an_effect_is_moved_onto_a_side_path_around_the_process_gate():
    def mutate(workflow):
        workflow["connections"]["Accepted Response"]["main"][0].append(
            {"node": FIRST_EFFECT_BUILDER, "type": "main", "index": 0}
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
    """Der Modus fuer synthetische Bytes ist auf einen reviewten
    `test_only: true`-Eintrag beschraenkt; produktive Workflows muessen
    binaeren oder JSON-Input verwenden.

    Frueher: der Smoke HATTE einen literalUtf8-Knoten, und der Test drehte
    stattdessen `test_only` in der Spec auf False. Heute gibt es keinen solchen
    Knoten mehr, also wird er hineinmutiert -- die Spec bleibt die echte
    (test_only=False), was den Beweis eher schaerft als schwaecht.
    """

    def mutate(workflow):
        _node(workflow, EFFECT_NODE)["parameters"]["bodyMode"] = "literalUtf8"

    errors = _reject(mutate)
    assert any("bodyMode=literalUtf8" in error for error in errors), errors


def test_reject_when_an_unlisted_node_type_runs_after_acceptance():
    def mutate(workflow):
        _node(workflow, "Build Success Callback")[
            "type"
        ] = "n8n-nodes-base.executeCommand"

    errors = _reject(mutate)
    assert any("not permitted after acceptance" in error for error in errors), errors


def test_the_mutations_above_are_single_edits_of_the_committed_document():
    """Das Beweismaterial absichern: jede Ablehnung muss aus EINER Aenderung am
    echten Dokument kommen, sonst sagt "der Verifier hat es abgelehnt" nichts
    darueber, welcher Guard gefeuert hat.
    """
    baseline = _workflow()
    mutated = deepcopy(baseline)
    _node(mutated, EFFECT_NODE)["parameters"]["host"] = "attacker.example.net"
    assert mutated != baseline
    assert json.loads(WORKFLOW_PATH.read_text(encoding="utf-8")) == baseline
    # ... und das unangetastete Dokument ist weiterhin sauber, die
    # Wiederherstellung also echt.
    assert verify_v2_workflow(baseline, _registry_spec()) == []
