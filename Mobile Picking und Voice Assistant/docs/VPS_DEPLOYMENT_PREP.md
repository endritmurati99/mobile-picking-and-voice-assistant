# VPS Deployment Prep - Hostinger/Docker

Status: Vorbereitung, bevor Build-Integration und Live-n8n-Rollout passieren.

## 1. Klarstellung zur Umgebung

Der Hostinger-VPS kann und soll Docker ausfuehren. Die aktuelle OpenClaw-Agent-Runtime, in der diese Repo-Arbeit passiert, hat aber kein `docker` im PATH. Das bedeutet:

- Repo-Dateien, Compose, n8n-Workflows, Tests und Deployment-Skripte koennen hier vorbereitet werden.
- Live-Kommandos wie `docker compose ps`, `n8n import:workflow` im Container oder Stack-Starts muessen auf dem VPS/Host mit Docker-Zugriff laufen.
- Alternativ kann n8n ueber Public API oder MCP angebunden werden, wenn Token sicher ausserhalb des Repos gesetzt werden.

## 2. Zielzustand VPS

Auf dem VPS sollen laufen:

- Caddy als Reverse Proxy/TLS-Grenze
- FastAPI Backend
- Odoo
- PostgreSQL
- n8n
- optional lokale Hilfsdienste wie Mailpit nur in Dev, nicht public

Produktionsregeln:

1. Keine Admin-Ports offen ohne Reverse Proxy/Auth.
2. n8n nicht direkt auf `:5678` public exponieren.
3. Odoo nicht direkt auf `:8069` public exponieren.
4. Backend ohne `--reload`.
5. Secrets nur in `.env` oder VPS Secret Store, nie im Repo.
6. n8n Public API nur bewusst aktivieren, Key nie committen.
7. Vor Workflow-Import immer Backup exportieren.

## 3. VPS-Vorcheck

Auf dem VPS ausfuehren:

```bash
whoami
hostname
uname -a
cat /etc/os-release

docker --version
docker compose version

git --version
curl --version
openssl version

sudo ufw status verbose || true
ss -tulpn | grep -E ':(80|443|8069|5678|5432|5433|8025)\b' || true
```

Erwartung:

- Docker und Docker Compose vorhanden.
- Ports 80/443 duerfen extern offen sein.
- 8069/5678/5432/5433/8025 duerfen nicht extern offen sein.

## 4. Repo-Checkout auf VPS

```bash
mkdir -p ~/apps
cd ~/apps
git clone https://github.com/endritmurati99/mobile-picking-and-voice-assistant.git
cd mobile-picking-and-voice-assistant/'Mobile Picking und Voice Assistant'
```

Falls Repo schon existiert:

```bash
cd ~/apps/mobile-picking-and-voice-assistant
git fetch origin main
git reset --hard origin/main
cd 'Mobile Picking und Voice Assistant'
```

Achtung: Nach History-Rewrite muessen alte lokale Klone hart resettet oder neu geklont werden.

## 5. Environment-Datei

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

Pflichtwerte pruefen:

- `POSTGRES_PASSWORD`
- `ODOO_PASSWORD`
- `ODOO_API_KEY`
- `N8N_ENCRYPTION_KEY`
- `N8N_CALLBACK_SECRET`
- `LAN_HOST` oder Domain
- ggf. `OPENAI_API_KEY` nur wenn Vision/Shadow-AI aktiv genutzt wird

Keys generieren:

```bash
openssl rand -hex 32
```

## 6. Compose-Auswahl

Empfohlen fuer VPS:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config > /tmp/mobile-picking-compose.rendered.yml
```

Dann manuell pruefen:

```bash
grep -nE '5678:|8069:|5432:|5433:|8025:|--reload|/mnt/c|C:' /tmp/mobile-picking-compose.rendered.yml || true
```

Erwartung:

- keine direkten public n8n/Odoo/DB/Mailpit-Portbindungen
- kein Backend `--reload`
- keine Windows-Mounts

## 7. Stack starten

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull || true
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Health prüfen:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 n8n
curl -k https://localhost/api/health || true
```

## 8. n8n Workflow-Rollout auf VPS

Erst Backup:

```bash
bash infrastructure/scripts/import-workflows.sh backup
```

Dann Import inaktiv:

```bash
BACKUP_DIR="n8n/backups/<timestamp>"
bash infrastructure/scripts/import-workflows.sh import "$BACKUP_DIR"
```

Dann gezielt aktivieren:

```bash
bash infrastructure/scripts/import-workflows.sh activate "$BACKUP_DIR" error-trigger.json quality-alert-created.json
```

Rollback:

```bash
bash infrastructure/scripts/import-workflows.sh rollback "$BACKUP_DIR"
```

## 9. n8n API/MCP Option

Wenn n8n Public API genutzt wird:

```bash
export N8N_API_BASE='https://<domain>/n8n/api/v1'
export N8N_API_KEY='<nicht committen>'
python3 infrastructure/scripts/test-n8n-api.py
```

Claude Code MCP darf nur lokal/persoenlich eingerichtet werden, nicht im Repo:

```bash
claude mcp list
# bei Bedarf lokal, mit sicherem Token:
# claude mcp add -s local --transport http <n8n-mcp-url>
```

## 10. Reihenfolge fuer unser Projekt

1. VPS-Docker/Ports/Env verifizieren.
2. Aktuellen Compose-Render pruefen.
3. Stack starten oder bestehenden Stack sichern.
4. n8n Backup exportieren.
5. Neuen Quality-Vision-Workflow erst als Shadow Workflow importieren.
6. Testdaten/LEGO-Fixtures durchlaufen lassen.
7. Erst nach stabiler Shadow-Auswertung operative Writebacks aktivieren.
