# Einrichtungsanleitung

## Voraussetzungen

- Docker + Docker Compose v2
- mkcert (für lokale HTTPS-Zertifikate)
- Python 3.10+ (für Seed-Script)
- Mindestens 8 GB RAM auf dem Docker-Host (Vosk braucht ~2 GB)
- Feste LAN-IP für den Docker-Host

## Schritt-für-Schritt

### 1. Repository klonen und .env erstellen
```bash
cp .env.example .env
# .env ausfüllen — alle Felder mit HIER_... ersetzen
# N8N_ENCRYPTION_KEY generieren: openssl rand -hex 32
```

### 2. Zertifikate generieren
```bash
bash infrastructure/scripts/setup-certs.sh 192.168.1.100
# Ersetze mit deiner LAN-IP
```

### 3. CA auf mobile Geräte übertragen
CA-Datei: `mkcert -CAROOT` zeigt den Pfad. Die Datei `rootCA.pem` auf die Geräte übertragen.

**iOS:** Mail/AirDrop → Profil installieren → Einstellungen → Allgemein → Info → Zertifikatsvertrauenseinstellungen → aktivieren

**Android:** Einstellungen → Sicherheit → Zertifikat installieren → CA

### 4. Stack starten
```bash
docker compose build
docker compose up -d
```

### 5. Odoo initialisieren
- Browser: `http://<HOST>:8069/web/database/manager`
- Neue DB erstellen: Name `picking`, Admin-Passwort setzen
- Demo-Daten NICHT laden (wir nutzen eigene Seed-Daten)

### 6. Odoo API-Key generieren
- Odoo einloggen → Benutzermenü → Einstellungen → API-Schlüssel
- API-Key in `.env` als `ODOO_API_KEY` eintragen
- `docker compose restart backend`

### 7. Custom Module installieren
- Odoo → Apps → "Apps-Liste aktualisieren"
- Suche: "Quality Alert Custom"
- Installieren

### 8. Seed-Daten laden
```bash
python infrastructure/scripts/seed-odoo.py \
  --url http://localhost:8069 \
  --db picking \
  --user admin \
  --api-key <dein-api-key>
```

### 9. Testen
- Mobile Browser: `https://<LAN-IP>/`
- API-Docs: `https://<LAN-IP>/api/docs`
- Odoo Admin: `http://<HOST>:8069/`
- n8n: `https://<LAN-IP>/n8n/`

> Hinweis: Odoo 18 wird im aktuellen Setup für die Administration direkt über Port `8069` verwendet.

### 10. n8n Public API einrichten
- In n8n: `Settings > n8n API`
- Neuen API-Key mit Label + Ablaufzeit erzeugen
- Als lokale Umgebungsvariablen setzen:

```powershell
$env:N8N_API_KEY="<dein-frischer-n8n-api-key>"
$env:N8N_API_BASE="https://localhost/n8n/api/v1"
```

- Testen:

```powershell
powershell -ExecutionPolicy Bypass -File infrastructure/scripts/workflow.ps1 test-n8n-api
```

> Fuer lokale `https://localhost`-Tests akzeptiert das Script standardmaessig das lokale Zertifikat ohne strikte TLS-Pruefung.

### 11. n8n MCP einrichten
- In n8n: `Settings > Instance-level MCP`
- `Enable MCP access` aktivieren
- Die gewuenschten Workflows muessen veroeffentlicht, durch einen unterstuetzten Trigger ausloesbar und explizit fuer MCP freigegeben sein
- In `Connection details > Access Token` einen frischen MCP-Token erzeugen
- In Claude Code den MCP-Server lokal fuer dieses Projekt anlegen:

```powershell
claude mcp add -s local --transport http n8n-local https://localhost/n8n/mcp-server/http --header "Authorization: Bearer <dein-frischer-n8n-mcp-token>"
```

- Fuer lokale `mkcert`-Zertifikate vor `claude mcp list` und vor dem Start von `claude` zusaetzlich die Root-CA setzen:

```powershell
$ca = Join-Path ((mkcert -CAROOT).Trim()) "rootCA.pem"
$env:SSL_CERT_FILE = $ca
$env:NODE_EXTRA_CA_CERTS = $ca
```

- Danach pruefen:

```powershell
claude mcp list
claude mcp get n8n-local
```

- Wenn du den Server spaeter neu setzen willst:

```powershell
claude mcp remove n8n-local -s local
```

## Troubleshooting

| Problem | Lösung |
|---------|--------|
| Zertifikat-Warnung auf iOS | CA-Trust in Einstellungen → Info → Zertifikatsvertrauenseinstellungen aktivieren |
| Odoo startet nicht | `docker compose logs odoo` — oft PostgreSQL-Verbindung oder Modul-Fehler |
| getUserMedia undefined | HTTPS nicht aktiv — Caddy/Zertifikat prüfen |
| Vosk antwortet nicht | Container braucht ~30s zum Modellladen; `docker compose logs vosk` |
| `test-n8n-api` liefert 401/403 | API-Key neu erzeugen und pruefen, dass wirklich `N8N_API_KEY` gesetzt ist |
| `n8n-local` MCP verbindet nicht | MCP in n8n aktivieren, Workflow-Freigaben pruefen und den lokalen Claude-Code-Eintrag mit `claude mcp add -s local --transport http ...` neu anlegen |
| `n8n-local` bleibt trotz korrektem Token `Failed to connect` | Fuer lokales HTTPS mit `mkcert` `SSL_CERT_FILE` und `NODE_EXTRA_CA_CERTS` auf `rootCA.pem` setzen und `claude mcp list` erneut ausfuehren |
