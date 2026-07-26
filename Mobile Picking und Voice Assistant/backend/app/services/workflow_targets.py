"""Event-to-webhook-target map loaded from the sole reviewed registry.

No Python constant repeats the event-to-path mapping: the only source is
`n8n/workflow-registry.json` (schema v1). Only `generation: "v2"` workflows
contribute targets; every rule here is an allowlist and every violation
fails closed with `ValueError` at construction time.
"""
import json
import re
from pathlib import Path

from app.models.events import EVENT_NAMES

# Same allowlisted charset the signed transport enforces on full targets.
_ALLOWED_PATH = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def load_event_targets(registry_path: Path) -> dict[str, str]:
    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "v1":
        raise ValueError("unsupported workflow registry schema")
    targets: dict[str, str] = {}
    for workflow in raw.get("workflows") or []:
        if workflow.get("generation") != "v2":
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
