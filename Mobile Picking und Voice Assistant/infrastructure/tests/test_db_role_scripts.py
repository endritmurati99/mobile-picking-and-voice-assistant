import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "infrastructure" / "scripts"


def text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_fresh_init_creates_separate_non_superuser_app_roles():
    script = text("infrastructure/scripts/init-db-roles.sh")
    assert "pwr_db_admin" in script
    assert "odoo_app" in script
    assert "n8n_app" in script
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE" in script
    assert "REVOKE CONNECT" in script


def test_existing_volume_migration_has_all_reversible_modes():
    script = text("infrastructure/scripts/migrate-n8n-db-role.sh")
    for mode in ("backup", "apply", "verify", "rollback"):
        assert f'"{mode}")' in script
    assert "pg_dump --format=custom" in script
    assert "pg_dumpall --roles-only" in script
    assert "REASSIGN OWNED" in script
    assert "NOLOGIN" in script


def test_isolation_probe_contains_positive_and_negative_checks():
    script = text("infrastructure/scripts/verify-db-role-isolation.sh")
    assert "rolsuper" in script
    assert "n8n_app" in script and "odoo_app" in script
    assert "expected connection failure" in script


def test_volume_clone_is_offline_verified_and_deletable():
    script = text("infrastructure/scripts/clone-postgres-volume.sh")
    for mode in ("create", "verify", "delete"):
        assert f'"{mode}")' in script
    assert "docker volume inspect" in script
    assert "running container still mounts source volume" in script
    assert "manifest.sha256" in script
    override = text("infrastructure/docker-compose.db-migration.yml")
    assert "PWR_DB_MIGRATION_VOLUME" in override
    assert "/var/lib/postgresql/data" in override


def test_no_app_uses_cluster_bootstrap_role_in_compose():
    compose = text("docker-compose.yml")
    assert "DB_POSTGRESDB_USER: ${N8N_DB_USER:-n8n_app}" in compose
    assert "USER: ${ODOO_DB_USER:-odoo_app}" in compose


# ---------------------------------------------------------------------------
# Behavioral tests: run the real scripts as subprocesses with stubbed
# `psql`/`docker`/pg_* tools on PATH, instead of only grepping script text.
# These exercise the actual control flow (fail-closed checks, generated SQL,
# volume-identity refusal) rather than asserting a substring merely exists
# somewhere in the file.
# ---------------------------------------------------------------------------


def _make_executable(path: Path, body: str) -> Path:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _password_file(tmp_path: Path, name: str, content: str = "secret") -> Path:
    p = tmp_path / name
    p.write_text(content)
    p.chmod(0o600)
    return p


