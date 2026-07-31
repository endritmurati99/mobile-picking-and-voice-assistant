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
(`load_registry`) is the first. Both read ONE declaration of the generation
allowlist, `app.services.workflow_generations` — a copy is exactly the drift
that let an unknown generation string silently skip every v2 check in this
reader while `load_registry` had already learned to reject it (finding #12,
second reader).

That declaration lives under `backend/app/` and NOT under
`infrastructure/scripts/` because this module must import cleanly inside the
backend image, where `backend/app/` is the only tree that ships and nothing
named `infrastructure/` exists. Nothing in this module may reach above
`backend/` — `app.dependencies` imports `load_event_targets` at module scope,
so any such import failure takes down `uvicorn app.main:app` at startup.
`backend/tests/test_workflow_targets.py` guards that with an import performed
in a reproduction of the container layout.
"""
import json
import re
from pathlib import Path

from app.models.events import EVENT_NAMES
from app.services.workflow_generations import KNOWN_GENERATIONS

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
