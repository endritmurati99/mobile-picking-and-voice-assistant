"""Event-to-webhook-target map loaded from the sole reviewed registry.

No Python constant repeats the event-to-path mapping: the only source is
`n8n/workflow-registry.json` (schema v1). Only `generation: "v2"` workflows
contribute targets; every rule here is an allowlist and every violation
fails closed with `ValueError` at construction time.

COMPATIBILITY CONSTRAINT for future registry entries (Task 15's smoke
workflow included): the path allowlist is lowercase letters, digits and
hyphens ONLY — underscores are deliberately rejected. Name v2 webhook paths
kebab-case (e.g. `quality-assessment-v2`), never snake_case.

This is the registry's SECOND reader. `infrastructure/scripts/workflow_registry.py`
(`load_registry`) is the first, and it is the one that owns `KNOWN_GENERATIONS`.
Do not redeclare that tuple here — a copy is exactly the drift that let an
unknown generation string silently skip every v2 check in this reader while
`load_registry` had already learned to reject it (finding #12, second reader).
Import it from the single declaration instead, the same way
`infrastructure/scripts/verify-workflows.py` reaches its sibling modules.
"""
import json
import re
import sys
from pathlib import Path

from app.models.events import EVENT_NAMES

# `infrastructure/scripts/` has no `__init__.py`; it is imported as an
# implicit namespace package the same way infrastructure's own CLI entry
# points (e.g. verify-workflows.py) reach their sibling modules: put the
# repo root on sys.path, then import by dotted path.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from infrastructure.scripts.workflow_registry import KNOWN_GENERATIONS  # noqa: E402

# Same allowlisted charset the signed transport enforces on full targets.
_ALLOWED_PATH = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def load_event_targets(registry_path: Path) -> dict[str, str]:
    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "v1":
        raise ValueError("unsupported workflow registry schema")
    targets: dict[str, str] = {}
    for workflow in raw.get("workflows") or []:
        generation = workflow.get("generation")
        if generation not in KNOWN_GENERATIONS:
            raise ValueError(
                f"{workflow.get('file')}: unknown generation {generation!r}"
            )
        if generation != "v2":
            continue
        paths = workflow.get("webhook_paths") or []
        events = workflow.get("event_names") or []
        if len(paths) != 1:
            raise ValueError(f"{workflow.get('file')}: v2 requires one webhook path")
        if not _ALLOWED_PATH.fullmatch(str(paths[0])):
            raise ValueError(
                f"{workflow.get('file')}: v2 webhook path must match "
                f"{_ALLOWED_PATH.pattern}"
            )
        target = f"/webhook/{paths[0]}"
        for event_name in events:
            if event_name in targets:
                raise ValueError(f"duplicate v2 event target: {event_name}")
            targets[event_name] = target
    unknown = set(targets) - EVENT_NAMES
    if unknown:
        raise ValueError(f"unknown v2 event target: {sorted(unknown)}")
    return targets
