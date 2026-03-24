---
title: Projekt Übersicht
tags:
  - overview
  - project
aliases:
  - Übersicht
---

# LogILab Mobile Picking Assistant

> [!abstract] Bachelorarbeit PoC
> Hybrider, sprachgestützter mobiler Picking-Assistent auf Basis von Odoo 18 Community.
> Läuft vollständig lokal im LAN — kein Cloud, kein Internet erforderlich.

## Komponenten

| Komponente | Technologie | Status |
| ---------- | ----------- | ------ |
| Mobile PWA | HTML5 · Web Speech API · HID-Scanner | 🔵 In Entwicklung |
| HTTPS Proxy | Caddy 2 + mkcert | 🔵 In Entwicklung |
| App-Backend | FastAPI (Python 3.12) | 🔵 In Entwicklung |
| STT Engine | Vosk (Deutsch, lokal) | 🔵 In Entwicklung |
| Orchestrator | n8n | 🔵 In Entwicklung |
| ERP Backend | Odoo 18.0 Community | ✅ Konfiguriert |
| Datenbank | PostgreSQL 16 | ✅ Läuft |
| Quality Modul | quality_alert_custom | ✅ Implementiert |

## Phasen-Status

- [ ] **[[03 - Features/Phase 0 - Infrastruktur|Phase 0]]:** Infrastruktur (Docker + HTTPS)
- [ ] **[[03 - Features/Phase 1 - Odoo Datenmodell|Phase 1]]:** Odoo-Datenmodell (Custom Module + Seed)
- [ ] **[[03 - Features/Phase 2 - Backend und PWA Shell|Phase 2]]:** Backend + PWA-Shell
- [ ] **[[03 - Features/Phase 3 - Barcode Scanning|Phase 3]]:** Barcode-Scanning
- [ ] **[[03 - Features/Phase 4 - Voice Picking|Phase 4]]:** Voice-Picking (Vosk STT)
- [ ] **[[03 - Features/Phase 5 - n8n Orchestrierung|Phase 5]]:** n8n-Orchestrierung
- [ ] **[[03 - Features/Phase 6 - Integration und Lagertest|Phase 6]]:** Integration + Lagertest
- [ ] **[[03 - Features/Phase 7 - Härtung und Evaluation|Phase 7]]:** Härtung + Evaluation

## Schnell-Links

### Architektur
- [[01 - Architektur/System Architektur|System Architektur]] — Mermaid-Diagramm, Docker-Netzwerk, Datenflows
- [[01 - Architektur/API Dokumentation|API Dokumentation]] — Endpoint-Tabellen, Request/Response-Beispiele
- [[01 - Architektur/Odoo 18 Entscheidungen|Odoo 18 ADRs]] — JSON-RPC, API-Key, Breaking Changes, button_validate
- [[01 - Architektur/Voice Intent Engine|Voice Intent Engine]] — STT-Pipeline, Intent-Patterns, Kontext-Zustände
- [[01 - Architektur/PWA Implementierungshinweise|PWA Implementierungshinweise]] — iOS Safari Bugs, MediaRecorder, HTTPS

### Phasen-Tracking
- [[03 - Features/Phase 0 - Infrastruktur|Phase 0 — Infrastruktur]] — Docker-Setup, mkcert, HTTPS
- [[03 - Features/Phase 1 - Odoo Datenmodell|Phase 1 — Odoo Datenmodell]] — DB, Custom Module, Seed
- [[03 - Features/Phase 2 - Backend und PWA Shell|Phase 2 — Backend + PWA Shell]] — Endpoints testen, Mobile
- [[03 - Features/Phase 3 - Barcode Scanning|Phase 3 — Barcode Scanning]] — HID-Scanner, Touch-Fallback, EAN-13
- [[03 - Features/Phase 4 - Voice Picking|Phase 4 — Voice Picking]] — Vosk STT, Intent-Engine, TTS
- [[03 - Features/Phase 5 - n8n Orchestrierung|Phase 5 — n8n Orchestrierung]] — Webhooks, Workflows, Fire-and-Forget
- [[03 - Features/Phase 6 - Integration und Lagertest|Phase 6 — Integration + Lagertest]] — 20 Picks, Resilienztest
- [[03 - Features/Phase 7 - Härtung und Evaluation|Phase 7 — Härtung + Evaluation]] — SUS, NASA-TLX, Interview

### Ressourcen
- [[04 - Ressourcen/Links|Ressourcen & Links]] — Externe Docs, Vosk, Caddy, n8n
- [[05 - Future Functions/Future Functions|Future Functions]] — Roadmap nach MVP, Visual Sight Loop, proaktive n8n-Ideen

## MVP — Vertikaler Slice

```
Barcode scannen → FastAPI → Odoo JSON-RPC → Menge buchen (quantity) → TTS Bestätigung
```

## Zugänge (nach Stack-Start)

| Service | URL |
| ------- | --- |
| PWA | `https://<LAN-IP>/` |
| Odoo Admin | `http://<HOST>:8069/` |
| n8n | `https://<LAN-IP>/n8n/` |
| API Docs | `https://<LAN-IP>/api/docs` |

> [!note] Odoo-Zugriff im aktuellen Setup
> Für Einrichtung und Admin-Aufgaben wird Odoo direkt über `http://<HOST>:8069/` geöffnet.
> Der Proxy-Pfad `/odoo/` ist im aktuellen PoC kein verlässlicher Admin-Zugang.
