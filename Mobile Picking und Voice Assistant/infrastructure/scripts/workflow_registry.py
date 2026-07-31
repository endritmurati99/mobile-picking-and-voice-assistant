from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_REGISTRY_PATH = _REPO_ROOT / "n8n" / "workflow-registry.json"

# The generation allowlist has two readers in two different runtimes: this
# module (always in a repo checkout) and backend/app/services/workflow_targets.py
# (inside the backend image, where only backend/app/ ships and there is no
# `infrastructure/` at all). The single declaration therefore lives on the side
# that exists in BOTH trees, and this side -- which always has the repo -- is
# the one that reaches across. See backend/app/services/workflow_generations.py.
#
# The reach-across no longer mutates sys.path. It used to be
# `sys.path.insert(0, <repo>/backend)` -- a process-wide side effect for a
# single module lookup, at position 0, in front of everything including the
# directory the process was started from. `backend/` contains a `tests/`
# PACKAGE (it has an `__init__.py`; `infrastructure/tests/` has none), so
# merely importing this module made the bare name `tests` resolve to
# `backend/tests` for the rest of the process. Nothing depends on that today
# and both suites are green, but only because pytest happens to name the two
# trees' test modules differently -- a property of the runner, not one this
# repository states or enforces anywhere.
#
# Two paths, in this order, and the order is the point:
#
# 1. The ordinary import first, so that when `backend/` IS importable (the
#    backend suite, the combined run, anything running backend code) both
#    readers get the SAME module object out of sys.modules. That identity is
#    itself a guard -- backend/tests/test_workflow_targets.py asserts
#    `workflow_targets.KNOWN_GENERATIONS is registry_known_generations` to
#    catch a future copy before its contents can drift -- and loading by file
#    path unconditionally would have quietly broken it by producing a second
#    module object.
# 2. Only if `app` is genuinely not importable (an infrastructure-only run
#    from a bare checkout) fall back to loading the single declaration
#    straight off disk. Still one declaration, still no path entry, so there
#    is nothing left to shadow.
#
# Pinned by infrastructure/tests/test_workflow_registry_import_isolation.py.
_GENERATIONS_MODULE = "app.services.workflow_generations"
_GENERATIONS_PATH = (
    _REPO_ROOT / "backend" / "app" / "services" / "workflow_generations.py"
)


