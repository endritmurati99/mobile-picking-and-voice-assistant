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
- fuer den Live-Betrieb einen dedizierten technischen Service-User verwenden
- Odoo einloggen → Benutzermenü → Einstellungen → API-Schlüssel
- API-Key in `.env` als `ODOO_API_KEY` eintragen
- keinen Passwort- oder `admin`-Fallback fuer den produktiven Backend-Betrieb verwenden
- `docker compose restart backend`

### 7. Custom Module installieren
- Odoo → Apps → "Apps-Liste aktualisieren"
- Suche: "Quality Alert Custom"
- Installieren

### 7b. Optional: zweite Odoo-Instanz fuer den Lagerumschalter

Der PWA-Umschalter liest `GET /api/instances`. Das lokale Standardprofil heisst technisch `local`.
Eine zweite lokale Testinstanz kann ueber das optionale Compose-Profil `second-odoo` gestartet werden:

```powershell
docker compose --profile second-odoo up -d odoo-lager-2
```

Sie nutzt Port `8070`, ein eigenes Filestore-Volume und die Odoo-Datenbank `lager2`.
Das Backend wird erst ueber `.env` bzw. die Shell-Umgebung auf dieses Profil aufmerksam:

```powershell
ODOO_INSTANCES_JSON={"lager-2":{"display_name":"Lager 2","url":"http://odoo-lager-2:8069","db":"lager2","user":"admin","password":"<passwort-oder-api-key>"}}
```

Regeln:

- `display_name` ist die sichtbare Bezeichnung in der PWA, z. B. `Lager 1` / `Lager 2`.
- `url`, `db`, `user`, `api_key` und ggf. `password` bleiben lokal in `.env` oder der Shell; keine Secrets committen.
- `local` kommt immer aus den bestehenden `ODOO_*`-Variablen und wird nicht aus `ODOO_INSTANCES_JSON` ueberschrieben.
- Nach Aenderung von `.env`: `docker compose up -d backend --force-recreate` oder Stack neu starten.
- Fuer eine frische `lager2`-DB: Custom-Module installieren und dann `seed-odoo.py --url http://localhost:8070 --db lager2 --user admin --api-key <passwort-oder-api-key>` ausfuehren.

Fachliche Mindestdaten fuer einen echten Live-Test:

- Das Custom-Addon `quality_alert_custom` muss in jeder Zielinstanz installiert/aktualisiert sein.
- Testprodukte brauchen gepflegte Barcodes, damit Scan-Confirm real pruefbar ist.
- Serienpflichtige Produkte muessen in Odoo `tracking = serial` oder `tracking = lot` haben.
- Am erwarteten Lagerplatz muss verfuegbarer Bestand (`stock.quant`) vorhanden sein.
- Es muss mindestens einen aktiven internen Picker-Benutzer geben.

### 7c. Lokales KI-Modell fuer die Qualitaetsbewertung (offline)

Die KI-Bewertung der Quality Alerts laeuft ueber ein lokales Sprachmodell (Ollama)
auf dem Lab-PC — ohne Internet. Der n8n-Workflow `quality-alert-created` ruft dazu
den Backend-Endpoint `POST /api/internal/llm/quality-disposition` auf; das Backend
spricht mit dem Ollama-Container. Faellt das Modell aus (Timeout, ungueltige Antwort),
nutzt der Workflow automatisch die eingebaute Heuristik als Fallback.

Der Ollama-Container startet mit dem Stack. Modell einmalig laden:

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b
```

Regeln:

- Konfiguration ueber `.env`: `LLM_PROVIDER`, `LLM_ENDPOINT`, `LLM_MODEL`, `LLM_TIMEOUT_MS`.
- n8n erreicht Ollama **nicht** direkt (SSRF-Policy erlaubt nur `backend`); der Aufruf laeuft bewusst ueber das Backend.
- CPU-only genuegt (i7-4790, 32 GB RAM). Die Bewertung ist asynchron; Latenz ist unkritisch.
- Zum Abschalten des lokalen Modells `LLM_PROVIDER` auf einen anderen Wert setzen (z. B. `disabled`) — dann bewertet nur die Heuristik.

### 7d. Voice-Intent-Fallback (optional, klein und schnell)

Der Voice-Assistent erkennt haeufige Kommandos deterministisch (Regex/Fuzzy).
Nur unklare, frei formulierte Aeusserungen gehen an ein **kleines** lokales
Modell, das sie einem bekannten Befehl zuordnet. Einmalig laden:

```bash
docker compose exec ollama ollama pull qwen2.5:1.5b
```

Regeln:

- Konfiguration ueber `.env`: `LLM_VOICE_MODEL` (Default `qwen2.5:1.5b`), `LLM_VOICE_TIMEOUT_MS` (Default `4000`). Endpoint wird von `LLM_ENDPOINT` mitbenutzt.
- Ohne das Modell faellt der Classifier **fail-closed** aus: Voice funktioniert weiter rein deterministisch, nur ohne LLM-Auffangnetz.
- Schreib-Kommandos (bestaetigen/buchen) vom LLM werden immer als Rueckfrage (Read-back) behandelt, nie direkt gebucht.
- Ein kleineres Modell (`qwen2.5:0.5b`) geht auch — per `LLM_VOICE_MODEL` tauschbar, Geschwindigkeit vs. Trefferquote live abwaegen.

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

> Hinweis: Odoo 19 wird im aktuellen Setup für die Administration direkt über Port `8069` verwendet.
> Bestehende Odoo-18-Datenbanken nicht blind mit dem Odoo-19-Container starten.
> Vor einem Wechsel der Hauptinstanz: Datenbank sichern und eine echte Major-Migration
> durchführen. Für technische Smokes eine frische Odoo-19-Datenbank verwenden.

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

### 10b. n8n Workflows kontrolliert ausrollen
- vor dem Live-Rollout erst die Repo-Gates ausfuehren:
  - `python infrastructure/scripts/verify-workflows.py`
  - relevante `pytest`-Tests
  - `node --test n8n/tests/assess-alert-v2.test.mjs`
- Backup erzeugen:

```bash
bash infrastructure/scripts/import-workflows.sh backup
```

- Danach mit dem ausgegebenen Backup-Verzeichnis:

```bash
bash infrastructure/scripts/import-workflows.sh import <backup-dir>
bash infrastructure/scripts/import-workflows.sh activate <backup-dir> error-trigger.json
bash infrastructure/scripts/import-workflows.sh activate <backup-dir> voice-exception-query.json
bash infrastructure/scripts/import-workflows.sh activate <backup-dir> quality-alert-created.json
bash infrastructure/scripts/import-workflows.sh activate <backup-dir> shortage-reported.json
```

- Nach jeder Aktivierung den zugehoerigen Smoke-Test ausfuehren.

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