def _env_with_bin(tmp_path: Path) -> tuple[dict, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return env, bin_dir


def _stub_noop_psql(bin_dir: Path):
    # A psql stub that consumes stdin (so `<<'SQL' ... SQL` doesn't hang)
    # and always succeeds. Used only where the test doesn't care about
    # exact SQL content, just about fail-closed behavior before any
    # psql call would matter.
    _make_executable(bin_dir / "psql", "cat >/dev/null 2>&1; exit 0\n")


def _stub_noop(bin_dir: Path, name: str):
    _make_executable(bin_dir / name, "exit 0\n")


def test_init_db_roles_fails_closed_without_odoo_db_name(tmp_path):
    env, bin_dir = _env_with_bin(tmp_path)
    _stub_noop_psql(bin_dir)
    env["PWR_DB_ADMIN_PASSWORD_FILE"] = str(_password_file(tmp_path, "pwr.pass"))
    env["ODOO_DB_PASSWORD_FILE"] = str(_password_file(tmp_path, "odoo.pass"))
    env["N8N_DB_PASSWORD_FILE"] = str(_password_file(tmp_path, "n8n.pass"))
    env["POSTGRES_USER"] = "pwr_db_admin"
    env.pop("ODOO_DB_NAME", None)

    result = subprocess.run(
        ["bash", str(SCRIPTS / "init-db-roles.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "ODOO_DB_NAME" in result.stderr


def test_init_db_roles_requires_pwr_db_admin_bootstrap_user(tmp_path):
    env, bin_dir = _env_with_bin(tmp_path)
    _stub_noop_psql(bin_dir)
    env["PWR_DB_ADMIN_PASSWORD_FILE"] = str(_password_file(tmp_path, "pwr.pass"))
    env["ODOO_DB_PASSWORD_FILE"] = str(_password_file(tmp_path, "odoo.pass"))
    env["N8N_DB_PASSWORD_FILE"] = str(_password_file(tmp_path, "n8n.pass"))
    env["ODOO_DB_NAME"] = "picking"
    env["POSTGRES_USER"] = "some_other_role"

    result = subprocess.run(
        ["bash", str(SCRIPTS / "init-db-roles.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "pwr_db_admin" in result.stderr


@pytest.mark.parametrize(
    "mode,needs_backup_dir",
    [
        ("backup", True),
        ("apply", True),
        ("verify", False),
        ("rollback", True),
    ],
)
def test_migrate_fails_closed_without_odoo_db_name_in_every_mode(tmp_path, mode, needs_backup_dir):
    env, bin_dir = _env_with_bin(tmp_path)
    _stub_noop_psql(bin_dir)
    for tool in ("docker", "pg_dump", "pg_dumpall", "pg_restore"):
        _stub_noop(bin_dir, tool)
    env.pop("ODOO_DB_NAME", None)

    args = [mode]
    if needs_backup_dir:
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir(mode=0o700)
        args.append(str(backup_dir))

    result = subprocess.run(
        ["bash", str(SCRIPTS / "migrate-n8n-db-role.sh"), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "ODOO_DB_NAME" in result.stderr


def test_isolation_probe_fails_closed_without_odoo_db_name(tmp_path):
    env, bin_dir = _env_with_bin(tmp_path)
    _stub_noop_psql(bin_dir)
    env["ODOO_DB_PASSWORD_FILE"] = str(_password_file(tmp_path, "odoo.pass"))
    env["N8N_DB_PASSWORD_FILE"] = str(_password_file(tmp_path, "n8n.pass"))
    env.pop("ODOO_DB_NAME", None)

    result = subprocess.run(
        ["bash", str(SCRIPTS / "verify-db-role-isolation.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "ODOO_DB_NAME" in result.stderr


def _prepare_backup_dir(tmp_path: Path) -> Path:
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(mode=0o700)
    for name in (
        "roles-before.sql",
        "n8n-before.dump",
        "database-acl-before.tsv",
        "n8n-schema-acl-before.tsv",
    ):
        (backup_dir / name).write_text("stub-content")
    subprocess.run(
        ["bash", "-c", "sha256sum *.sql *.dump *.tsv > manifest.sha256"],
        cwd=backup_dir,
        check=True,
    )
    subprocess.run(["chmod", "0600"] + [str(p) for p in backup_dir.glob("*")], check=True)
    return backup_dir


def test_migrate_apply_creates_nosuperuser_roles_revokes_public_acls_and_quotes_identifiers(tmp_path):
    env, bin_dir = _env_with_bin(tmp_path)
    capture_file = tmp_path / "psql_capture.log"

    _make_executable(
        bin_dir / "psql",
        textwrap.dedent(
            f"""\
            args="$*"
            stdin_content="$(cat)"
            {{
              printf 'ARGS: %s\\n' "$args"
              echo '---STDIN---'
              printf '%s\\n' "$stdin_content"
              echo '---END---'
            }} >> "{capture_file}"
            # Answer the isolation verifier's role-flag lookups so it can
            # run to completion inside cmd_apply.
            case "$args" in
              *"rolsuper FROM pg_roles WHERE rolname = 'pwr_db_admin'"*)
                echo "t" ;;
              *"rolname = 'odoo_app'"*)
                echo "f|f|f" ;;
              *"rolname = 'n8n_app'"*)
                echo "f|f|f" ;;
            esac
            # Simulate real cross-database connection refusal for the
            # isolation verifier's two negative checks; every other
            # connection (including the positive checks) succeeds.
            case "$args" in
              *"--username n8n_app"*"--dbname picking"*)
                exit 1 ;;
              *"--username odoo_app"*"--dbname n8n"*)
                exit 1 ;;
            esac
            exit 0
            """
        ),
    )
    _make_executable(
        bin_dir / "docker",
        textwrap.dedent(
            """\
            if [ "$1" = "compose" ] && [ "$2" = "config" ]; then
              echo "USER: odoo_app"
              echo "DB_POSTGRESDB_USER: n8n_app"
              exit 0
            fi
            exit 0
            """
        ),
    )

    env["ODOO_DB_NAME"] = "picking"
    env["POSTGRES_USER"] = "odoo"
    env["LEGACY_DB_SUPERUSER"] = "odoo"
    env["PWR_DB_ADMIN_PASSWORD_FILE"] = str(_password_file(tmp_path, "pwr.pass"))
    env["ODOO_DB_PASSWORD_FILE"] = str(_password_file(tmp_path, "odoo.pass"))
    env["N8N_DB_PASSWORD_FILE"] = str(_password_file(tmp_path, "n8n.pass"))

    backup_dir = _prepare_backup_dir(tmp_path)

    # apply's final step invokes verify-db-role-isolation.sh for real,
    # against the same stubbed psql (which always exits 0). That script's
    # negative checks would then "unexpectedly connect" and fail hard,
    # which is fine here: we assert on what was captured *before* that
    # point, not on cmd_apply's overall exit status.
    subprocess.run(
        ["bash", str(SCRIPTS / "migrate-n8n-db-role.sh"), "apply", str(backup_dir)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    captured = capture_file.read_text()

    # App roles are created explicitly non-superuser/non-createdb/non-createrole.
    assert "CREATE ROLE odoo_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE" in captured
    assert "CREATE ROLE n8n_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE" in captured

    # The pwr_db_admin bootstrap role is actually created (not just logged).
    assert "CREATE ROLE pwr_db_admin SUPERUSER LOGIN" in captured

    # Legacy role name is substituted through psql's quoted-identifier
    # form, never as a bare/unquoted substitution.
    assert 'REASSIGN OWNED BY :"legacy" TO n8n_app' in captured
    assert 'REASSIGN OWNED BY :"legacy" TO odoo_app' in captured
    assert 'ALTER ROLE :"legacy" NOSUPERUSER NOCREATEDB NOCREATEROLE NOLOGIN' in captured
    assert "REASSIGN OWNED BY :legacy " not in captured
    assert "ALTER ROLE :legacy " not in captured

    # PUBLIC connect/temporary and schema access are revoked for both
    # databases, not just declared in the fresh-init script.
    assert "REVOKE CONNECT, TEMPORARY ON DATABASE n8n FROM PUBLIC" in captured
    assert "REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC" in captured
    assert captured.count("REVOKE ALL ON SCHEMA public FROM PUBLIC") >= 2


def test_clone_delete_refuses_recorded_source_volume(tmp_path):
    env, bin_dir = _env_with_bin(tmp_path)
    _make_executable(
        bin_dir / "docker",
        textwrap.dedent(
            """\
            if [ "$1" = "volume" ] && [ "$2" = "inspect" ]; then
              shift 2
              # Strip a trailing --format ... pair if present; the name is
              # whatever remains as the first positional argument.
              name="$1"
              echo "$name"
              exit 0
            fi
            if [ "$1" = "volume" ] && [ "$2" = "rm" ]; then
              exit 0
            fi
            exit 0
            """
        ),
    )

    manifest_dir = tmp_path / "manifest"
    manifest_dir.mkdir(mode=0o700)
    (manifest_dir / "clone.manifest").write_text(
        "source_volume=prod_pg_data\ncopy_volume=pwr_migration_copy\ncreated_utc=2026-01-01T00:00:00Z\n"
    )

    refused = subprocess.run(
        ["bash", str(SCRIPTS / "clone-postgres-volume.sh"), "delete", "prod_pg_data", str(manifest_dir)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert refused.returncode != 0
    assert "refus" in refused.stderr.lower()
    # The manifest directory must survive a refused delete.
    assert (manifest_dir / "clone.manifest").exists()


def test_clone_assert_target_refuses_source_and_requires_recorded_copy(tmp_path):
    env, bin_dir = _env_with_bin(tmp_path)
    _make_executable(
        bin_dir / "docker",
        textwrap.dedent(
            """\
            if [ "$1" = "volume" ] && [ "$2" = "inspect" ]; then
              shift 2
              name="$1"
              echo "$name"
              exit 0
            fi
            exit 0
            """
        ),
    )

    manifest_dir = tmp_path / "manifest"
    manifest_dir.mkdir(mode=0o700)
    (manifest_dir / "clone.manifest").write_text(
        "source_volume=prod_pg_data\ncopy_volume=pwr_migration_copy\ncreated_utc=2026-01-01T00:00:00Z\n"
    )

    refused = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "clone-postgres-volume.sh"),
            "assert-target",
            str(manifest_dir),
            "prod_pg_data",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert refused.returncode != 0
    assert "refus" in refused.stderr.lower()

    accepted = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "clone-postgres-volume.sh"),
            "assert-target",
            str(manifest_dir),
            "pwr_migration_copy",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert accepted.returncode == 0
