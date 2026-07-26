from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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
