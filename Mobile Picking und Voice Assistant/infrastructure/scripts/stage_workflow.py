"""Pure workflow-staging and activation-guard helpers for the n8n rollout tooling.

``stage_workflow`` never mutates the workflow JSON that lives on disk: it
returns a deep copy with runtime IDs injected, so the reviewed source files
under ``n8n/workflows/`` never carry workflow or credential IDs.

The activation guard helpers below encode the fail-closed rules that
``infrastructure/scripts/import-workflows.sh`` enforces before it is allowed
to activate a workflow (production or test-only). They are pure and
Docker-free so they can be unit tested directly; the shell script invokes
them through this module's small CLI (see ``main`` at the bottom).
"""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from typing import Any
from uuid import uuid4


def stage_workflow(
    source: dict,
    *,
    bindings: list[dict],
    credential_index: dict[tuple[str, str], list[dict]],
    existing_workflow_id: str | None,
    error_workflow_id: str | None,
) -> dict:
    """Stage a workflow for import.

    ``credential_index`` maps (logical_name, credential_type) to the list of
    *candidate* credentials found for that key -- mirroring how the Node
    credential resolver (indexCredentials) represents candidates, rather
    than a single pre-resolved value. stage_workflow performs its own
    "exactly one" check here, so it fails closed both when a binding has no
    matching credential at all AND when it finds more than one candidate
    and cannot disambiguate -- it never trusts an upstream caller to have
    already deduplicated.
    """
    staged = deepcopy(source)
    staged["id"] = existing_workflow_id or staged.get("id") or uuid4().hex
    staged["active"] = False
    by_name = {node.get("name"): node for node in staged.get("nodes") or []}
    for binding in bindings:
        node = by_name.get(binding["node"])
        if node is None:
            raise ValueError(f"credential node not found: {binding['node']}")
        lookup = (
            binding["logical_name"],
            binding["credential_type"],
        )
        candidates = credential_index.get(lookup) or []
        if len(candidates) != 1:
            raise ValueError(
                f"expected exactly one credential for {binding['logical_name']}, "
                f"found {len(candidates)}"
            )
        credential = candidates[0]
        node.setdefault("credentials", {})[binding["credential_type"]] = {
            "id": credential["id"],
            "name": credential["name"],
        }
    if error_workflow_id:
        staged.setdefault("settings", {})["errorWorkflow"] = error_workflow_id
    return staged


class ActivationError(ValueError):
    """Raised when an activate/activate-test/deactivate-test guard refuses."""


def assert_activatable(
    spec: dict[str, Any],
    *,
    credentials_verified: bool,
    duplicate: bool,
) -> None:
    """Guard for the normal ``activate`` mode.

    Refuses workflows that are not registered for production activation,
    workflows whose bound credentials were not verified, and workflows for
    which a duplicate n8n workflow name was detected on the instance.
    """
    file_name = spec.get("file", "<unknown>")
    if not spec.get("production_activation"):
        raise ActivationError(
            f"{file_name}: refusing activate, production_activation is false"
        )
    if not credentials_verified:
        raise ActivationError(
            f"{file_name}: refusing activate, credentials are not verified"
        )
    if duplicate:
        raise ActivationError(
            f"{file_name}: refusing activate, duplicate workflow name on instance"
        )


def assert_test_activatable(
    spec: dict[str, Any],
    *,
    run_id: str | None,
    dependency_files: set[str],
) -> None:
    """Guard for ``activate-test``.

    Requires a nonempty operator-generated RUN_ID, refuses every
    production_activation=true workflow, and refuses activating any
    dependency workflow (a workflow other tests/flows rely on being in its
    normal production state).
    """
    file_name = spec.get("file", "<unknown>")
    if not run_id:
        raise ActivationError("activate-test requires a nonempty RUN_ID")
    if spec.get("production_activation"):
        raise ActivationError(
            f"{file_name}: refusing activate-test, workflow is production_activation=true"
        )
    if not spec.get("test_only"):
        raise ActivationError(
            f"{file_name}: refusing activate-test, workflow is not test_only"
        )
    if file_name in dependency_files:
        raise ActivationError(
            f"{file_name}: refusing activate-test, workflow is a dependency workflow"
        )


def build_restoration_manifest(
    *,
    file_name: str,
    run_id: str,
    workflow_id: str,
    previous_active: bool,
) -> dict[str, Any]:
    return {
        "file": file_name,
        "run_id": run_id,
        "workflow_id": workflow_id,
        "previous_active": previous_active,
    }


