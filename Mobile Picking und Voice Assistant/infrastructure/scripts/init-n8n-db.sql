-- Laeuft genau einmal, beim ersten Start auf leerem pg_data
-- (docker-entrypoint-initdb.d), verbunden als POSTGRES_USER in der
-- Datenbank "postgres". n8n bekommt seine Datenbank hier; Eigentuemer ist
-- die Bootstrap-Rolle, dieselbe, mit der n8n laut docker-compose.yml
-- verbindet. Eine getrennte n8n_app-Rolle (Remediation R4) wurde geprueft
-- und verworfen -- siehe docs/architecture/ebene-6-docker-daten-sicherheit.md.
CREATE DATABASE n8n;
