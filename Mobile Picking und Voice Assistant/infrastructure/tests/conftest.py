"""Import path for every infrastructure test module.

Two entries are needed because these tests import their subjects both ways:
the repo root, for the dotted `infrastructure.scripts.*` form, and
`infrastructure/scripts` itself, for the modules that scripts import as bare
siblings. Without this, `python -m pytest ../infrastructure/tests/` (the test
command every plan in this programme documents) fails collection on every
module with `ModuleNotFoundError: No module named 'infrastructure'`.
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

for _entry in (_REPO_ROOT, _REPO_ROOT / "infrastructure" / "scripts"):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))
