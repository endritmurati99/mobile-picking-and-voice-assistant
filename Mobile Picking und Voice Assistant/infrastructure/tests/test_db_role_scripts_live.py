"""Opt-in SQL integration check on a new, disposable PostgreSQL container.

PWR_TEST_POSTGRES=1 pytest infrastructure/tests/test_db_role_scripts_live.py
Only Compose service orchestration is stubbed; backup, migration SQL and
permission checks run against real PostgreSQL. No existing volume is mounted.
"""
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.environ.get("PWR_TEST_POSTGRES") != "1", reason="requires Docker; opt in with PWR_TEST_POSTGRES=1")
@pytest.mark.parametrize("legacy_is_bootstrap", [True, False])
def test_backup_and_two_warehouse_migration_on_real_postgres(legacy_is_bootstrap):
    name = "pwr-role-test-" + uuid4().hex[:10]
    image = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["db"]["image"]

    def docker(*args, stdin=None, check=True):
        result = subprocess.run(["docker", *args], input=stdin, text=True, capture_output=True, timeout=60)
        if check:
            assert result.returncode == 0, result.stderr
        return result

    def sql(query, db="postgres", user="legacy_review"):
        return docker("exec", "-i", name, "psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", "-U", user, "-d", db, stdin=query).stdout.strip()

    try:
        bootstrap = "legacy_review" if legacy_is_bootstrap else "initdb_review"
        docker("run", "-d", "--name", name, "--network", "none", "--tmpfs", "/var/lib/postgresql/data",
               "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_USER=" + bootstrap, image)
        for _ in range(30):
            # The init server accepts sockets only; TCP waits for the final server.
            if docker("exec", name, "pg_isready", "-h", "127.0.0.1", "-U", bootstrap, check=False).returncode == 0:
                break
            time.sleep(0.5)
        else:
            pytest.fail("disposable PostgreSQL did not become ready")
        if not legacy_is_bootstrap:
            sql("CREATE ROLE legacy_review LOGIN SUPERUSER;", user=bootstrap)
        sql("CREATE DATABASE n8n; CREATE DATABASE lager1; CREATE DATABASE lager2; CREATE DATABASE legacy_archive;")
        for db in ("n8n", "lager1", "lager2"):
            sql("""CREATE TABLE preserved(id serial PRIMARY KEY);
INSERT INTO preserved VALUES (42);
CREATE VIEW preserved_view AS SELECT id FROM preserved;
CREATE FUNCTION preserved_function() RETURNS integer LANGUAGE sql AS 'SELECT 42';
CREATE TYPE preserved_enum AS ENUM ('ok');
""", db)
        sql("CREATE TABLE preserved(id integer PRIMARY KEY); INSERT INTO preserved VALUES (42);", "legacy_archive")
        for script in ("migrate-n8n-db-role.sh", "verify-db-role-isolation.sh"):
            docker("exec", "-i", name, "sh", "-c", "cat > /tmp/" + script,
                   stdin=(ROOT / "infrastructure/scripts" / script).read_text())
        docker("exec", "-i", name, "sh", stdin="""set -eu
mkdir /tmp/stub
printf '#!/bin/sh\necho odoo_app n8n_app\n' > /tmp/stub/docker
chmod 700 /tmp/stub/docker
umask 077
printf test-admin > /tmp/admin.pass
printf test-odoo > /tmp/odoo.pass
printf test-n8n > /tmp/n8n.pass
""")
        env = ["-e", "ODOO_DB_NAME=lager1", "-e", "ODOO_LAGER2_DB_NAME=lager2",
               "-e", "LEGACY_DB_SUPERUSER=legacy_review", "-e", "PWR_DB_ADMIN_PASSWORD_FILE=/tmp/admin.pass",
               "-e", "ODOO_DB_PASSWORD_FILE=/tmp/odoo.pass", "-e", "N8N_DB_PASSWORD_FILE=/tmp/n8n.pass"]
        # Do not supply PGUSER: each backup command must select the legacy role.
        docker("exec", *env, name, "bash", "/tmp/migrate-n8n-db-role.sh", "backup", "/tmp/backup")
        for dump in ("n8n-before.dump", "odoo-before.dump", "odoo-lager2-before.dump"):
            docker("exec", name, "pg_restore", "--list", "/tmp/backup/" + dump)
        archive_dump = docker("exec", name, "awk", "-F\\t", "NR==1 {print $3}", "/tmp/backup/extra-databases-before.tsv").stdout.strip()
        assert archive_dump.startswith("extra-") and archive_dump.endswith(".dump")
        docker("exec", name, "pg_restore", "--list", "/tmp/backup/" + archive_dump)
        docker("exec", "-d", name, "sh", "-c", "exec psql -X -U legacy_review -d legacy_archive -c 'SELECT pg_sleep(30)'")
        for _ in range(20):
            if sql("SELECT count(*) FROM pg_stat_activity WHERE datname='legacy_archive' AND pid <> pg_backend_pid();") == "1":
                break
            time.sleep(0.1)
        else:
            pytest.fail("archive client did not become visible")
        active_refusal = docker("exec", *env, name, "sh", "-c",
                                "PATH=/tmp/stub:$PATH bash /tmp/migrate-n8n-db-role.sh apply /tmp/backup", check=False)
        assert active_refusal.returncode != 0 and "active client sessions" in active_refusal.stderr
        assert sql("SELECT count(*) FROM pg_roles WHERE rolname IN ('odoo_app', 'n8n_app');") == "0"
        sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='legacy_archive' AND pid <> pg_backend_pid();")
        sql("CREATE DATABASE later_archive;")
        sql("CREATE TABLE preserved(id integer PRIMARY KEY); INSERT INTO preserved VALUES (42);", "later_archive")
        stale_inventory = docker("exec", *env, name, "sh", "-c",
                                 "PATH=/tmp/stub:$PATH bash /tmp/migrate-n8n-db-role.sh apply /tmp/backup", check=False)
        assert stale_inventory.returncode != 0 and "extra database inventory differs" in stale_inventory.stderr
        assert sql("SELECT count(*) FROM pg_roles WHERE rolname IN ('odoo_app', 'n8n_app');") == "0"
        docker("exec", *env, name, "bash", "/tmp/migrate-n8n-db-role.sh", "backup", "/tmp/backup")
        sql("CREATE SCHEMA custom_application;", "lager2")
        refused = docker("exec", *env, name, "sh", "-c",
                         "PATH=/tmp/stub:$PATH bash /tmp/migrate-n8n-db-role.sh apply /tmp/backup", check=False)
        assert refused.returncode != 0 and "additional schemas" in refused.stderr
        assert sql("SELECT tableowner FROM pg_tables WHERE tablename='preserved';", "n8n") == "legacy_review"
        sql("DROP SCHEMA custom_application;", "lager2")
        docker("exec", *env, name, "sh", "-c",
               "PATH=/tmp/stub:$PATH bash /tmp/migrate-n8n-db-role.sh apply /tmp/backup")
        owners = sql("SELECT datname || ':' || pg_get_userbyid(datdba) FROM pg_database ORDER BY datname;", user="pwr_db_admin").splitlines()
        assert "n8n:n8n_app" in owners
        assert "lager1:odoo_app" in owners and "lager2:odoo_app" in owners
        # The inert original bootstrap role retains PostgreSQL system objects.
        assert "postgres:" + bootstrap in owners
        assert all(not row.endswith(":n8n_app") for row in owners if not row.startswith("n8n:"))
        assert sql("SELECT count(*) FROM pg_tablespace WHERE spcowner = (SELECT oid FROM pg_roles WHERE rolname IN ('n8n_app'));", user="pwr_db_admin") == "0"
        assert sql("SELECT rolsuper, rolcanlogin FROM pg_roles WHERE rolname='legacy_review';", user="pwr_db_admin") == ("t|f" if legacy_is_bootstrap else "f|f")
        assert sql("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='legacy_archive';", user="pwr_db_admin") == "legacy_review"
        assert sql("SELECT id FROM preserved;", "legacy_archive", "pwr_db_admin") == "42"
        for role in ("odoo_app", "n8n_app"):
            denied = docker("exec", name, "psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", "-U", role, "-d", "legacy_archive", "-c", "SELECT 1", check=False)
            assert denied.returncode != 0
        verify_env = ["-e", "POSTGRES_USER=pwr_db_admin", "-e", "PGPASSWORD=test-admin",
                      "-e", "ODOO_DB_NAME=lager1", "-e", "ODOO_LAGER2_DB_NAME=lager2",
                      "-e", "ODOO_DB_PASSWORD_FILE=/tmp/odoo.pass", "-e", "N8N_DB_PASSWORD_FILE=/tmp/n8n.pass"]
        docker("exec", *verify_env, name, "bash", "/tmp/verify-db-role-isolation.sh")
        sql("GRANT CONNECT ON DATABASE legacy_archive TO n8n_app;", user="pwr_db_admin")
        regression = docker("exec", *verify_env, name, "bash", "/tmp/verify-db-role-isolation.sh", check=False)
        assert regression.returncode != 0 and "extra database" in regression.stderr
        for db, role in (("n8n", "n8n_app"), ("lager1", "odoo_app"), ("lager2", "odoo_app")):
            assert sql("SELECT id FROM preserved;", db, role) == "42"
            assert sql("SELECT preserved_function();", db, role) == "42"
            assert sql("SELECT id FROM preserved_view;", db, role) == "42"
            sql("ALTER TABLE preserved ADD COLUMN app_column text; ALTER SEQUENCE preserved_id_seq RESTART WITH 43; ALTER TYPE preserved_enum ADD VALUE 'ready';", db, role)
            sql("BEGIN; CREATE TABLE app_write_probe(id integer); ROLLBACK;", db, role)
    finally:
        docker("rm", "-f", name, check=False)
