"""Importing workflow_registry must not rearrange anyone else's imports.

`workflow_registry.py` has to reach into `backend/app/services/` for the one
declaration of the generation allowlist -- that direction is deliberate and
documented (the backend image ships `backend/app/` and no `infrastructure/`
at all, so the declaration cannot live on the infrastructure side).

The old way of reaching across was `sys.path.insert(0, <repo>/backend)`,
which is a process-wide side effect for a single module lookup. `backend/`
contains `tests/` WITH an `__init__.py`, so it is an importable package;
`infrastructure/tests/` has none. Putting `backend/` at position 0 therefore
makes the name `tests` resolve to `backend/tests` for the whole process, in
front of everything -- including the directory the process was started from.

R3's own ledger checked the opposite direction (does anything shadow `app`?)
and correctly found nothing. It did not check this direction. Today both
suites are green, and pytest happens to keep the two trees' module names
apart (`tests.test_x` for the backend, bare `test_x` for infrastructure), so
nothing is broken -- but that is a property of how pytest names modules, not
a property this repository states or enforces anywhere. Any infrastructure
module doing `import tests.…`, or any future runner collecting both trees
differently, silently gets `backend/tests`.

The fix is to stop needing the side effect at all: load the one module by
file path. These tests pin that the side effect is gone.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _probe(body: str) -> subprocess.CompletedProcess:
    """Run `body` in a fresh interpreter whose only path entry is the repo root.

    A subprocess is required, not a niceness: this session's pytest has
    already put `backend/` on `sys.path` (it collects `backend/tests/`), so
    an in-process assertion would be measuring pytest, not the module.
    """
    source = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        {textwrap.indent(textwrap.dedent(body), " " * 8).lstrip()}
    """)
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )


def test_importing_workflow_registry_does_not_put_backend_on_sys_path():
    result = _probe(f"""
        import infrastructure.scripts.workflow_registry as wr
        assert wr.KNOWN_GENERATIONS == ("v1", "v2"), wr.KNOWN_GENERATIONS
        assert wr.GRANDFATHERED_V1_FILES, "allowlist must still be reachable"
        backend = {str(ROOT / "backend")!r}
        leaked = [entry for entry in sys.path if entry == backend]
        assert not leaked, (
            "importing workflow_registry left " + backend + " on sys.path; "
            "that makes `tests` resolve to backend/tests process-wide"
        )
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_importing_workflow_registry_does_not_make_tests_resolve_to_backend():
    """The concrete hazard, named: `tests` must not become backend/tests."""
    result = _probe("""
        import importlib.util
        before = importlib.util.find_spec("tests")
        assert before is None, before
        import infrastructure.scripts.workflow_registry  # noqa: F401
        after = importlib.util.find_spec("tests")
        assert after is None, (
            "`tests` became importable as a side effect of importing "
            "workflow_registry; it resolves to " + str(after.origin)
        )
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_ordinary_import_still_wins_when_backend_is_importable():
    """Removing the side effect must not fork the declaration into two objects.

    The first attempt at this fix loaded the file by path unconditionally and
    broke backend/tests/test_workflow_targets.py's identity assertion
    (`workflow_targets.KNOWN_GENERATIONS is registry_known_generations`):
    same source file, two module objects. So when `backend/` is importable,
    the ordinary import must win and both readers must end up holding the
    SAME object -- the file-path load is a fallback for the bare
    infrastructure-only run, not the normal route.
    """
    result = _probe(f"""
        sys.path.insert(0, {str(ROOT / "backend")!r})
        from app.services.workflow_generations import KNOWN_GENERATIONS as declared
        from infrastructure.scripts.workflow_registry import KNOWN_GENERATIONS as via_registry
        assert via_registry is declared, (
            "the registry holds a SECOND copy of the allowlist; identity is "
            "what catches drift before the contents diverge"
        )
    """)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_allowlist_is_still_the_backend_declaration_not_a_copy():
    """Narrowing the import must not turn into retyping the values.

    The whole point of the cross-tree reach is that there is exactly ONE
    declaration. A local copy would make these tests pass and reintroduce
    the drift the single declaration exists to prevent.
    """
    registry_source = (
        ROOT / "infrastructure" / "scripts" / "workflow_registry.py"
    ).read_text(encoding="utf-8")
    assert "workflow_generations" in registry_source
    for literal in ("quality-alert-created.json", '"v1", "v2"', "'v1', 'v2'"):
        assert literal not in registry_source, (
            f"{literal!r} is declared in backend/app/services/"
            "workflow_generations.py and must not be retyped here"
        )