def _load_generations():
    try:
        return importlib.import_module(_GENERATIONS_MODULE)
    except ModuleNotFoundError:
        pass
    spec = importlib.util.spec_from_file_location(
        "pwr_workflow_generations", _GENERATIONS_PATH
    )
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable
        raise ImportError(f"cannot load generation allowlist from {_GENERATIONS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_generations = _load_generations()
GRANDFATHERED_V1_FILES = _generations.GRANDFATHERED_V1_FILES
KNOWN_GENERATIONS = _generations.KNOWN_GENERATIONS

__all__ = [
    "GRANDFATHERED_V1_FILES",
    "KNOWN_GENERATIONS",
    "CredentialBinding",
    "WorkflowSpec",
    "WorkflowRegistry",
    "DEFAULT_REGISTRY_PATH",
    "load_registry",
    "main",
]


@dataclass(frozen=True)
class CredentialBinding:
    node: str
    credential_type: str
    logical_name: str


@dataclass(frozen=True)
class WorkflowSpec:
    file: str
    name: str
    generation: str
    event_names: tuple[str, ...]
    webhook_paths: tuple[str, ...]
    callback_paths: tuple[str, ...]
    authentication: str
    managed: bool
    production_activation: bool
    test_only: bool
    activation_order: int | None
    allowed_target_hosts: tuple[str, ...]
    credential_bindings: tuple[CredentialBinding, ...]
    # Registered {field} artifact-path templates (see workflow_verifier.py's
    # verify_v2_workflow), e.g. "/api/internal/n8n/v2/artifacts/{event_id}".
    # Empty for every current (v1) workflow.
    artifact_path_templates: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowRegistry:
    credentials: dict[str, str]
    workflows: tuple[WorkflowSpec, ...]

    def by_file(self, name: str) -> WorkflowSpec:
        matches = [item for item in self.workflows if item.file == name]
        if len(matches) != 1:
            raise KeyError(name)
        return matches[0]

    def managed_files(self) -> tuple[str, ...]:
        return tuple(
            item.file
            for item in sorted(
                (item for item in self.workflows if item.managed),
                key=lambda item: item.activation_order or 10_000,
            )
        )

    def activation_order(self) -> tuple[str, ...]:
        return tuple(
            item.file
            for item in sorted(
                (
                    item
                    for item in self.workflows
                    if item.managed and item.production_activation
                ),
                key=lambda item: item.activation_order or 10_000,
            )
        )

    def test_only_files(self) -> tuple[str, ...]:
        return tuple(
            item.file for item in self.workflows if item.managed and item.test_only
        )

    def required_credentials(self, file_name: str) -> tuple[CredentialBinding, ...]:
        return self.by_file(file_name).credential_bindings

    def error_trigger_file(self) -> str:
        """Resolve the single managed workflow that is THE error trigger,
        rather than any caller hardcoding "error-trigger.json". Fails
        closed if there is not exactly one such managed entry.
        """
        matches = [
            item.file
            for item in self.workflows
            if item.managed and item.authentication == "error_trigger_v1"
        ]
        if len(matches) != 1:
            raise ValueError(
                f"expected exactly one managed error_trigger_v1 workflow, found {len(matches)}"
            )
        return matches[0]


def load_registry(
    path: Path,
    *,
    workflow_root: Path | None = None,
) -> WorkflowRegistry:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "v1":
        raise ValueError("unsupported workflow registry schema")
    credential_types = {
        name: spec["type"] for name, spec in (raw.get("credentials") or {}).items()
    }
    workflows: list[WorkflowSpec] = []
    for value in raw.get("workflows") or []:
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
        bindings = tuple(
            CredentialBinding(
                node=item["node"],
                credential_type=item["credential_type"],
                logical_name=item["logical_name"],
            )
            for item in value.get("credential_bindings") or []
        )
        workflows.append(
            WorkflowSpec(
                file=value["file"],
                name=value["name"],
                generation=value["generation"],
                event_names=tuple(value.get("event_names") or []),
                webhook_paths=tuple(value.get("webhook_paths") or []),
                callback_paths=tuple(value.get("callback_paths") or []),
                authentication=value["authentication"],
                managed=bool(value["managed"]),
                production_activation=bool(value["production_activation"]),
                test_only=bool(value.get("test_only", False)),
                activation_order=value.get("activation_order"),
                allowed_target_hosts=tuple(value.get("allowed_target_hosts") or []),
                credential_bindings=bindings,
                artifact_path_templates=tuple(value.get("artifact_path_templates") or []),
            )
        )

    files = [item.file for item in workflows]
    names = [item.name for item in workflows]
    paths = [path for item in workflows for path in item.webhook_paths]
    orders = [
        item.activation_order
        for item in workflows
        if item.production_activation and item.activation_order is not None
    ]
    for label, values in (
        ("file", files),
        ("name", names),
        ("webhook path", paths),
        ("activation order", orders),
    ):
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {label}")
    for workflow in workflows:
        if workflow.generation == "v2" and workflow.authentication != "native_header_hmac":
            raise ValueError(f"{workflow.file}: v2 requires native_header_hmac")
        if workflow.test_only and (
            not workflow.managed
            or workflow.production_activation
            or workflow.generation != "v2"
        ):
            raise ValueError(
                f"{workflow.file}: test_only requires managed non-production v2"
            )
        for binding in workflow.credential_bindings:
            expected_type = credential_types.get(binding.logical_name)
            if expected_type is None:
                raise ValueError(
                    f"{workflow.file}: unknown logical credential {binding.logical_name}"
                )
            if expected_type != binding.credential_type:
                raise ValueError(f"{workflow.file}: credential type mismatch")

    root = workflow_root or path.parent / "workflows"
    if root.is_dir():
        disk = {item.name for item in root.glob("*.json")}
        if set(files) != disk:
            raise ValueError(
                f"registry/disk mismatch: missing={sorted(disk - set(files))}, "
                f"unknown={sorted(set(files) - disk)}"
            )
    return WorkflowRegistry(credentials=credential_types, workflows=tuple(workflows))


def _credential_bindings_payload(registry: WorkflowRegistry, file_name: str) -> list[dict[str, str]]:
    return [
        {
            "node": binding.node,
            "credential_type": binding.credential_type,
            "logical_name": binding.logical_name,
        }
        for binding in registry.required_credentials(file_name)
    ]


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help="Path to workflow-registry.json (default: n8n/workflow-registry.json)",
    )
    common.add_argument(
        "--json",
        action="store_true",
        help="Print output as a JSON array (default output format; flag accepted for "
        "explicitness/compatibility).",
    )

    parser = argparse.ArgumentParser(
        parents=[common],
        description="Query the central n8n workflow registry (sole source of truth "
        "for workflows, events, paths, hosts, credentials, and activation).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "managed-files",
        parents=[common],
        help="List managed workflow files in activation order.",
    )
    subparsers.add_parser(
        "activation-order",
        parents=[common],
        help="List managed, production-activated workflow files in activation order.",
    )
    subparsers.add_parser(
        "test-only-files",
        parents=[common],
        help="List managed workflow files that are test-only.",
    )
    credential_parser = subparsers.add_parser(
        "credential-bindings",
        parents=[common],
        help="List credential bindings for a workflow file.",
    )
    credential_parser.add_argument("file", help="Workflow file name, e.g. shortage-reported.json")
    subparsers.add_parser(
        "error-trigger-file",
        parents=[common],
        help="Print the single managed error_trigger_v1 workflow file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        registry = load_registry(args.registry)
        if args.command == "managed-files":
            payload = list(registry.managed_files())
        elif args.command == "activation-order":
            payload = list(registry.activation_order())
        elif args.command == "test-only-files":
            payload = list(registry.test_only_files())
        elif args.command == "credential-bindings":
            payload = _credential_bindings_payload(registry, args.file)
        elif args.command == "error-trigger-file":
            payload = registry.error_trigger_file()
        else:  # pragma: no cover - argparse enforces valid choices
            raise ValueError(f"unknown command {args.command}")
    except (ValueError, KeyError, OSError) as exc:
        print(f"workflow-registry: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
