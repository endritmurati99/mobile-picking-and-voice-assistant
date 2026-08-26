# Mobile Picking und Voice Assistant

Mobile Picking mit mobiler PWA, FastAPI, Odoo 19 und lokalem Voice-/KI-Stack.
Odoo ist das System of Record; die PWA spricht ausschließlich mit FastAPI.
n8n verarbeitet nur asynchrone Qualitätsereignisse.

## Architektur

`PWA → Caddy → FastAPI → Odoo` ist der operative Pfad. Caddy ist die einzige
öffentliche Kante im Basis-Stack; Odoo, PostgreSQL und n8n bleiben intern.
Whisper, Piper, Ollama und der Embedding-Dienst laufen lokal im Docker-Netz.
Der aktuelle Quality-Workflow ist `quality-assessment-v2.json` und wird durch
[`n8n/workflow-registry.json`](n8n/workflow-registry.json) beschrieben.

## Start

```bash
cp .env.example .env
# Werte und Secrets in .env setzen
bash infrastructure/scripts/setup-certs.sh <LAN-IP>
docker compose build
docker compose up -d
```

Die Initialisierung einer Odoo-19-Datenbank, die Konfiguration und die
Mobilgeräte-Einrichtung stehen in [docs/SETUP.md](docs/SETUP.md).
Für lokale Direktzugriffe dient das bewusste Overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

## Prüfen

```bash
make install-backend-deps
make verify-code
make verify-workflows
```

`make test-odoo` benötigt eine wegwerfbare Docker-Testdatenbank. `make
verify-stack` prüft einen bereits laufenden lokalen Stack.

## Dokumentation

- [Architektur](docs/ARCHITECTURE.md)
- [Voice-Kommandos](docs/VOICE_COMMANDS.md)
- [Betriebs- und Backup-Runbook](docs/runbooks/backup-und-wiederherstellung.md)
- [Testanleitung](docs/testing/bedienanleitung.md)
- [Entscheidungen](docs/DECISIONS.md)

Datierte Scorecards, Evaluierungen und die stillgelegten Browserartefakte in
`e2e/` sind Nachweise, nicht der aktuelle Betriebsvertrag.