def restore_from_manifest(
    manifest: dict[str, Any], *, run_id: str, file_name: str | None = None
) -> bool:
    """Validate a deactivate-test restoration manifest and return the
    ``active`` state that must be restored.

    A missing or mismatched run_id is a hard failure: it means the caller
    is not the same live-smoke run that performed the activation, so we
    refuse to guess and restore nothing. A caller-supplied file_name that
    does not match the manifest's own file is likewise a hard failure: it
    means the operator asked to restore a different workflow than the one
    this manifest actually activated, so we refuse rather than restoring
    the wrong workflow under the right RUN_ID.
    """
    if not run_id or manifest.get("run_id") != run_id:
        raise ActivationError(
            "deactivate-test refused: run_id does not match the restoration manifest"
        )
    if file_name is not None and manifest.get("file") != file_name:
        raise ActivationError(
            f"deactivate-test refused: requested file '{file_name}' does not match "
            f"the restoration manifest's file '{manifest.get('file')}'"
        )
    return bool(manifest.get("previous_active"))


def _read_json_stdin() -> Any:
    return json.load(sys.stdin)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pure staging/activation-guard helpers for n8n workflow rollout.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    stage = subparsers.add_parser(
        "stage",
        help="Stage a workflow: read {source, bindings, credential_index, "
        "existing_workflow_id, error_workflow_id} JSON on stdin, print staged JSON.",
    )
    stage.set_defaults(command="stage")

    assert_activate = subparsers.add_parser(
        "assert-activatable",
        help="Read {spec, credentials_verified, duplicate} JSON on stdin; "
        "exit 1 with a message on stderr if activation must be refused.",
    )
    assert_activate.set_defaults(command="assert-activatable")

    assert_test_activate = subparsers.add_parser(
        "assert-test-activatable",
        help="Read {spec, run_id, dependency_files} JSON on stdin; exit 1 "
        "with a message on stderr if activate-test must be refused.",
    )
    assert_test_activate.set_defaults(command="assert-test-activatable")

    build_manifest = subparsers.add_parser(
        "build-manifest",
        help="Read {file_name, run_id, workflow_id, previous_active} JSON on "
        "stdin, print the restoration manifest JSON.",
    )
    build_manifest.set_defaults(command="build-manifest")

    restore = subparsers.add_parser(
        "restore-from-manifest",
        help="Read {manifest, run_id, file_name} JSON on stdin; print "
        "'true'/'false' for the active state to restore, or exit 1 on a "
        "run_id or file_name mismatch.",
    )
    restore.set_defaults(command="restore-from-manifest")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        payload = _read_json_stdin()
        if args.command == "stage":
            # Wire format for credential_index: a list of
            # {"logical_name", "credential_type", "credentials"} rows (JSON
            # object keys cannot carry the (name, type) tuple directly).
            # "credentials" is itself a list of every candidate found for
            # that key, so a real duplicate (more than one candidate) is
            # representable and stage_workflow's own "exactly one" check
            # actually has something to reject.
            credential_index: dict[tuple[str, str], list[dict]] = {
                (row["logical_name"], row["credential_type"]): row.get("credentials") or []
                for row in payload["credential_index"]
            }
            result = stage_workflow(
                payload["source"],
                bindings=payload["bindings"],
                credential_index=credential_index,
                existing_workflow_id=payload.get("existing_workflow_id"),
                error_workflow_id=payload.get("error_workflow_id"),
            )
            print(json.dumps(result))
        elif args.command == "assert-activatable":
            assert_activatable(
                payload["spec"],
                credentials_verified=bool(payload.get("credentials_verified")),
                duplicate=bool(payload.get("duplicate")),
            )
        elif args.command == "assert-test-activatable":
            assert_test_activatable(
                payload["spec"],
                run_id=payload.get("run_id"),
                dependency_files=set(payload.get("dependency_files") or []),
            )
        elif args.command == "build-manifest":
            print(json.dumps(build_restoration_manifest(**payload)))
        elif args.command == "restore-from-manifest":
            active = restore_from_manifest(
                payload["manifest"],
                run_id=payload.get("run_id"),
                file_name=payload.get("file_name"),
            )
            print("true" if active else "false")
        else:  # pragma: no cover - argparse enforces valid choices
            raise ValueError(f"unknown command {args.command}")
    except (ActivationError, ValueError, KeyError) as exc:
        print(f"stage_workflow: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
