---
title: Backend (FastAPI)
tags:
  - backend
  - fastapi
  - api
  - odoo
  - n8n
  - voice
  - idempotenz
created: 2026-06-22
---

# Backend (FastAPI)

> [!info] Was diese Notiz ist
> Die zentrale Referenz für das **FastAPI-Backend** des Projekts "Mobile Picking und Voice Assistant". Sie beschreibt die Rolle des Backends, die Modulstruktur, alle Router und Endpunkte, die Services, die Konfiguration, das Idempotenz- und Identitäts-Konzept sowie den n8n-Vertrag (raus- und reingehende Webhooks). Alle Angaben sind aus dem Quellcode belegt; konkrete Dateipfade, Endpunkte und Odoo-Modellnamen sind genannt.

Schwesternotizen: [[00 - Start Hier (Übersichtskarte)]] · [[02 - Architektur & Diagramm erklärt]] · [[03 - Docker & Container]] · [[06 - Odoo]] · [[07 - n8n]] · [[08 - PWA & Voice-Pfad]] · [[10 - Glossar]]

---

## 1. Rolle des Backends

Das FastAPI-Backend ist die **App-API** des Systems. Es ist die **einzige Schicht, mit der die PWA spricht** — die PWA redet niemals direkt mit Odoo oder n8n, sondern ausschließlich mit diesem Backend unter dem Prefix `/api`.

Man kann sich das Backend als **Vermittler ("Adapter") mit Gedächtnis** vorstellen. Es übernimmt fünf Kernaufgaben:

| Rolle | Bedeutung (einfach erklärt) | Beleg im Code |
|-------|------------------------------|----------------|
| **App-API für die PWA** | Die einzige Tür, durch die die mobile App spricht. Alle Routen liegen unter `/api`. | `app/main.py` (`include_router(..., prefix="/api")`) |
| **Idempotente Write-Schicht** | Schreibende Aktionen (Pick bestätigen, Alert anlegen, ...) können **mehrfach gesendet werden, ohne doppelt zu wirken**. Wackliges WLAN auf dem Gerät schadet so nicht. | `app/services/mobile_workflow.py`, Odoo-Tabelle `picking.assistant.idempotency` |
| **Odoo-Adapter** | Übersetzt App-Anfragen in **JSON-RPC-Aufrufe an Odoo 18** (das "System of Record", also die Wahrheit über Lagerbestand & Aufträge). | `app/services/odoo_client.py` |
| **Synchroner Voice-Pfad** | Für Sprachanfragen wartet das Backend **live (synchron) auf eine Antwort von n8n** (bis zu 7 s) und liefert sonst eine lokale Notfall-Antwort. | `app/routers/voice.py`, `app/services/n8n_webhook.py` (`request_reply`) |
| **n8n-Anbindung** | Feuert Ereignisse **raus** an n8n (Webhooks) und nimmt Ergebnisse über `/internal/n8n`-Callbacks **rein**. | `app/services/n8n_webhook.py`, `app/routers/n8n_internal.py` |

> [!note] "System of Record"
> Odoo ist die maßgebliche Datenquelle. Das Backend hält **keine eigene Geschäfts-Datenbank** für Pickings/Bestände — es liest und schreibt über JSON-RPC direkt in Odoo. Auch der Idempotenz-Speicher liegt **in Odoo** (Tabelle `picking.assistant.idempotency`), nicht in einer separaten Backend-DB.

---

## 2. Modulstruktur

Verzeichnis: `backend/app/` (relativ zum Projekt `Mobile Picking und Voice Assistant/`)

```
backend/
└── app/
    ├── __init__.py
    ├── main.py                           # FastAPI-App + Router-Registrierung unter /api
    ├── config.py                         # Settings (Pydantic) + Umgebungsvariablen
    ├── dependencies.py                   # DI: Picker-Identität, Idempotency, n8n-Secret
    ├── routers/
    │   ├── health.py                     # GET /api/health
    │   ├── pickings.py                   # Picking-Operationen (Claim, Confirm, Route, Stock)
    │   ├── voice.py                      # Voice-Erkennung + Assist (STT/TTS)
    │   ├── quality.py                    # Quality Alerts mit Foto-Upload
    │   ├── scan.py                       # Barcode-Validierung
    │   ├── integration.py                # /api/integration/log (deprecated) + n8n-Secret
    │   ├── obsidian.py                   # Obsidian-Suche + Logging
    │   └── n8n_internal.py               # Callbacks von n8n: Quality Assessment, Replenishment
    ├── services/
    │   ├── odoo_client.py                # JSON-RPC zu Odoo 18 (System of Record)
    │   ├── n8n_webhook.py                # Outbound Events + Sync Request/Reply + Circuit Breaker
    │   ├── mobile_workflow.py            # Picker-Identität, Idempotency, Picking-Claims
    │   ├── picking_service.py            # Picking-Logik: Bestätigung, Lagerbestand, Route
    │   ├── whisper_client.py             # Server-side STT zu lokalem Whisper-Container
    │   ├── piper_client.py               # Server-side TTS zu lokalem Piper-Container
    │   ├── route_optimizer.py            # Deterministische Routen-Heuristik
    │   ├── quality_shadow_evaluation.py  # Research: Lokale Fallback-Heuristik für Quality
    │   ├── obsidian_context.py           # Obsidian-Vault-Suche für Kontext
    │   ├── intent_engine.py              # Deterministische Voice-Intent-Erkennung
    │   ├── integration_log.py            # Tägliche Notizen ins Obsidian schreiben
    │   └── vosk_client.py                # (vorhanden, aber nicht aktiv genutzt)
    ├── models/
    │   ├── n8n.py                        # Pydantic: VoiceAssistRequest/Response, QualityAssessmentCallback, ...
    │   ├── picking.py                    # Pydantic: PickingResponse, MoveLineResponse, RouteStop
    │   ├── quality.py                    # (Quality-Modelle)
    │   └── voice.py                      # TTSRequest
    ├── schemas/
    │   └── obsidian.py                   # ObsidianLogRequest, ObsidianSearchRequest
    └── utils/
        ├── audio.py                      # Audio-Konvertierung (convert_to_wav)
        └── barcode.py                    # (Barcode-Utilities)
```

