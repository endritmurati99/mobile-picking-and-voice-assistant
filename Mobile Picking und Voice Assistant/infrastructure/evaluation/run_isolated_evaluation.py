#!/usr/bin/env python3
"""Build and run the disposable Bachelor evaluation stack.

This runner never targets the production containers for writes.  It clones the
configured live Odoo database into an internal-only PostgreSQL container, then
runs only the packaged synthetic-fixture scripts in the cloned ``evaluation``
database.  It deliberately withholds commands, environment values, dump data,
and stderr from normal output.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_APP = ROOT.parents[1]
NETWORK = "bachelor-eval-isolated"
TEMP_CONTAINERS = ("bachelor-eval-db", "bachelor-eval-odoo", "bachelor-eval-backend")
PRODUCTION = {
    "backend": "mobilepickingundvoiceassistant-backend-1",
    "odoo": "mobilepickingundvoiceassistant-odoo-1",
    "db": "mobilepickingundvoiceassistant-db-1",
}
TESTS = ("test_core.py", "test_followup.py", "test_negative_quantity.py", "prepare_outbox.py", "test_outbox.py")


class RunnerError(RuntimeError):
    pass


def run(label: str, args: list[str], *, input_data: bytes | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(args, input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if result.returncode:
        # Never surface args: Docker args can carry passwords and mount paths.
        raise RunnerError(f"{label} failed")
    return result


def docker_json(label: str, args: list[str]) -> dict:
    try:
        return json.loads(run(label, ["docker", *args]).stdout)[0]
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        raise RunnerError(f"{label} returned unexpected metadata") from exc


def env_of(inspect: dict) -> dict[str, str]:
    return dict(item.split("=", 1) for item in inspect["Config"].get("Env", []) if "=" in item)


def docker_mount_path(path: Path) -> str:
    """Return a Docker bind source for Windows Python, WSL, or native Linux."""
    value = str(path.resolve())
    if os.name == "nt":
        return value
    parts = Path(value).parts
    if len(parts) >= 4 and parts[:2] == ("/", "mnt") and len(parts[2]) == 1:
        return f"{parts[2].upper()}:/{'/'.join(parts[3:])}"
    if value.startswith("/"):
        return value
    raise RunnerError("mounted path is not absolute")


def application_tree(app_path: Path) -> str:
    """Identify the committed application tree and reject dirty runtime inputs."""
    git_root = Path(run(
        "locate application repository",
        ["git", "-C", str(app_path), "rev-parse", "--show-toplevel"],
    ).stdout.decode().strip()).resolve()
    try:
        relative_app = app_path.resolve().relative_to(git_root)
    except ValueError as exc:
        raise RunnerError("app path is outside its Git repository") from exc
    relative_text = relative_app.as_posix()
    tree_spec = "HEAD^{tree}" if relative_text == "." else f"HEAD:{relative_text}"
    tree = run(
        "resolve application tree",
        ["git", "-C", str(git_root), "rev-parse", tree_spec],
    ).stdout.decode().strip()
    runtime_paths = [
        relative_app / "backend/app",
        relative_app / "odoo/addons",
        relative_app / "n8n/workflow-registry.json",
    ]
    status = run(
        "inspect runtime input state",
        [
            "git", "-C", str(git_root), "status", "--porcelain",
            "--untracked-files=all", "--", *(path.as_posix() for path in runtime_paths),
        ],
    ).stdout
    if status.strip():
        raise RunnerError("mounted runtime inputs differ from the recorded Git tree")
    return tree


def container_names() -> set[str]:
    result = run("list containers", ["docker", "ps", "-a", "--format", "{{.Names}}"])
    return {line.strip() for line in result.stdout.decode().splitlines() if line.strip()}


def clear_previous(*, replace: bool) -> None:
    existing = container_names()
    found = [name for name in TEMP_CONTAINERS if name in existing]
    network_exists = NETWORK in {line.strip() for line in run("list networks", ["docker", "network", "ls", "--format", "{{.Name}}"]).stdout.decode().splitlines()}
    if (found or network_exists) and not replace:
        raise RunnerError("temporary evaluation containers/network already exist; rerun with --replace")
    if not replace:
        return
    for name in TEMP_CONTAINERS:
        if name in existing:
            run("remove temporary container", ["docker", "rm", "-f", "-v", name])
    if network_exists:
        run("remove temporary network", ["docker", "network", "rm", NETWORK])


def launch(name: str, image: str, network: str, env: dict[str, str], mounts: list[tuple[Path, str]]) -> None:
    command = ["docker", "run", "-d", "--name", name, "--network", network]
    for source, destination in mounts:
        command.extend(["--mount", f"type=bind,src={docker_mount_path(source)},dst={destination},readonly"])
    for key, value in env.items():
        command.extend(["-e", f"{key}={value}"])
    command.append(image)
    run(f"launch {name}", command)


def wait_for(label: str, probe: list[str], *, seconds: int = 90) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = subprocess.run(probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RunnerError(f"{label} did not become ready")


def pipe_clone(source_db: dict[str, str], target_password: str, source_database: str) -> None:
    dump = subprocess.Popen(
        ["docker", "exec", PRODUCTION["db"], "pg_dump", "-U", source_db["POSTGRES_USER"], "-d", source_database, "--no-owner", "--no-acl"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    restore = subprocess.Popen(
        ["docker", "exec", "-i", "-e", f"PGPASSWORD={target_password}", "bachelor-eval-db", "psql", "-U", "eval_admin", "-d", "evaluation", "-v", "ON_ERROR_STOP=1"],
        stdin=dump.stdout,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert dump.stdout is not None
    dump.stdout.close()
    restore_stderr = restore.communicate()[1]
    dump_stderr = dump.communicate()[1]
    if dump.returncode or restore.returncode:
        # Keep dump/restore output private: it may contain database names or role details.
        _ = (dump_stderr, restore_stderr)
        raise RunnerError("database clone failed")


def pipe_private_fixtures() -> None:
    source = subprocess.Popen(
        ["docker", "exec", "bachelor-eval-odoo", "cat", "/tmp/evaluation-fixtures-private.json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    target = subprocess.Popen(
        ["docker", "exec", "-i", "bachelor-eval-backend", "sh", "-c", "cat > /tmp/evaluation-fixtures-private.json"],
        stdin=source.stdout,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert source.stdout is not None
    source.stdout.close()
    target_stderr = target.communicate()[1]
    source_stderr = source.communicate()[1]
    if source.returncode or target.returncode:
        _ = (source_stderr, target_stderr)
        raise RunnerError("private fixture transfer failed")


def reported_failure(stdout: bytes) -> bool:
    """Recognize both JSON documents and JSONL case results, including blocked cases."""
    def failed(payload: object) -> bool:
        if isinstance(payload, list):
            return any(failed(item) for item in payload)
        if isinstance(payload, dict):
            if payload.get("status") in {"fail", "failed", "error", "blocked"}:
                return True
            return any(failed(value) for value in payload.values() if isinstance(value, (list, dict)))
        return False

    content = stdout.decode("utf-8", errors="replace")
    for line in [content, *content.splitlines()]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if failed(payload):
            return True
    return False


def capture_script(script: str, output: Path, private: Path) -> int:
    result = subprocess.run(
        ["docker", "exec", "-e", "PYTHONPATH=/app", "bachelor-eval-backend", "python", f"/tmp/{script}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Packaged scripts intentionally produce sanitized JSON only on stdout.
    (output / f"{Path(script).stem}.jsonl").write_bytes(result.stdout)
    (private / f"{Path(script).stem}.stderr").write_bytes(result.stderr)
    if result.returncode:
        raise RunnerError(f"{script} failed")
    if reported_failure(result.stdout):
        raise RunnerError(f"{script} reported failure")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated Bachelor evaluation fixtures")
    parser.add_argument("--output", type=Path, required=True, help="directory for sanitized evidence")
    parser.add_argument("--app-path", type=Path, default=DEFAULT_APP, help="application root (defaults to the repository copy containing this script)")
    parser.add_argument("--source-backend-container", default=PRODUCTION["backend"])
    parser.add_argument("--source-odoo-container", default=PRODUCTION["odoo"])
    parser.add_argument("--source-db-container", default=PRODUCTION["db"])
    parser.add_argument("--replace", action="store_true", help="remove only prior bachelor-eval temporary resources")
    args = parser.parse_args()
    PRODUCTION.update({
        "backend": args.source_backend_container,
        "odoo": args.source_odoo_container,
        "db": args.source_db_container,
    })
    output = args.output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        print(json.dumps({"status": "failed", "stage": "output must be a new or empty directory"}))
        return 1
    private = output / "private"
    output.mkdir(parents=True, exist_ok=True)
    private.mkdir(exist_ok=True)
    try:
        if not args.app_path.is_dir():
            raise RunnerError("app path does not exist")
        tested_application_tree = application_tree(args.app_path)
        backend = docker_json("inspect production backend", ["inspect", PRODUCTION["backend"]])
        odoo = docker_json("inspect production odoo", ["inspect", PRODUCTION["odoo"]])
        db = docker_json("inspect production database", ["inspect", PRODUCTION["db"]])
        # Inspect resolves IDs and aliases to canonical names before any deletion.
        for source in (backend, odoo, db):
            if source.get("Name", "").lstrip("/") in TEMP_CONTAINERS:
                raise RunnerError("source container overlaps disposable evaluation resources")
        clear_previous(replace=args.replace)
        backend_env = env_of(backend)
        db_env = env_of(db)
        source_database = backend_env.get("ODOO_DB")
        if not source_database or "POSTGRES_USER" not in db_env:
            raise RunnerError("production metadata is incomplete")

        run("create isolated network", ["docker", "network", "create", "--internal", NETWORK])
        eval_password = secrets.token_urlsafe(32)
        launch(
            "bachelor-eval-db",
            db["Image"],
            NETWORK,
            {"POSTGRES_USER": "eval_admin", "POSTGRES_PASSWORD": eval_password, "POSTGRES_DB": "evaluation"},
            [],
        )
        wait_for("evaluation database", ["docker", "exec", "bachelor-eval-db", "pg_isready", "-U", "eval_admin", "-d", "evaluation"])
        pipe_clone(db_env, eval_password, source_database)
        run(
            "disable cloned jobs and mail",
            ["docker", "exec", "-e", f"PGPASSWORD={eval_password}", "bachelor-eval-db", "psql", "-U", "eval_admin", "-d", "evaluation", "-v", "ON_ERROR_STOP=1", "-c", "UPDATE ir_cron SET active=false; UPDATE ir_mail_server SET active=false;"],
        )

        config_dir = private / "runtime"
        config_dir.mkdir(parents=True, exist_ok=True)
        config = config_dir / "odoo.conf"
        config.write_text("[options]\naddons_path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons\nlist_db=False\ndb_name=evaluation\ndbfilter=^evaluation$\nmax_cron_threads=0\nworkers=0\nlog_level=warn\n", encoding="utf-8")
        launch(
            "bachelor-eval-odoo",
            odoo["Image"],
            NETWORK,
            {"HOST": "bachelor-eval-db", "PORT": "5432", "USER": "eval_admin", "PASSWORD": eval_password},
            [(args.app_path / "odoo/addons", "/mnt/extra-addons"), (config, "/etc/odoo/odoo.conf")],
        )
        wait_for("evaluation odoo", ["docker", "exec", "bachelor-eval-odoo", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8069/web/login', timeout=2).read()"], seconds=120)

        eval_backend_env = dict(backend_env)
        eval_backend_env.update({
            "ODOO_URL": "http://bachelor-eval-odoo:8069",
            "ODOO_DB": "evaluation",
            "ODOO_INSTANCES_JSON": "",
            "DISPATCHER_ENABLED": "false",
            "PWA_ORIGINS": "https://evaluation.local",
            "RUNTIME_PROFILE": "test",
            "STARTUP_ODOO_WAIT_SECONDS": "90",
        })
        launch(
            "bachelor-eval-backend",
            backend["Image"],
            NETWORK,
            eval_backend_env,
            [(args.app_path / "backend/app", "/app/app"), (args.app_path / "n8n/workflow-registry.json", "/run/pwr/workflow-registry.json")],
        )
        wait_for("evaluation backend", ["docker", "exec", "bachelor-eval-backend", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/live', timeout=2).read()"])

        fixture = run("create synthetic fixtures", ["docker", "exec", "-i", "bachelor-eval-odoo", "sh", "-c", 'odoo shell -c /etc/odoo/odoo.conf --no-http --db_host "$HOST" --db_user "$USER" --db_password "$PASSWORD" -d evaluation'], input_data=(ROOT / "fixtures.py").read_bytes())
        # Fixture stdout includes an intentionally public summary only.
        (output / "fixtures-public.log").write_bytes(fixture.stdout)
        (private / "fixtures.stderr").write_bytes(fixture.stderr)
        pipe_private_fixtures()
        for script in TESTS:
            run("copy test script", ["docker", "exec", "-i", "bachelor-eval-backend", "sh", "-c", f"cat > /tmp/{script}"], input_data=(ROOT / script).read_bytes())
        status = {script: capture_script(script, output, private) for script in TESTS}

        environment = {
            "database": "evaluation",
            "network": NETWORK,
            "external_network": False,
            "public_ports": False,
            "scheduler_and_mail_disabled_in_clone": True,
            "dispatcher_enabled": False,
            "clone_boundary": "pg_dump pipe from production database container into disposable evaluation database; no production write",
            "images": {"backend": backend["Image"], "odoo": odoo["Image"], "postgres": db["Image"]},
            "application_tree": tested_application_tree,
            "test_exit_codes": status,
            "suite_status": "passed",
        }
        (output / "environment.json").write_text(json.dumps(environment, indent=2, sort_keys=True), encoding="utf-8")
        (output / "runner-status.json").write_text(json.dumps({"status": "passed"}, sort_keys=True), encoding="utf-8")
        print(json.dumps({"status": "passed", "output": str(output), "application_tree": tested_application_tree}, sort_keys=True))
        return 0
    except RunnerError as exc:
        (output / "runner-status.json").write_text(json.dumps({"status": "failed", "error_type": type(exc).__name__}), encoding="utf-8")
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "stage": "unexpected runner failure"}, sort_keys=True))
        return 1
    except Exception as exc:
        # Includes malformed local metadata and Docker invocation failures; never print their args.
        (output / "runner-status.json").write_text(json.dumps({"status": "failed", "error_type": type(exc).__name__}), encoding="utf-8")
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "stage": "unexpected runner failure"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
