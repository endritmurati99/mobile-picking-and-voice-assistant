---
title: Phase 0 - Infrastruktur
tags:
  - phase
  - infrastructure
  - docker
status: pending
---

# Phase 0 — Infrastruktur

> [!todo] Aktuelle Phase
> Docker-Stack starten, HTTPS einrichten, Erreichbarkeit auf mobilen Geräten verifizieren.
> **Go/No-Go:** Erst wenn alle Checkboxen ✅, beginnt Phase 1.

Überblick: [[00 - Projekt Übersicht]] | Architektur: [[System Architektur]] | Nächste Phase: [[Phase 1 - Odoo Datenmodell]]

---

## Voraussetzungen

- [ ] Docker Desktop installiert und gestartet
- [ ] `mkcert` installiert (`brew install mkcert` / `choco install mkcert`)
- [ ] LAN-IP des Docker-Hosts bekannt (z.B. `192.168.1.100`)
- [ ] Mindestens 6 GB RAM frei (Vosk-Modell: ~2 GB)

---

## Setup-Schritte

### Schritt 1: Environment einrichten
```bash
cd "Mobile Picking und Voice Assistant"
cp .env.example .env
```

`.env` befüllen:
```
POSTGRES_PASSWORD=<sicheres-passwort>
N8N_ENCRYPTION_KEY=$(openssl rand -hex 32)
N8N_WEBHOOK_SECRET=$(openssl rand -hex 16)
LAN_HOST=192.168.1.100
```
`ODOO_API_KEY` bleibt leer — wird nach Odoo-Setup generiert (Phase 1).

### Schritt 2: TLS-Zertifikate generieren
```bash
bash infrastructure/scripts/setup-certs.sh 192.168.1.100
```
Ausgabe: `infrastructure/certs/cert.pem` + `key.pem`

> [!important] CA auf Mobile-Geräte übertragen
> `$(mkcert -CAROOT)/rootCA.pem` per AirDrop (iOS) oder per USB (Android) auf Gerät übertragen und als vertrauenswürdige CA installieren.
> Details: [[PWA Implementierungshinweise]]

### Schritt 3: Docker Images bauen und starten
```bash
docker compose build
docker compose up -d
```

Erwartete Container (alle `Up`):
- `caddy` — Reverse Proxy :443 + :80
- `db` — PostgreSQL 16
- `odoo` — Odoo 18.0 (braucht ~60s zum Start)
- `backend` — FastAPI (wartet auf Odoo + Vosk)
- `vosk` — Vosk STT Deutsch (braucht ~30s für Modell-Load)
- `n8n` — n8n Orchestrator
- `pwa` — Caddy Static File Server

### Schritt 4: Status prüfen
```bash
docker compose ps
docker compose logs --tail=20 backend
docker compose logs --tail=20 vosk
```

---

## Go/No-Go Checkliste

| Kriterium | Prüfung | Status |
| --------- | ------- | ------ |
| Alle Container `Up` | `docker compose ps` | ☐ |
| HTTPS erreichbar | `curl -k https://localhost/api/health` → `200 OK` | ☐ |
| Odoo Login sichtbar | `http://<HOST>:8069/` im Desktop-Browser | ☐ |
| Grünes Schloss iOS | Kein Zertifikats-Fehler in iOS Safari | ☐ |
| Grünes Schloss Android | Kein Zertifikats-Fehler in Chrome Android | ☐ |
| n8n Setup-Wizard | `https://<LAN-IP>/n8n/` zeigt Setup | ☐ |

---

## Kill-Criteria

> [!danger] Kill-Kriterien — wenn zutreffend, alternativen Ansatz wählen
> - **iOS akzeptiert Zertifikat trotz CA-Installation nicht** → DNS-Lösung mit `.local`-Domain + MDNS versuchen
> - **Vosk startet nicht wegen RAM** → Kleineres Modell (`vosk-model-small-de`) nutzen
> - **n8n Webhook-URL falsch** → `WEBHOOK_URL` in `.env` auf `https://<LAN-IP>/n8n/` setzen

---

## Bekannte Probleme & Lösungen

| Problem | Lösung |
| ------- | ------ |
| `backend` container startet nicht | Odoo und Vosk noch nicht bereit — `docker compose restart backend` nach ~90s |
| `odoo` zeigt "Database not found" | Datenbank noch nicht erstellt → Phase 1 Schritt 1 |
| Odoo unter `https://<LAN-IP>/odoo/` zeigt nicht die Admin-Oberfläche | Für Setup direkt `http://<HOST>:8069/` verwenden |
| Port 443 belegt | Anderen Prozess beenden: `lsof -i :443` |
| iOS Zertifikat "Nicht vertrauenswürdig" | CA-Profil in Einstellungen → Allgemein → Info → Zertifikatsvertrauenseinstellungen aktivieren |

---

## Weiterführend

- [[System Architektur]] — Docker-Netzwerk-Details
- [[PWA Implementierungshinweise]] — HTTPS-Pflicht, CA-Installation auf Mobilgeräten
- [[Phase 1 - Odoo Datenmodell]] — Nächste Phase nach erfolgreichem Go