> [!info] Schichten auf einen Blick
> **routers/** = HTTP-Eingang (welche URL, welche Methode). **services/** = die eigentliche Arbeit (Odoo-Aufrufe, n8n, Intent-Erkennung). **models/ + schemas/** = Datenform (Pydantic). **utils/** = Helfer. Diese Trennung hält die Router dünn und die Logik testbar.

### app/main.py – FastAPI-Initialisierung

Datei: `backend/app/main.py`

```python
app = FastAPI(
    title="Picking Assistant API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# CORS-Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Router unter /api (Prefix)
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(pickings.router, prefix="/api", tags=["pickings"])
app.include_router(quality.router, prefix="/api", tags=["quality"])
app.include_router(voice.router, prefix="/api", tags=["voice"])
app.include_router(scan.router, prefix="/api", tags=["scan"])
app.include_router(integration.router, prefix="/api", tags=["integration"])
app.include_router(obsidian.router, prefix="/api", tags=["obsidian"])
app.include_router(n8n_internal.router, prefix="/api")  # Tags für /internal/n8n
```

> [!note] OpenAPI / Swagger
> Interaktive Doku unter `/api/docs`, Schema unter `/api/openapi.json`. Praktisch zum Ausprobieren der Endpunkte ohne PWA.

---

## 3. Konfiguration: config.py & dependencies.py

### app/config.py – Settings (Pydantic)

Datei: `backend/app/config.py` — Klasse `Settings` (Pydantic `BaseSettings`). Werte kommen aus Umgebungsvariablen (ENV); die Defaults stehen unten.

| Bereich | ENV-Variable(n) | Default | Zweck |
|---------|-----------------|---------|-------|
| **Odoo** | `odoo_url`, `odoo_db`, `odoo_user`, `odoo_api_key`, `odoo_password` | — | Verbindung zu Odoo 18 (JSON-RPC). Sowohl API-Key als auch Passwort werden für die Authentifizierung versucht. |
| **Whisper (STT)** | `whisper_url` | `http://whisper:9000` | Server-seitige Spracherkennung. |
| **Piper (TTS)** | `piper_url` | `http://piper:5500` | Server-seitige Sprachausgabe. |
| **n8n Basis** | `n8n_webhook_base` | `http://n8n:5678/webhook` | Basis-URL für ausgehende Webhooks. |
| **n8n Secrets** | `n8n_webhook_secret` | — | Auth-Header für ausgehende Calls. |
| | `n8n_callback_secret` | — | Prüfwert für eingehende Callbacks (`X-N8N-Callback-Secret`). |
| **n8n Pfade** | `quality-alert-created`, `voice-exception-query`, `shortage-reported`, `pick-confirmed` | (überschreibbar) | Webhook-Pfad-Overrides pro Event. |
| **n8n Timeouts** | `n8n_sync_timeout_ms` | `7000` | Max. Wartezeit auf synchrone Antwort (Voice). |
| | `n8n_connect_timeout_ms` | `1000` | Verbindungs-Timeout. |
| **n8n Circuit Breaker** | `n8n_circuit_breaker_failures` | `3` | Fehler bis zum Öffnen. |
| | `n8n_circuit_breaker_open_seconds` | `60` | Wie lange offen (Sekunden). |
| **Mobile Workflow** | `mobile_claim_ttl_seconds` | `120` | Gültigkeit einer Picking-Reservierung (Claim). |
| | `mobile_claim_heartbeat_seconds` | `30` | Heartbeat-Intervall. |
| | `mobile_idempotency_ttl_seconds` | `86400` | Lebensdauer Idempotency-Eintrag (24 h). |
| | `mobile_header_grace_mode` | `True` | Toleranter Umgang mit fehlenden Headern. |
| **CORS** | `cors_origins` | `https://localhost` | Erlaubte Web-Origins (kommagetrennt). |
| **Logging** | `log_level` | `info` | Log-Level. |

### app/dependencies.py – Dependency Injection (DI)

Datei: `backend/app/dependencies.py`. "DI" heißt: Die Router bekommen ihre Helfer (Odoo-Client, Services, geprüfte Identität) **automatisch von FastAPI gereicht**, statt sie selbst zu bauen.

| Funktion | Typ | Aufgabe |
|----------|-----|---------|
| `get_odoo_client()` | Singleton (`@lru_cache()`) | Liefert eine `OdooClient`-Instanz. |
| `get_n8n_client()` | Singleton (`@lru_cache()`) | Liefert einen `N8NWebhookClient`. |
| `get_picking_service()` | neue Instanz | Braucht `OdooClient` + `N8NWebhookClient`. |
| `get_mobile_workflow_service()` | neue Instanz | Braucht `OdooClient`. |
| `get_required_picker_identity(...)` | async | Validiert Header `X-Picker-User-Id` (numerisch), ruft `workflow.resolve_identity()` auf. Gibt `PickerIdentity` zurück **oder wirft 403**. |
| `get_write_request_context(...)` | — | Parst `Idempotency-Key`, `X-Picker-User-Id`, `X-Device-Id`. Gibt `WriteRequestContext` (ggf. unvollständig) zurück. |
| `require_n8n_callback_secret(...)` | Guard | Prüft `X-N8N-Callback-Secret` gegen `settings.n8n_callback_secret` mit `secrets.compare_digest()` (timing-sicher). |

> [!note] Singleton vs. neue Instanz
> `@lru_cache()` sorgt dafür, dass es genau **einen** Odoo- und einen n8n-Client gibt (Verbindungen werden wiederverwendet). Services wie `PickingService` werden pro Anfrage neu erzeugt, halten aber keine eigene Verbindung — sie nutzen die geteilten Clients.

---

## 4. Router & Endpunkte (Gesamtübersicht)

Alle Endpunkte liegen unter dem Prefix `/api`. Spalte "Auth" nennt die nötige Picker-Identität/Header; "Idemp." sagt, ob `Idempotency-Key` ausgewertet wird.

### 4.1 health.py

Datei: `backend/app/routers/health.py`

| Endpoint | HTTP | Zweck |
|----------|------|-------|
| `/health` | GET | Liefert `{ status: "ok", service: "picking-assistant-backend" }`. |

### 4.2 pickings.py

Datei: `backend/app/routers/pickings.py`

| Endpoint | HTTP | Zweck | Auth | Idemp. |
|----------|------|-------|------|--------|
| `/pickers` | GET | Liste aktiver Odoo-Benutzer. | — | — |
| `/products/{product_id}/image` | GET | Produktbild (128–1920 px, Base64-Decode). | — | — |
| `/pickings` | GET | Offene Pickings mit Move-Lines. | PickerIdentity (resolve) | — |
| `/pickings/{picking_id}` | GET | Einzelnes Picking mit Details. | PickerIdentity | — |
| `/pickings/{picking_id}/route-plan` | GET | Optimierte Reihenfolge verbleibender Positionen. | PickerIdentity | — |
| `/pickings/{picking_id}/claim` | POST | Picking für Gerät/Picker reservieren (Heartbeat-TTL). | `X-Picker-User-Id`, `X-Device-Id` | Ja |
| `/pickings/{picking_id}/heartbeat` | POST | Aktiven Claim verlängern. | `X-Picker-User-Id`, `X-Device-Id` | Ja |
| `/pickings/{picking_id}/release` | POST | Claim freigeben. | `X-Picker-User-Id`, `X-Device-Id` | Ja |
| `/pickings/{picking_id}/confirm-line` | POST | Pick-Zeile bestätigen (Scan + Menge). | `X-Picker-User-Id`, `X-Device-Id` | Ja |
| `/pickings/{picking_id}/replenishment-request` | POST | Nachschubanforderung bei out-of-stock. | `X-Picker-User-Id`, `X-Device-Id` | Ja |
| `/pickings/{picking_id}/stock` | GET | Stock-Snapshot für Produkt + Location. | PickerIdentity | — |

> [!info] Idempotenz-Muster (pickings)
> Request-Fingerprint (SHA256) + Eintrag in der Odoo-Tabelle `picking.assistant.idempotency`. Bei Wiederholung wird die **gecachte Response** zurückgegeben. TTL: `mobile_idempotency_ttl_seconds` (24 h).

### 4.3 voice.py

Datei: `backend/app/routers/voice.py`

| Endpoint | HTTP | Zweck | Idemp. |
|----------|------|-------|--------|
| `/voice/recognize` | POST | Audio → Whisper-STT + Intent-Erkennung. | — |
| `/voice/assist` | POST | Deterministischer Intent → **synchrone** n8n-Anfrage, sonst lokale Fallback-Antwort. | — |
| `/voice/tts` | POST | Text → Piper-TTS (WAV). | — |

Flows im Detail:
1. **`/voice/recognize`**: Audio (`multipart/form-data`) → Whisper (async) → Intent Engine → JSON mit Confidence, Normalisierung, Match-Strategie.
2. **`/voice/assist`**: `VoiceAssistRequest` (text, intent, picking_id, ...) → `N8NWebhookClient.request_reply()` (synchron, 7 s Timeout) → Fallback auf lokale Stock-Query + Obsidian-Kontext bei n8n-Fehler.
3. **`/voice/tts`**: Text → Piper-Synthese → WAV-Bytes oder **503** bei Fehler (PWA fällt dann auf Browser-TTS zurück).

### 4.4 quality.py

Datei: `backend/app/routers/quality.py`

| Endpoint | HTTP | Zweck | Auth | Idemp. |
|----------|------|-------|------|--------|
| `/quality-alerts` | POST | Alert erstellen + optional N Fotos + n8n-Dispatch. | `X-Picker-User-Id`, `X-Device-Id` | Ja (Fingerprint aus Description + Foto-SHAs) |

Flow:
1. Formulardaten: `description`, `picking_id`, `product_id`, `location_id`, `priority`, `photos[]` (beliebig viele).
2. Fotos als Base64 in Odoo schreiben (`ir.attachment`).
3. n8n Fire → `quality-alert-created` (async, keine synchrone Antwort).
4. Bei n8n-Fehler: lokale Fallback-Heuristik (Keyword-Matching auf Description) → Shadow-Assessment speichern.
5. Response: `alert_id`, `name`, `photo_count`, `ai_evaluation_status`.

### 4.5 scan.py

Datei: `backend/app/routers/scan.py`

| Endpoint | HTTP | Zweck |
|----------|------|-------|
| `/scan/validate` | POST | Gescannten Barcode gegen erwarteten Wert abgleichen. |

Input: `barcode` (URL-Parameter), `expected_barcode` (Query-Param, Default `""`).
Output: `{ match: bool, barcode, expected, message }`.

### 4.6 integration.py

Datei: `backend/app/routers/integration.py`

| Endpoint | HTTP | Zweck | Guard |
|----------|------|-------|-------|
| `/integration/log` | POST | Log-Event in tägliche Obsidian-Notiz schreiben. | `X-N8N-Callback-Secret` |

### 4.7 obsidian.py

Datei: `backend/app/routers/obsidian.py`

| Endpoint | HTTP | Zweck | Guard |
|----------|------|-------|-------|
| `/obsidian/log` | POST | (Deprecated) Log in tägliche Notiz. | `X-N8N-Callback-Secret` |
| `/obsidian/search` | GET | Freitext-Suche im Obsidian-Vault. | — |
| `/obsidian/search` | POST | Freitext-Suche (JSON-Body). | — |

### 4.8 n8n_internal.py (Inbound-Callbacks von n8n)

Datei: `backend/app/routers/n8n_internal.py`. Alle Endpunkte benötigen `X-N8N-Callback-Secret` **und** `Idempotency-Key` (Header). Alle sind idempotent (gleicher Key = gecachte Response).

| Endpoint | HTTP | Zweck | Inbound Payload | Wann sendet n8n? |
|----------|------|-------|-----------------|------------------|
| `/internal/n8n/quality-assessment` | POST | AI-Bewertung in Odoo speichern + Chatter-Note. | `QualityAssessmentCallbackRequest` | nach AI-Analyse |
| `/internal/n8n/quality-assessment-ai` | POST | Shadow-AI-Bewertung (Research-Log). | `QualityAssessmentAIRequest` (schema_v1, execution_id) | parallel zur AI-Assess |
| `/internal/n8n/replenishment-action` | POST | Nachschubauftrag erzeugen (Transfer anlegen). | `ReplenishmentActionRequest` | nach Shortage-Report |
| `/internal/n8n/quality-assessment-failed` | POST | AI-Bewertung fehlgeschlagen markieren. | `QualityAssessmentFailedRequest` | bei Fehler in n8n |
| `/internal/n8n/manual-review-activity` | POST | `mail.activity` + Chatter-Note auf Picking. | `ManualReviewActivityRequest` | bei Manual-Review-Bedarf |

> [!warning] Korrelation erzwungen
> Jeder Callback prüft den `Idempotency-Key` gegen `correlation_id` im Body. **Mismatch = 409, fehlend = 400.** Strukturierte JSON-Logs nach stdout (`event_type=quality_shadow_evaluation`, `callback_status` ∈ {applied, failed, replay, rejected, aborted}).

---

## 5. Services – was jeder tut

### 5.1 odoo_client.py — JSON-RPC zu Odoo 18

Datei: `backend/app/services/odoo_client.py` — Klasse `OdooClient`.

- **Authentifizierung** ist *lazy*: erst beim ersten `execute_kw()` wird `authenticate()` aufgerufen. Es werden sowohl `odoo_api_key` als auch `odoo_password` versucht; `_uid`/`_secret` werden gecached.
- **API:** `authenticate()`, `execute_kw(model, method, args, kwargs)`, `search_read(model, domain, fields, limit)`, `create(model, vals)`, `write(model, ids, vals)`, `call_method(model, method, ids, args, context)`.
- **Timeouts:** `httpx.Timeout(connect=5s, read=30s, write=10s, pool=5s)`.
- **Fehler:** `OdooAPIError`, wenn die JSON-RPC-Response ein `error`-Feld enthält.

> [!note] Odoo-18-Besonderheiten (wichtig fürs Verständnis)
> - Menge an der Bewegungszeile heißt `stock.move.line.quantity` (**nicht** mehr `qty_done`).
> - Picking-Bewegungen liegen unter `stock.picking.move_ids` (**nicht** `move_lines`).
> - Custom-Modelle des Projekts: `quality.alert.custom`, `picking.assistant.idempotency`.

### 5.2 n8n_webhook.py — Outbound-Events & Sync-Requests

Datei: `backend/app/services/n8n_webhook.py` — Klasse `N8NWebhookClient`.

- `fire_event(path, payload, picker, device_id, picking_context, correlation_id)` — Fire-and-forget. Gibt `N8NEventResult` (`delivered: bool`, `correlation_id`, `status_code`, `error`).
- `fire(...)` — Alias für `fire_event()`.
- `request_reply(path, payload, ..., timeout_ms, fallback_text)` — **synchroner** RPC: wartet auf JSON-Antwort bis `timeout_ms` (Default 7 s). Gibt `N8NReply` (`status`, `tts_text`, `source`, `correlation_id`, `latency_ms`, `fallback_reason`, `recommendation`).
- **Circuit Breaker** pro Pfad: öffnet nach `n8n_circuit_breaker_failures` (3) Fehlern für `n8n_circuit_breaker_open_seconds` (60 s); liefert dann Fallback-Reply mit `fallback_reason: "circuit_open"`.

> [!info] Circuit Breaker – Analogie
> Wie eine Sicherung im Stromkasten: Wenn n8n mehrfach hintereinander streikt, "fliegt die Sicherung raus" und das Backend antwortet eine Minute lang sofort mit der lokalen Fallback-Antwort, statt jedes Mal ins Timeout zu laufen. Das hält den Voice-Pfad schnell.

### 5.3 mobile_workflow.py — Picker-Identität & Idempotency

Datei: `backend/app/services/mobile_workflow.py`.

**Dataclasses:** `PickerIdentity` (`user_id`, `device_id`, `picker_name`; frozen; `is_complete` = beide vorhanden) · `WriteRequestContext` (`idempotency_key`, `identity`; frozen) · `IdempotencyReservation` (`status`, `entry_id`, `response_payload`, `status_code`; `should_replay`, `is_active`).

**Exceptions:** `ClaimConflictError` (Picking bereits reserviert → 409) · `InvalidPickerIdentityError` (User nicht aktiv/vorhanden → 403).

**Klasse `MobileWorkflowService`:** `list_pickers()`, `resolve_identity()`, `claim_picking()` (ruft Odoo `api_claim_mobile()` mit TTL; wirft bei Konflikt `ClaimConflictError`), `heartbeat_picking()`, `release_picking()`, `build_request_fingerprint(payload)` (SHA256 des normalisierten JSON), `begin_idempotent_request()`, `finalize_idempotent_request()`, `abort_idempotent_request()`.

### 5.4 picking_service.py — Picking-Business-Logik

Datei: `backend/app/services/picking_service.py` — Klasse `PickingService(odoo_client, n8n_client)`.

- `get_open_pickings()` — offene Stock-Pickings via `search_read`, angereichert mit Move-Lines + Voice-Instructions.
- `get_picking_detail(picking_id)` — einzelnes Picking + alle Move-Lines; Enrichment (Produktnamen, Location-Kurzformen, Voice-Intros).
- `get_picking_route_plan(picking_id)` — ruft `route_optimizer.build_route_plan()` auf.
- `confirm_pick_line(picking_id, move_line_id, scanned_barcode, quantity, picker_identity)` — bestätigt Zeile in Odoo (`stock.move.line.quantity`); feuert `pick-confirmed` (async); wirft `ClaimConflictError`, wenn nicht mehr geclaimt.
- `request_replenishment(picking_id, move_line_id, reason, picker_identity)` — erstellt Nachschubanforderung.
- `get_stock_snapshot(product_id, location_id)` — Stock-Quants laden, verfügbaren Bestand pro Location berechnen.

### 5.5 whisper_client.py — Server-side STT

Datei: `backend/app/services/whisper_client.py` — `transcribe_audio(audio_bytes, mime_type) -> str`. POST an `{whisper_url}/asr` mit Query `task=transcribe&language=de&output=json&encode=false`, Body `multipart/form-data` (`audio_file`). Timeout 60 s, persistenter httpx-Client (Keep-Alive, max. 2 Verbindungen, Pool-Expiry 30 s). Bei Fehler: Rückgabe `""` (nicht `None`).

### 5.6 piper_client.py — Server-side TTS

Datei: `backend/app/services/piper_client.py` — `synthesize(text, lang="de-DE") -> bytes | None`. POST an `{piper_url}/synthesize`, JSON `{ "text": ..., "lang": ... }`. Timeout 5 s — bei Timeout/Fehler `None` (PWA fällt auf Browser-TTS zurück). Persistenter httpx-Client.

### 5.7 route_optimizer.py — deterministische Route

Datei: `backend/app/services/route_optimizer.py` — `build_route_plan(move_lines) -> dict`. Strategie **"zone-first-shortest-walk"**: sortiert nach `picked`-Status (offen zuerst), Zone (links < mitte < rechts < andere), Location-Koordinaten (Regal/Ebene/Position) und alphabetisch; filtert auf noch offene Positionen; berechnet Sequenznummer, geschätzte Schritte (Manhattan-Distanz) und Zone. Response enthält u. a. `strategy`, `total_stops`, `remaining_stops`, `estimated_travel_steps`, `next_move_line_id`, `zone_sequence`, `stops[]`, `ordered_move_lines`.

> [!note] Deterministisch heißt nachvollziehbar
> Die Route entsteht aus festen Sortierregeln, nicht aus KI. Gleiche Eingabe → gleiche Reihenfolge. Das ist für eine Bachelorarbeit gut belegbar und reproduzierbar.

### 5.8 quality_shadow_evaluation.py — lokale Fallback-Heuristik (Research)

Datei: `backend/app/services/quality_shadow_evaluation.py` — `classify_quality_alert_shadow(alert) -> ShadowHeuristicResult`. Dataclass: `category` ∈ {damage, shortage, wrong_item, unclear}, `confidence` (0.0–1.0), `reason`, `scores`. Algorithmus: Beschreibung normalisieren (Lower, Umlaute, Negationen entfernen) → Keywords pro Kategorie (gewichtet) → ranken → bei Mehrdeutigkeit "unclear" → Confidence aus Score/Textlänge/Fotoanzahl. Einsatz: Fallback bei n8n-Fehler **und** als Shadow-Vergleich gegen die echte AI (Forschung).

### 5.9 obsidian_context.py — Vault-Suche für Kontext

Datei: `backend/app/services/obsidian_context.py` — `search_obsidian_notes(search_terms, limit=3) -> list[dict]` (Vault via ENV `OBSIDIAN_PATH`, Default `../../../Notzien`; tokenisiert ≥3 Zeichen; Score = Token-Häufigkeit + Pfad-Treffer) und `format_obsidian_hits(hits, max_chars=320) -> str`. Hit-Struktur: `{ title, path, excerpt, score }`. Wird im Voice-Assist als Zusatzkontext genutzt.

### 5.10 integration_log.py — Obsidian Daily Notes

Datei: `backend/app/services/integration_log.py` — `write_daily_note_log(request: ObsidianLogRequest) -> dict`. Schreibt nach `{OBSIDIAN_PATH}/02 - Daily Notes/{YYYY-MM-DD}.md` im Append-Modus (`\n- [HH:MM:SS] **{category}**: {message}`). Aufgerufen von `/api/integration/log` und `/api/obsidian/log`.

### 5.11 intent_engine.py — Voice-Intent-Erkennung

Datei: `backend/app/services/intent_engine.py`. Enums: `PickingContext` (IDLE, AWAITING_LOCATION_CHECK, AWAITING_QUANTITY_CONFIRM, AWAITING_COMMAND) · `VoiceSurface` (LIST, DETAIL, QUALITY_ALERT, COMPLETE). Dataclass `Intent`: `action` (confirm, next, problem, stock_query, done, pause, photo, repeat, help, filter_high, filter_normal, status, unknown, ...), `value`, `confidence`, `raw_text`, `normalized_text`, `match_strategy` (exact | regex | fuzzy | segment | unknown).

Thresholds: `EXACT_MATCH_CONFIDENCE = 0.95` · `FUZZY_SINGLE_THRESHOLD = 0.73` · `FUZZY_PHRASE_THRESHOLD = 0.68`.

`recognize_intent(text, context, surface, remaining_line_count, active_line_present) -> Intent`: Text normalisieren → Context-Checks (Zahlenextraktion) → negierte Bestätigung ("nicht ... bestätigen" → "problem") → Exact-Match (Aliase) → Regex → Fuzzy (Levenshtein) → Segment-Fallback → Context-Resolution. Aliase: pro Action viele umgangssprachliche Varianten ("jep", "jup", "ok", "passt", "mhm" → "confirm").

---

## 6. Idempotenz & Picker-Identität

### 6.1 Warum Idempotenz?

Auf einem Handheld im Lager bricht WLAN ab oder die App sendet aus Unsicherheit erneut. **Idempotenz** garantiert: Egal wie oft dieselbe schreibende Anfrage (gleicher `Idempotency-Key`) ankommt — sie wirkt **genau einmal**, und Wiederholungen bekommen exakt dieselbe Antwort zurück.

### 6.2 Speicher in Odoo: `picking.assistant.idempotency`

| Feld | Bedeutung |
|------|-----------|
| `endpoint` | welcher Endpunkt (indexiert) |
| `idempotency_key` | eindeutiger Schlüssel (unique) |
| `fingerprint` | SHA256 der normalisierten Payload |
| `picking_id`, `user_id`, `device_id` | Kontext (nullable) |
| `status` | `reserved` → `finalized` / `aborted` / `replay` / `pending` / `conflict` |
| `response_payload` | gecachte Antwort (JSON) |
| `status_code` | HTTP-Statuscode der Antwort |
| `created_at` / `updated_at`, `ttl_expires_at` | Zeitstempel; nach 24 h gelöscht |

### 6.3 Ablauf

1. Client sendet `Idempotency-Key` im Header.
2. `begin_idempotent_request()` prüft in Odoo:
   - **Gleicher Key + gleicher Fingerprint** → Reservation `replay` + gecachte Response zurück.
   - **Gleicher Key, anderer Fingerprint** → `conflict` → **409**.
   - **Nicht vorhanden** → neuer Eintrag `reserved` + `entry_id`.
3. Handler führt die Aktion aus.
4. `finalize_idempotent_request()` speichert Response + Status `finalized`.
5. Spätere Requests mit gleichem Key → `finalized` → gecachte Response.

TTL: `mobile_idempotency_ttl_seconds` (Default 86400 = 24 h).

### 6.4 Picker-Identität & Claim

- **Identität:** `user_id` (Odoo `res.users.id`) + `device_id` (von der PWA erzeugt) + optional `picker_name`. `is_complete` = beide vorhanden.
- **Verfügbarkeitsprüfung:** `res.users.search([("id","=",user_id),("active","=",True),("share","=",False)])` — nur aktive Nicht-Share-User dürfen picken.
- **Claim-TTL:** Ein Picking wird auf die Kombination User+Device reserviert; TTL `mobile_claim_ttl_seconds` (120 s), per Heartbeat (`/pickings/{picking_id}/heartbeat`) verlängerbar.

> [!warning] Header sind verbindlich (Write-Pfad)
> Alle schreibenden Picking-/Quality-Operationen erwarten `X-Picker-User-Id`, `X-Device-Id` und `Idempotency-Key`. Der Claim ist an **User UND Device** gebunden — so kann nicht ein zweites Gerät dasselbe Picking parallel abarbeiten. Bei Konflikt antwortet das Backend mit **409** (`ClaimConflictError`), bei ungültiger Identität mit **403** (`InvalidPickerIdentityError`).

---

## 7. Der n8n-Vertrag

Zwei Richtungen: das Backend **feuert Events raus** an n8n und nimmt Ergebnisse über `/internal/n8n`-**Callbacks rein**.

### 7.1 Outbound: Backend → n8n (Envelope-Format)

Jedes ausgehende Event hat denselben Umschlag (`event_name`, `schema_version: "v1"`, `correlation_id`, `occurred_at`, `picker`, `device_id`, `picking_context`, `payload`):

```json
{
  "event_name": "quality-alert-created",
  "schema_version": "v1",
  "correlation_id": "uuid",
  "occurred_at": "ISO8601Z",
  "picker": { "user_id": null, "name": "" },
  "device_id": "",
  "picking_context": {
    "picking_id": 0, "move_line_id": null, "product_id": null,
    "location_id": null, "priority": null, "origin": null
  },
  "payload": { }
}
```

| Webhook-Pfad | Modus | Zweck |
|--------------|-------|-------|
| `quality-alert-created` | async (fire) | Neuer Quality-Alert inkl. Foto-Anzahl & Beschreibung. |
| `voice-exception-query` | **sync RPC (7 s)** | Sprachanfrage; erwartet Antwort mit `tts_text` + ggf. `recommendation`. |
| `shortage-reported` | async (fire) | Gemeldete Fehlmenge inkl. Empfehlung (z. B. `trigger_replenishment`). |
| `pick-confirmed` | async (fire) | Bestätigte Pick-Zeile (möglicherweise nicht überall aktiv). |

**Erwartete synchrone Antwort** (für `voice-exception-query`):

```json
{
  "status": "success | fallback | error",
  "tts_text": "Am Platz sind noch 10 Stück ...",
  "source": "n8n-workflow | local-fallback",
  "correlation_id": "uuid",
  "recommendation": { "action": "trigger_replenishment", "location_id": 100 }
}
```

### 7.2 Inbound: n8n → Backend (`/internal/n8n`-Callbacks)

Pflicht-Header je Callback: `Idempotency-Key` (eindeutig pro n8n-Execution) **und** `X-N8N-Callback-Secret`. Body muss `correlation_id` enthalten (**muss == `Idempotency-Key` sein**, sonst 409). Antwort i. d. R. **201** `{ status: "applied", correlation_id, detail }`.

| Callback | Zweck | wichtige Felder |
|----------|-------|------------------|
| `/internal/n8n/quality-assessment` | AI-Bewertung in Odoo speichern + Chatter-Note. | `alert_id`, `ai_disposition`, `ai_confidence`, `ai_summary`, `ai_enhanced_description`, `ai_photo_analysis`, `ai_recommended_action`, `ai_provider`, `ai_model`, `latency_tracking` |
| `/internal/n8n/quality-assessment-ai` | Shadow-Evaluation (Research-Log). | `alert_id`, `category`, `confidence`, `reason`, `model`, `schema_version: "v1"`, `execution_id` |
| `/internal/n8n/replenishment-action` | Nachschub-Transfer in Odoo anlegen. | `picking_id`, `product_id`, `location_id`, `recommended_location_id`, `recommended_location`, `quantity`, `reason`, `requested_by_user_id` → ruft `stock.picking.api_create_replenishment_transfer(...)` |
| `/internal/n8n/quality-assessment-failed` | AI-Status auf "failed" setzen. | `alert_id`, `failure_reason` (Chatter-Note + `mail.activity` für Manual Review) |
| `/internal/n8n/manual-review-activity` | Review-Note + `mail.activity` am Picking. | `picking_id`, `reason`, `execution_url` |

> [!note] Sicherheit der Callbacks
> Das Secret wird mit `secrets.compare_digest()` (timing-sicher) geprüft. Die Bindung `Idempotency-Key == correlation_id` verhindert, dass ein verspäteter/duplizierter n8n-Callback einen falschen Datensatz trifft.

---

## 8. Wichtige Datenflüsse (zusammengefasst)

### Flow 1 — Pick bestätigen (`/pickings/{id}/confirm-line`)
PWA (Headers `X-Picker-User-Id`, `X-Device-Id`, `Idempotency-Key`; Body `move_line_id`, `scanned_barcode`, `quantity`) → Identität auflösen (`res.users`) → Fingerprint (SHA256) → `begin_idempotent_request()` → Heartbeat (Claim verlängern) → `PickingService.confirm_pick_line()` (Odoo `stock.move.line.quantity` + n8n `pick-confirmed` async) → `finalize_idempotent_request()` → Response. Wiederholung mit gleichem Key/Fingerprint = gecachte Response (24 h).

### Flow 2 — Voice Assist (synchroner n8n-RPC)
PWA `POST /api/voice/assist` → Picking-Detail laden (Odoo) → Stock-Context laden (`stock.quant`) → Obsidian-Notizen durchsuchen → `request_reply("voice-exception-query")` (7 s, Circuit Breaker) → bei Antwort: `tts_text` + `recommendation`; bei Timeout/Fehler/`fallback=true`: lokale Antwort aus Stock-Context + Obsidian. Response: `status`, `tts_text`, `source`, `correlation_id`, `latency_ms`, `recommendation`.

### Flow 3 — Quality Alert mit AI
PWA `POST /api/quality-alerts` (Form: Description, Photos) → Identität → Foto-Fingerprints → `begin_idempotent_request()` → Odoo `quality.alert.custom.api_create_alert()` (Alert + Fotos als `ir.attachment`) → n8n `fire_event("quality-alert-created")` (async; bei Fehler lokale Keyword-Heuristik) → n8n analysiert → Callbacks `/quality-assessment` (AI) und `/quality-assessment-ai` (Shadow). Response: `alert_id`, `photo_count`, `ai_evaluation_status`.

### Flow 4 — Shortage / Replenishment
Voice "Artikel fehlt" → Stock-Context zeigt kein Bestand → Empfehlung `trigger_replenishment` (alt. Location) → n8n `shortage-reported` → n8n erzeugt Transfer → Callback `/replenishment-action` → Odoo `stock.picking.api_create_replenishment_transfer(...)` → Response `status: "applied"` + `detail` (z. B. "Nachschubauftrag REPLEN/2026/001 angelegt").

---

## 9. Sicherheits- & Zuverlässigkeitsmerkmale (Kurzliste)

1. **n8n Circuit Breaker** pro Webhook-Pfad: öffnet nach 3 Fehlern für 60 s.
2. **Idempotenz** aller Write-Operationen via SHA256-Fingerprint + Odoo-Speicher (24 h TTL).
3. **Picker-Identität** an User-ID **und** Device-ID gebunden; Claim-TTL 120 s + Heartbeat.
4. **n8n-Secret** über `secrets.compare_digest()` (timing-sicher).
5. **Fallback-Logik:** Voice → lokale Stock-Query + Obsidian; Quality → lokale Keyword-Heuristik.
6. **Timeout-Handling:** Whisper 60 s, Piper 5 s (→ `None`), n8n-Sync 7 s (→ Fallback), Odoo-Read 30 s.
7. **Obsidian-Suche** rein lokal im Vault — keine Remote-Abhängigkeit.

---

## 10. Konkrete Dateipfade (Referenz)

| Komponente | Pfad (relativ zum Projekt) |
|------------|----------------------------|
| Config & DI | `backend/app/config.py`, `backend/app/dependencies.py` |
| Main Entry | `backend/app/main.py` |
| Pickings-Router | `backend/app/routers/pickings.py` |
| Voice-Router | `backend/app/routers/voice.py` |
| Quality-Router | `backend/app/routers/quality.py` |
| Scan-Router | `backend/app/routers/scan.py` |
| Health-Router | `backend/app/routers/health.py` |
| Integration-Router | `backend/app/routers/integration.py` |
| Obsidian-Router | `backend/app/routers/obsidian.py` |
| n8n-Callbacks | `backend/app/routers/n8n_internal.py` |
| Odoo-Client | `backend/app/services/odoo_client.py` |
| n8n-Webhooks | `backend/app/services/n8n_webhook.py` |
| Mobile Workflow | `backend/app/services/mobile_workflow.py` |
| Picking-Service | `backend/app/services/picking_service.py` |
| Intent-Engine | `backend/app/services/intent_engine.py` |
| Route-Optimizer | `backend/app/services/route_optimizer.py` |
| Quality-Heuristik | `backend/app/services/quality_shadow_evaluation.py` |
| Whisper-STT | `backend/app/services/whisper_client.py` |
| Piper-TTS | `backend/app/services/piper_client.py` |
| Obsidian-Kontext | `backend/app/services/obsidian_context.py` |
| Obsidian-Logging | `backend/app/services/integration_log.py` |
| Datenmodelle | `backend/app/models/{n8n,picking,quality,voice}.py` |
| Schemas | `backend/app/schemas/obsidian.py` |

---

> [!info] Verwandte Notizen
> Architektur-Gesamtbild: [[02 - Architektur & Diagramm erklärt]] · Odoo-Details (Modelle/Felder): [[06 - Odoo]] · n8n-Workflows: [[07 - n8n]] · PWA & Voice-UI: [[08 - PWA & Voice-Pfad]] · Begriffe: [[10 - Glossar]] · Container/Hosting: [[03 - Docker & Container]] · Übersicht: [[00 - Start Hier (Übersichtskarte)]]
