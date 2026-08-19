"""Lane C: Rueckfrage-Text der Sprachausgabe muss fuer JEDE moegliche
Intent-Aktion auf Deutsch vorliegen.

Vorgeschichte (Audit 2026-08-19): `_ACTION_DE` in
app/routers/voice.py::recognize_speech war unvollstaendig. Fehlte ein
Eintrag, fiel die Rueckfrage auf den rohen Intent-Bezeichner zurueck,
z. B. "Ich habe confirm_all verstanden. Richtig?" statt einer
verstaendlichen deutschen Formulierung.

Dieser Test extrahiert den Dict-Literal `_ACTION_DE` per AST direkt aus
dem Quelltext (er ist eine lokale Variable in der Endpoint-Funktion, daher
nicht importierbar) und vergleicht seine Schluessel gegen das vollstaendige
Aktions-Vokabular der Intent-Engine (PRIORITY_ORDER + abort/check_digit/
quantity, die ausserhalb von PRIORITY_ORDER erzeugt werden).
"""

import ast
from pathlib import Path

from app.services.intent_engine import PRIORITY_ORDER, EXTERNAL_INTENT_LABELS

VOICE_ROUTER_PATH = Path(__file__).resolve().parents[1] / "app" / "routers" / "voice.py"

# Aktionen, die ausserhalb von PRIORITY_ORDER im Code entstehen koennen und
# daher ebenfalls eine deutsche Rueckfrage brauchen (siehe intent_engine.py:
# _apply_negation_guard -> "abort", recognize_intent -> "check_digit"/"quantity").
EXTRA_NON_PRIORITY_ACTIONS = {"abort", "check_digit", "quantity"}


def _extract_action_de_dict() -> dict[str, str]:
    """Liest _ACTION_DE direkt aus dem Quelltext von voice.py per AST aus."""
    source = VOICE_ROUTER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(VOICE_ROUTER_PATH))

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "_ACTION_DE" in targets and isinstance(node.value, ast.Dict):
                result = {}
                for key_node, value_node in zip(node.value.keys, node.value.values):
                    key = ast.literal_eval(key_node)
                    value = ast.literal_eval(value_node)
                    result[key] = value
                return result

    raise AssertionError("_ACTION_DE nicht in voice.py gefunden -- Struktur geaendert?")


def _all_known_actions() -> set[str]:
    """Vollstaendiges Aktions-Vokabular: deterministische Engine + LLM-Fallback
    + die per Verneinungs-Guard/Kontext erzeugten Sonderaktionen."""
    return set(PRIORITY_ORDER) | set(EXTERNAL_INTENT_LABELS) | EXTRA_NON_PRIORITY_ACTIONS


def test_action_de_covers_all_known_intent_actions():
    action_de = _extract_action_de_dict()
    known_actions = _all_known_actions()

    missing = known_actions - action_de.keys()
    assert not missing, (
        f"Fehlende deutsche Rueckfrage-Texte fuer Aktionen: {sorted(missing)}. "
        "Ohne Eintrag faellt die Rueckfrage auf den rohen englischen Bezeichner zurueck."
    )


def test_action_de_values_are_non_empty_german_strings():
    action_de = _extract_action_de_dict()
    for action, text in action_de.items():
        assert isinstance(text, str) and text.strip(), (
            f"Leerer/ungueltiger deutscher Text fuer Aktion '{action}'"
        )
        # Grobe Absicherung gegen versehentlichen Rueckfall auf den rohen
        # Bezeichner (z. B. _ACTION_DE["confirm_all"] = "confirm_all").
        assert text != action, (
            f"Deutscher Text fuer '{action}' ist identisch mit dem rohen Bezeichner"
        )
