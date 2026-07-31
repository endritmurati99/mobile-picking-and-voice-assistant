"""The single declaration of the registry's generation allowlist.

This module exists because the allowlist has exactly TWO readers that run in
two different filesystem layouts:

* `infrastructure/scripts/workflow_registry.py` (`load_registry`) always runs
  from a checkout of this repository, with the repo root importable.
* `backend/app/services/workflow_targets.py` (`load_event_targets`) runs
  inside the backend image, where `backend/app/` is the ONLY thing that ships
  (`backend/Dockerfile`: `COPY app/ ./app/`; compose mounts only
  `./backend/app:/app/app:ro`). Nothing named `infrastructure/` exists there.

So the declaration lives on the side that ships in both trees -- inside
`backend/app/` -- and the infrastructure script imports it from here. The
reverse direction cannot work: it made `uvicorn app.main:app` fail at import
time with `ModuleNotFoundError: No module named 'infrastructure'`, because
`app.dependencies` imports `load_event_targets` at module scope.

Do NOT retype either value anywhere else. A copy is exactly the drift that
let an unknown generation string silently skip every v2 check in one reader
while the other had already learned to reject it.
"""

KNOWN_GENERATIONS = ("v1", "v2")

# v1 ist eingefroren. Diese Dateien existierten, bevor die v2-Kette gebaut
# wurde, und duerfen bleiben; neue v1-Eintraege sind verboten, weil v1 keine
# der v2-Pruefungen durchlaeuft. Ein offenes Generationsfeld war ein
# Fail-open: "v2-typo" hat jede einzelne v2-Pruefung stillschweigend
# uebersprungen.
GRANDFATHERED_V1_FILES = frozenset({
    "batch-confirmed.json",
    "daily-report.json",
    "error-trigger.json",
    "pick-confirmed.json",
    "quality-alert-ai-evaluation.json",
    "quality-alert-created.json",
    "shortage-reported.json",
    "voice-exception-query.json",
})
