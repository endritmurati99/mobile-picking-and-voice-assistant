---
title: Claude Code Workflow
tags:
  - architecture
  - workflow
  - claude-code
---

# Claude Code Workflow

## Ziel

Das Repository wurde auf einen schlankeren Claude-Code-Workflow umgestellt, damit Code-Arbeit, Kontext-Hygiene und Obsidian-Dokumentation sauber zusammenspielen.

## Umgesetzte Struktur

- Projektweite Claude-Code-Konfiguration liegt in `.claude/settings.json`
- Die operative Projektanweisung liegt nur noch in `Mobile Picking und Voice Assistant/CLAUDE.md`
- Spezialisierte Subagents liegen in `.claude/agents/`
- Datei-Aenderungen werden ueber einen Hook nach Obsidian protokolliert

## Wichtige Entscheidungen

### 1. Keine tote `.claudecodeignore`

Statt einer rein textuellen Ignore-Datei nutzt die aktuelle Claude-Code-Version projektweite Regeln in `.claude/settings.json`.

Aktive Schutzregeln:
- blockieren `.obsidian/`
- blockieren Python-Caches und `node_modules/`
- blockieren Bilddateien und ZIP-Artefakte
- blockieren `.env` und TLS-Zertifikate

### 2. Kleine `CLAUDE.md` statt Monolith

Die fruehere `CLAUDE.md` war als Wissensspeicher zu gross und hat zu viel irrelevanten Kontext in Sessions gezogen. Die neue Version enthaelt nur:

- harte Architektur-Invarianten
- Arbeitszonen
- Standard-Kommandos
- Delegationsregeln fuer Subagents
- Pflicht zur Obsidian-Dokumentation

### 3. Subagents statt unscharfer Rollenbeschreibungen

Es gibt jetzt drei fokussierte Subagents:

- `frontend-vanilla-pwa`
- `odoo-backend-specialist`
- `n8n-workflow-operator`

Damit kann Claude Code Aufgaben gezielter delegieren, ohne die gesamte Projektoberflaeche gleichzeitig im Kontext zu halten.

### 4. Obsidian-Logging als fester Workflow-Baustein

Ein `PostToolUse`-Hook schreibt jede von Claude Code bearbeitete Datei nach:

`Notzien (Obsidian)/04 - Ressourcen/Claude Code Aenderungslog.md`

Zusaetzlich sollen Architektur- und Prozessentscheidungen weiterhin manuell in der Daily Note dokumentiert werden.

## MCP-Stand

Playwright ist als inline MCP innerhalb des Frontend-Subagents vorgesehen und wird nur dort geladen, wo Browser-Tests wirklich gebraucht werden.

Der PostgreSQL-MCP wurde noch nicht projektweit aktiviert, weil die Datenbank im aktuellen Compose-Setup nicht auf dem Host-Port freigegeben ist. Bevor das aktiviert wird, ist eine bewusste Entscheidung noetig:

- sichere Host-Freigabe nur auf `127.0.0.1`
- oder ein lokaler Wrapper, der ueber Docker an die DB geht

## Naechste sinnvolle Schritte

1. Playwright-MCP projektweit oder nur inline testen
2. sicheren Zugangspfad fuer PostgreSQL-MCP festlegen
3. n8n-Workflow-Validator als Skript oder Subagent ergaenzen
