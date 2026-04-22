# n8n Contract Freeze V1

Dieses Dokument friert die produktiven n8n-Vertraege fuer Stufe 1 ein. Ziel ist
Regressionsvermeidung im bestehenden `FastAPI + PWA + Odoo + n8n`-Stand.
login:REMOVED
passwort:REMOVED


## Grundregeln

- FastAPI bleibt die einzige Writeback-Grenze zu Odoo.
- Direkte Odoo-Writebacks aus n8n sind in produktiven Flows verboten.
- Neue produktive Backend-Callback-Endpunkte sind ausserhalb der bestehenden Whitelist verboten.
- `correlation_id` ist Trace-ID.
- `Idempotency-Key` ist Replay-/Dedupe-Schluessel.
- Bei write-relevanten asynchronen Callbacks muessen `correlation_id` und `Idempotency-Key` identisch sein.
- Neue oder angefasste Producer senden `schema_version: "v1"`.
- Legacy-Producer ohne `schema_version` werden vorerst akzeptiert und als `legacy_payload=true` geloggt.

## Erlaubte Backend-Writebacks aus n8n

- `POST /api/internal/n8n/quality-assessment`
- `POST /api/internal/n8n/replenishment-action`
- `POST /api/internal/n8n/quality-assessment-failed`
- `POST /api/internal/n8n/manual-review-activity`
- `POST /api/integration/log`

Legacy-Alias:

- `POST /api/obsidian/log` bleibt vorerst kompatibel, ist aber nicht mehr der primaere Produktpfad

## Common Callback Metadata

### Pflichtheader fuer write-relevante Callbacks

- `X-N8N-Callback-Secret`
- `Idempotency-Key`

### Additive Metadaten im Body

- `schema_version: "v1"` fuer neue oder angefasste Producer
- `execution_id: str | null`
- `latency_tracking`

### `latency_tracking` Minimalvertrag

- `started_at: str | null`
- `total_duration_ms: int | null`
- `stages: dict[str, int] | null`
- `extra_stages: dict[str, int] | null`

Zulaessige Standard-Stage-Keys:

- `ingest_ms`
- `heuristic_ms`
- `callback_ms`

## Produktive Flows

### `quality-alert-created`

- Richtung: FastAPI feuert Event an n8n, n8n antwortet sofort synchron und schreibt Bewertung asynchron zurueck.
- Sync-Response: `status`, `tts_text`, `source`, `correlation_id`
- Writeback-Endpunkt: `POST /api/internal/n8n/quality-assessment`
- Der produktive Live-Pfad enthaelt keinen Shadow-AI-Subworkflow.
- Pflichtfelder:
  - `correlation_id`
  - `alert_id`
  - `schema_version`
  - `execution_id`
  - `latency_tracking`
  - `ai_disposition`
  - `ai_confidence`
  - `ai_summary`
- Optionale Felder:
  - `ai_enhanced_description`
  - `ai_photo_analysis`
  - `ai_recommended_action`
  - `ai_provider`
  - `ai_model`
- Idempotenzregel: `Idempotency-Key` verpflichtend und identisch zu `correlation_id`

### `shortage-reported`

- Richtung: FastAPI feuert Event an n8n, n8n antwortet sofort synchron und schreibt Nachschubaktion asynchron zurueck.
- Sync-Response: `status`, `tts_text`, `source`, `correlation_id`
- Writeback-Endpunkt: `POST /api/internal/n8n/replenishment-action`
- Pflichtfelder:
  - `correlation_id`
  - `picking_id`
  - `product_id`
  - `location_id`
  - `recommended_location_id`
  - `reason`
  - `schema_version`
  - `execution_id`
  - `latency_tracking`
- Optionale Felder:
  - `recommended_location`
  - `quantity`
  - `ticket_text`
  - `requested_by_user_id`
  - `requested_by_name`
- Idempotenzregel: `Idempotency-Key` verpflichtend und identisch zu `correlation_id`

### `voice-exception-query`

- Richtung: FastAPI sendet Request-Reply an n8n.
- Sync-Response bleibt unveraendert:
  - `status`
  - `tts_text`
  - `source`
  - `correlation_id`
- In Stufe 1 keine fachliche Antwortlogik-Aenderung.

### `pick-confirmed`

- Stufe 1 behandelt diesen Flow nur als Vertrags-/Syntaxobjekt.
- Kein funktionaler Umbau in dieser Phase.

### `error-trigger`

- Richtung: n8n-interner Fehlerpfad fuer produktive Workflows.
- Erlaubte Writebacks:
  - `POST /api/internal/n8n/quality-assessment-failed`
  - `POST /api/internal/n8n/manual-review-activity`
- Beide Writebacks sind write-relevant und brauchen:
  - `X-N8N-Callback-Secret`
  - `Idempotency-Key`
  - `schema_version`
  - `execution_id`
  - `latency_tracking`
- `quality-assessment-failed` Pflichtfelder:
  - `correlation_id`
  - `alert_id`
  - `failure_reason`
- `manual-review-activity` Pflichtfelder:
  - `correlation_id`
  - `picking_id`
  - `reason`

## Rollout-Regel

Vor jedem Import oder jeder Aktivierung:

1. `python infrastructure/scripts/verify-workflows.py`
2. relevante Backend-Tests gruen
3. `node --test n8n/tests/assess-alert-v2.test.mjs`
4. `bash infrastructure/scripts/import-workflows.sh backup`
5. `bash infrastructure/scripts/import-workflows.sh import <backup-dir>`
6. gezielte Aktivierung ueber `bash infrastructure/scripts/import-workflows.sh activate <backup-dir> <workflow-file>`
7. Smoke-Test
8. erst dann den naechsten Workflow aktivieren
