-- Idempotent schema/grant bootstrap for the n8n database.
--
-- Database and role creation for n8n_app happen in
-- infrastructure/scripts/init-db-roles.sh, not here, because passwords
-- cannot be committed into a SQL file that Postgres auto-runs from
-- docker-entrypoint-initdb.d. This file only assumes n8n_app already
-- exists and makes the n8n database's public schema safe to use.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO n8n_app;
ALTER SCHEMA public OWNER TO n8n_app;
ALTER DEFAULT PRIVILEGES FOR ROLE n8n_app GRANT ALL ON TABLES TO n8n_app;
ALTER DEFAULT PRIVILEGES FOR ROLE n8n_app GRANT ALL ON SEQUENCES TO n8n_app;
