# VPS Runbook - Hostinger Docker Deployment

Status: canonical VPS deployment and sizing runbook.  
Scope: prepare the Hostinger VPS, deploy the Docker stack, and roll out n8n workflows safely.

## 1. Rule: GitHub is the transfer path

Do **not** move the project as a ZIP by default.

Use GitHub:

```bash
mkdir -p ~/apps
cd ~/apps
git clone https://github.com/endritmurati99/mobile-picking-and-voice-assistant.git
cd mobile-picking-and-voice-assistant/'Mobile Picking und Voice Assistant'
```

If the repo already exists:

```bash
cd ~/apps/mobile-picking-and-voice-assistant
git fetch origin main
git reset --hard origin/main
cd 'Mobile Picking und Voice Assistant'
```

ZIP transfer is only for explicitly selected artifacts, never for the whole workspace. It can accidentally include `.env`, caches, local DBs, `node_modules`, Python deps, browser profiles, or old backups.

## 2. What belongs on the VPS

From Git:

- `docker-compose.yml`
- `docker-compose.prod.yml`
- `backend/`
- `odoo/`
- `pwa/`
- `n8n/workflows/`
- `infrastructure/`
- `docs/`

Never commit or ZIP by accident:

- `.env`
- API keys/passwords/tokens
- `node_modules/`
- `backend/.deps/`
- local database dumps unless explicitly sanitized
- browser profiles
- generated caches

Persist separately via Docker volumes/backups:

- `pg_data`
- `odoo_data`
- `n8n_data`
- `caddy_data`
- `caddy_config`

## 3. VPS sizing

The full stack is heavier than plain n8n.

Services:

- Caddy reverse proxy
- PostgreSQL
- Odoo 18
- FastAPI backend
- Whisper ASR service, model `small`
- n8n 2.13.3, Postgres-backed, currently `mem_limit: 2g`
- Cloudflare Tunnel, if used
- PWA static Caddy
- Mailpit only under dev profile in production overlay

Approximate RAM pressure:

| Component | Rough RAM |
| --- | ---: |
| PostgreSQL | 200-700 MB |
| Odoo | 700 MB-1.5 GB |
| Backend | 150-400 MB |
| n8n | 300 MB-2 GB limit |
| Whisper small | 1-2.5 GB |
| Caddy/PWA/Tunnel | <300 MB |

Recommendation:

- **2 GB RAM:** not suitable for the full stack.
- **4 GB RAM:** demo only, reduced stack, preferably no local Whisper, swap required.
- **8 GB RAM:** recommended minimum for the full PoC stack.
- **16 GB RAM:** comfortable for builds, logs, n8n image/binary data, and tests.

If VPS RAM is below 8 GB, first start without local Whisper and add it later only if memory allows.

## 4. Read-only VPS check

Run this on the VPS and paste the output before installing or starting anything:

```bash
set -e
printf '== host ==\n'
hostname
whoami
uname -a
cat /etc/os-release | sed -n '1,8p'

printf '\n== cpu/mem/disk ==\n'
nproc
free -h
df -h /
lsblk

printf '\n== docker ==\n'
command -v docker || true
command -v docker-compose || true
docker --version || true
docker compose version || true
systemctl is-active docker || true

printf '\n== ports ==\n'
ss -tulpn | grep -E ':(22|80|443|8069|5678|5432|5433|8025)\b' || true

printf '\n== firewall ==\n'
sudo ufw status verbose || true
```

Target posture:

- 80/443 may be public.
- 22 may be public but should be key-based and hardened.
- 8069, 5678, 5432/5433, 8025 should not be public.

## 5. Docker install, only if missing

State-changing. Run only after approval and only on Ubuntu 20.04/22.04/24.04 or compatible Hostinger image.

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
docker --version
docker compose version
```

Optional non-root Docker access:

```bash
sudo usermod -aG docker "$USER"
# log out and back in afterwards
```

## 6. Swap for small VPS

Use swap if RAM is 4-8 GB. Required if attempting anything on 2 GB.

Example 4 GB swap:

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

## 7. Environment setup

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

Required values:

- `POSTGRES_PASSWORD`
- `ODOO_PASSWORD`
- `ODOO_API_KEY`
- `N8N_ENCRYPTION_KEY`
- `N8N_CALLBACK_SECRET`
- `LAN_HOST` or production domain
- `CLOUDFLARE_TUNNEL_TOKEN` only if using tunnel
- `OPENAI_API_KEY` only if AI/Vision shadow workflows are enabled

Generate random secrets:

```bash
openssl rand -hex 32
```

## 8. Compose render check

Before starting:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config > /tmp/mobile-picking-compose.rendered.yml
grep -nE '5678:|8069:|5432:|5433:|8025:|--reload|/mnt/c|C:' /tmp/mobile-picking-compose.rendered.yml || true
```

Expected:

- no public n8n/Odoo/DB/Mailpit port bindings
- no backend `--reload`
- no Windows mounts

## 9. Start sequence

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull || true
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Health/log checks:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 n8n
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 odoo
curl -k https://localhost/api/health || true
```

## 10. n8n workflow rollout

Do not import workflows blind. Use the controlled script.

Backup first:

```bash
bash infrastructure/scripts/import-workflows.sh backup
```

Import inactive:

```bash
BACKUP_DIR="n8n/backups/<timestamp>"
bash infrastructure/scripts/import-workflows.sh import "$BACKUP_DIR"
```

Activate only selected production workflows:

```bash
bash infrastructure/scripts/import-workflows.sh activate "$BACKUP_DIR" error-trigger.json quality-alert-created.json
```

Rollback:

```bash
bash infrastructure/scripts/import-workflows.sh rollback "$BACKUP_DIR"
```

n8n Public API/MCP may be used, but tokens stay outside the repo:

```bash
export N8N_API_BASE='https://<domain>/n8n/api/v1'
export N8N_API_KEY='<do-not-commit>'
python3 infrastructure/scripts/test-n8n-api.py
```

## 11. First cleanup targets

If the VPS is too small or the stack is noisy:

1. Keep `mailpit` dev-only.
2. Make `whisper` optional or disable it initially.
3. Use either direct domain via Caddy or Cloudflare Tunnel, not both unless needed.
4. Do not activate old P1 Telegram/Gmail/Knowledge workflows unless they are part of the demo.
5. Keep n8n execution retention/pruning tight.
6. Avoid storing large image binaries in n8n executions longer than needed.

## 12. Decision gate before full deployment

Known before proceeding:

- VPS RAM
- vCPU count
- free disk space
- Docker/Compose availability
- public ports
- domain/tunnel choice
- whether local Whisper is required for the first demo

If any of these are unknown, run the read-only check in section 4 first.
