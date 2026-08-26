# Mobile Picking und Voice Assistant

Bachelorarbeits-Proof-of-Concept für mobiles und gebündeltes Kommissionieren
mit Odoo 19, FastAPI, einer installierbaren PWA sowie lokaler Sprach- und
Bildverarbeitung.

![Systemlandkarte von PWA, FastAPI, Odoo, Voice, Quality und lokalen KI-Diensten](<Mobile Picking und Voice Assistant/docs/architecture/ebene-1-systemlandkarte.svg>)

## Der aktuelle Stand

Der operative Weg bleibt bewusst kurz:

```text
Mitarbeiter → PWA → Caddy → FastAPI → Odoo 19
```

- Die PWA führt durch normale Aufträge und Cluster-Rundgänge.
- Scanner ist der robuste Primärpfad; Kamera, Touch und Voice sind ergänzende
  Bedienwege.
- Whisper erkennt deutsche Sprache, feste Intent-Regeln behandeln sichere
  Kommandos und Ollama unterstützt nur bei Unsicherheit.
- Piper spricht Antworten lokal; Browser-TTS ist der Rückfall.
- Odoo bleibt das System of Record für Aufträge, Bestand, Benutzer und
  Qualitätsmeldungen.
- n8n orchestriert ausschließlich asynchrone Quality-Prozesse und liegt nicht
  im Picking- oder Voice-Hot-Path.
- DINOv2, Farbhistogramme und lokale Text-/Bildmodelle unterstützen den
  Artikelabgleich und die Schadensbewertung. Unsicherheit führt zu
  `review_required`.

Die vollständige Beschreibung von Funktionen, Datenflüssen, Technologie-
entscheidungen, Fehlerverhalten und bekannten Grenzen steht in der
[Runtime-README](<Mobile Picking und Voice Assistant/README.md>).

## Die wichtigsten Abläufe

### Normales Picking

FastAPI lädt die zulässigen Odoo-Aufträge, reserviert einen geöffneten Auftrag
zeitlich begrenzt für Mitarbeiter und Gerät und hält den Claim per Heartbeat
aktiv. Positionen werden per Scanner, Kamera, Touch oder Voice bestätigt.
Idempotenzschlüssel verhindern doppelte Buchungen nach verlorenen Antworten.

### Cluster-Picking

Passende Odoo-Aufträge werden nach Lager, Ausliefertag, Zone, Kapazität und
Produktüberschneidung zu Vorschlägen gruppiert. Die PWA bündelt gemeinsame
Lagerstopps, behält Zielkarton und Odoo-Buchung aber für jeden Auftrag getrennt.

### Voice Assistant

```text
Mikrofon → PWA → FastAPI → Whisper → Intent-Regeln → sichere Aktion
                                      └─ bei Unsicherheit: Ollama
Antwort  ← PWA ← FastAPI ← Piper
```

Touch und Scanner bleiben verfügbar, wenn ein Sprach- oder Modelldienst
ausfällt. Riskante oder unsichere Schreibaktionen benötigen eine Bestätigung.

### Quality und lokale KI

```text
PWA → FastAPI → Odoo Alert + Fotos + Job + Outbox
    → HMAC-Dispatcher → n8n → lokale KI-Auswertung
    → signierter Callback → Odoo-Ergebnis oder review_required
```

Odoo speichert Alert, Anhänge, Integrationsjob und Outbox-Ereignis zuerst
gemeinsam. Erst danach beginnt die asynchrone Analyse. Wiederholungen werden
über Event-ID und Payload-Fingerprint dedupliziert.

## Repository-Struktur

| Pfad | Inhalt |
| --- | --- |
| `Mobile Picking und Voice Assistant/` | deploybarer Runtime-Stand |
| `Mobile Picking und Voice Assistant/backend/` | FastAPI und kontrollierte Abläufe |
| `Mobile Picking und Voice Assistant/pwa/` | mobile Oberfläche, Scanner und Voice |
| `Mobile Picking und Voice Assistant/odoo/` | eigene Odoo-19-Addons |
| `Mobile Picking und Voice Assistant/n8n/` | Registry, Workflows und Custom Nodes |
| `Mobile Picking und Voice Assistant/docs/` | Architektur, Setup und Runbooks |
| `Projekt-Wiki/` | Bachelorarbeits- und Projektdokumentation |

## Architektur und Betrieb

- [Architektureinstieg](<Mobile Picking und Voice Assistant/docs/ARCHITECTURE.md>)
- [Setup](<Mobile Picking und Voice Assistant/docs/SETUP.md>)
- [Voice-Kommandos](<Mobile Picking und Voice Assistant/docs/VOICE_COMMANDS.md>)
- [Projekt-Wiki](<Projekt-Wiki/00 - Start Hier (Übersichtskarte).md>)

Der Basis-Stack umfasst PWA, Caddy, FastAPI, Odoo 19, PostgreSQL, n8n,
Whisper, Piper, Ollama und den lokalen Einbettungsdienst. Nur Caddy
veröffentlicht im Basis-Stack Ports ins LAN.

## Bereinigter Runtime-Stand

Tests, E2E-Strecken, visuelle Baselines, Bildkorpus und historische Nachweise
wurden vor ihrer Entfernung unter den ursprünglichen relativen Pfaden im
privaten Repository
[`mobile-picking-test-evidence-archive`](https://github.com/endritmurati99/mobile-picking-test-evidence-archive)
gesichert. Das Archiv erfordert Zugriff.

Der Runtime-Split entfernte 39.914 Zeilen aus 283 Dateien. Im öffentlichen
Runtime-Stand bleiben deploybarer Code, benötigte Build-Dateien sowie direkt
referenzierte Markdown-, SVG-, Excalidraw- und Screenshot-Dokumentation.

## Bekannte Grenzen

- Das Backend startet in der Compose-Grunddatei noch mit Uvicorn `--reload`.
- Der produktive n8n-Workflow muss beim Deployment kontrolliert importiert und
  aktiviert werden.
- Quality-Bewertungen laufen auf dem aktuellen Host absichtlich seriell.
- Die PWA cached ihre Oberfläche, aber keine API-Daten oder Offline-Writes.

Stand: 26. August 2026.
