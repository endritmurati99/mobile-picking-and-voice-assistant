# Einrichtung

## Voraussetzungen

- Docker mit Compose v2
- `mkcert` für lokale HTTPS-Zertifikate
- Python 3.10+ für die Hilfsskripte
- feste LAN-IP des Docker-Hosts

## Basis-Stack

```bash
install -m 600 /dev/null .env
# Erforderliche Variablen und Secrets ausschließlich lokal in .env setzen.
bash infrastructure/scripts/setup-certs.sh <LAN-IP>
docker compose build
docker compose up -d
```

Der Basis-Stack veröffentlicht nur Caddy auf Port 80/443. Die PWA läuft unter
`https://<LAN-IP>/`, die API hinter `/api/`. Odoo, PostgreSQL und n8n sind
intern. Für lokale Direktzugriffe ist ausschließlich das Entwicklungs-Overlay
vorgesehen:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

## Odoo 19 initialisieren

Der Datenbank-Manager ist deaktiviert. Eine neue Datenbank wird per CLI
angelegt; bestehende Odoo-18-Datenbanken dürfen nicht mit dem Odoo-19-Container
gestartet werden.

```bash
docker compose run --rm --no-deps -T odoo \
  odoo --no-http --stop-after-init --workers=0 --max-cron-threads=0 \
  -d masterfischer_o19 --without-demo=all \
  -i base,mail,stock,stock_picking_batch,picking_assistant_core,picking_assistant_integration,quality_alert_custom
```

Danach in Odoo einen dedizierten technischen Benutzer/API-Schlüssel anlegen,
`ODOO_API_KEY` in `.env` setzen und das Backend neu starten. Seed-Daten werden
mit `python infrastructure/scripts/seed-odoo.py` geladen.

## Lokale Modelle und Qualitätsworkflow

Whisper verarbeitet Sprache lokal. Ollama wird für optionale Voice-Fallbacks
und Qualitätsbewertung verwendet; benötigte Modelle werden einmalig im
Container geladen, zum Beispiel:

```bash
docker compose exec ollama ollama pull qwen2.5:7b
docker compose exec ollama ollama pull gemma4:12b
```

Der produktive Quality-Vertrag ist v2: FastAPI sendet
`quality.assessment.requested.v1` an den Webhook `quality-assessment-v2`.
Die verbindliche Registry ist `n8n/workflow-registry.json`. n8n wird nicht über
eine öffentliche Basisroute, Public API oder MCP betrieben.

## Konfiguration und Laufzeit prüfen

```bash
docker compose --env-file .env config --quiet
docker compose ps
make help
```

Die Make-Ziele dieses Runtime-Repositories decken Setup, Build, Start/Stop,
Logs, Seed und Shell-Zugriffe ab. Die Bedienanleitung für Handys steht in
`docs/testing/bedienanleitung.md`; automatisierte Tests und Nachweise liegen im
privaten Test-/Evidence-Archiv.
