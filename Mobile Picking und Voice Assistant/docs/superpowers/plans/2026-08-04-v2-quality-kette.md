# v2-Qualitätskette Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein gemeldeter Qualitätsmangel läuft über die signierte v2-Strecke zu einem lokalen Sprachmodell und das Ergebnis steht am Odoo-Datensatz.

**Architecture:** Odoo reiht das Ereignis in derselben Transaktion ein, in der der Alert entsteht (Transactional Outbox). Der Backend-Dispatcher stellt es signiert an genau einen verifierkonformen n8n-Workflow zu; der ruft eine neue v2-signierte Bewertungsroute im Backend auf, die mit Ollama spricht, und meldet das Ergebnis per Callback zurück, den Odoo in derselben Transaktion auf die `ai_*`-Felder projiziert.

**Tech Stack:** Odoo 19 (Python), FastAPI, pytest, n8n 2.13.3 mit `n8n-nodes-pwr`, Ollama `qwen2.5:7b` (CPU), PostgreSQL 16.

**Spec:** `docs/superpowers/specs/2026-08-04-n8n-v2-quality-kette-design.md`

## Global Constraints

- Ereignisname: `quality.assessment.requested.v1`. Callback-Name: `quality.assessment.status.v1`. Andere Namen weist `backend/app/models/events.py:8` ab.
- Webhook-Pfad: `quality-assessment-v2`. Kebab-case ist Pflicht, Unterstriche lehnt `backend/app/services/workflow_targets.py:38` ab.
- `payload_fingerprint` ist **immer** `sha256(envelope_text.encode("utf-8")).hexdigest()` über exakt die Bytes, die in `picking.assistant.outbox.envelope_text` stehen.
- Envelope-Serialisierung **überall** identisch: `json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
- Annahmeantwort des Workflows: exakt `{"accepted": true, "event_id": …}`, kein weiteres Feld (`backend/app/services/signed_webhook_transport.py:110`).
- Zustellfrist 10 s, Verarbeitungs-Lease 300 s.
- Kein Ersatzurteil: fällt das LLM aus, ist der Status `review_required` und `ai_disposition` bleibt leer.
- Backend-Tests laufen mit `PYTHONPATH=.deps python3 -m pytest` aus `backend/`.
- Odoo-Tests laufen im Container gegen eine Testdatenbank, niemals gegen `masterfischer_o19`.
- Docker über den vollen Pfad: `DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"`.
- Compose immer mit beiden Dateien: `-f docker-compose.yml -f docker-compose.dev.yml`.

## File Structure

| Datei | Verantwortung |
|---|---|
| `odoo/addons/quality_alert_custom/models/quality_alert.py` | Revision, Projektionsmethode, Auslöser in `api_create_alert` |
| `odoo/addons/quality_alert_custom/models/quality_event.py` (neu) | Envelope-Bau und Fingerprint für das Qualitätsereignis |
| `odoo/addons/quality_alert_custom/tests/` (neu) | Tests der beiden obigen Dateien |
| `odoo/addons/picking_assistant_integration/models/api_security.py` | `_instance_name()` als gemeinsamer Helfer |
| `odoo/addons/picking_assistant_integration/models/receipts.py` | Projektionsaufruf im Callback |
| `backend/app/models/n8n.py` | Anfrage-/Antwortmodell der neuen Bewertungsroute |
| `backend/app/routers/n8n_v2.py` | neue Route `/assessments/quality` |
| `backend/app/main.py` | Startprüfung der Instanznamen |
| `backend/app/routers/quality.py` | Abschalten der Ersatzbewertung |
| `n8n/workflows/quality-assessment-v2.json` (neu) | der Workflow |
| `n8n/workflow-registry.json` | Registry-Eintrag |
| `n8n/tests/fingerprint-parity.test.mjs` (neu) | Kreuztest der Kanonisierung |

---

## Stufe 1 — Erzeugende Seite

### Task 1: Revisionszähler am Alert

**Files:**
- Modify: `odoo/addons/quality_alert_custom/models/quality_alert.py`
- Create: `odoo/addons/quality_alert_custom/tests/__init__.py`
- Test: `odoo/addons/quality_alert_custom/tests/test_integration_revision.py`

**Interfaces:**
- Produces: Feld `quality.alert.custom.integration_revision` (Integer, Default 1, monoton steigend)

- [ ] **Step 1: Testdatei anlegen**

`odoo/addons/quality_alert_custom/tests/__init__.py`:

```python
from . import test_integration_revision
```

`odoo/addons/quality_alert_custom/tests/test_integration_revision.py`:

```python
from odoo.tests.common import TransactionCase


class TestIntegrationRevision(TransactionCase):
    def _alert(self):
        return self.env["quality.alert.custom"].create(
            {"description": "Karton eingedrueckt", "priority": "1"}
        )

    def test_new_alert_starts_at_revision_one(self):
        self.assertEqual(self._alert().integration_revision, 1)

    def test_description_change_raises_revision(self):
        alert = self._alert()
        alert.write({"description": "Karton zerdrueckt, Ware nass"})
        self.assertEqual(alert.integration_revision, 2)

    def test_unrelated_change_keeps_revision(self):
        alert = self._alert()
        alert.write({"ai_summary": "egal"})
        self.assertEqual(alert.integration_revision, 1)

    def test_explicit_revision_is_not_double_counted(self):
        alert = self._alert()
        alert.write({"description": "neu", "integration_revision": 7})
        self.assertEqual(alert.integration_revision, 7)
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

```bash
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" exec mobilepickingundvoiceassistant-odoo-1 sh -c \
  'odoo -c /etc/odoo/odoo.conf -d pwr_test --db_host=db --db_user=$USER --db_password=$PASSWORD \
   --http-port=8199 --gevent-port=8299 -i quality_alert_custom --test-enable --stop-after-init'
```

Erwartet: FAIL, `Invalid field 'integration_revision'`.

- [ ] **Step 3: Feld und Schreiblogik ergänzen**

In `quality_alert.py`, Klasse `QualityAlert`, direkt nach `ai_failure_reason`:

```python
    # Monoton steigende Revision des Datensatzes. `_enqueue_job_event` verlangt
    # `aggregate_revision >= 1`; ein spaeteres Ereignis zum selben Alert traegt
    # damit eine hoehere Revision und kann ein aelteres abloesen.
    integration_revision = fields.Integer(
        string="Integrationsrevision", default=1, required=True, copy=False,
    )
```

Und als Methode derselben Klasse:

```python
    # Nur Felder, die die Bewertung beeinflussen. Eine Revision, die bei jedem
    # ai_*-Rueckschreiben hochzaehlt, wuerde die eigene Antwort als Aenderung
    # des Sachverhalts missverstehen.
    _REVISION_TRIGGER_FIELDS = ("description", "priority", "photo")

    def write(self, vals):
        bumps = any(field in vals for field in self._REVISION_TRIGGER_FIELDS)
        if not bumps or "integration_revision" in vals:
            return super().write(vals)
        for record in self:
            super(QualityAlert, record).write(
                dict(vals, integration_revision=record.integration_revision + 1)
            )
        return True
```

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

Gleicher Befehl wie Step 2. Erwartet: vier Tests grün.

- [ ] **Step 5: Committen**

```bash
git add odoo/addons/quality_alert_custom/models/quality_alert.py odoo/addons/quality_alert_custom/tests/
git commit -m "feat(odoo): give the quality alert a revision the outbox can order by"
```

---

### Task 2: Instanzname als Konfigurationsparameter

**Files:**
- Modify: `odoo/addons/picking_assistant_integration/models/api_security.py`
- Test: `odoo/addons/picking_assistant_integration/tests/test_instance_name.py`
- Modify: `odoo/addons/picking_assistant_integration/tests/__init__.py`

**Interfaces:**
- Produces: `self.env["picking.assistant.api.mixin"]._instance_name()` → `str`, wirft `ValidationError` wenn unkonfiguriert

- [ ] **Step 1: Failing test schreiben**

`odoo/addons/picking_assistant_integration/tests/test_instance_name.py`:

```python
from odoo.exceptions import ValidationError

from .common import IntegrationCase


class TestInstanceName(IntegrationCase):
    def _mixin(self):
        return self.env["picking.assistant.api.mixin"]

    def _set(self, value):
        self.env["ir.config_parameter"].sudo().set_param(
            "picking_assistant.instance_name", value
        )

    def test_configured_name_is_returned(self):
        self._set("lager-2")
        self.assertEqual(self._mixin()._instance_name(), "lager-2")

    def test_surrounding_whitespace_is_stripped(self):
        self._set("  local  ")
        self.assertEqual(self._mixin()._instance_name(), "local")

    def test_missing_parameter_raises(self):
        self._set("")
        with self.assertRaisesRegex(ValidationError, "instance_name"):
            self._mixin()._instance_name()

    def test_invalid_characters_raise(self):
        self._set("Lager 2")
        with self.assertRaisesRegex(ValidationError, "instance_name"):
            self._mixin()._instance_name()
```

In `odoo/addons/picking_assistant_integration/tests/__init__.py` ergänzen:

```python
from . import test_instance_name
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

```bash
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" exec mobilepickingundvoiceassistant-odoo-1 sh -c \
  'odoo -c /etc/odoo/odoo.conf -d pwr_test --db_host=db --db_user=$USER --db_password=$PASSWORD \
   --http-port=8199 --gevent-port=8299 -u picking_assistant_integration --test-enable --stop-after-init'
```

Erwartet: FAIL, `_instance_name` existiert nicht.

- [ ] **Step 3: Helfer implementieren**

Oben in `api_security.py`:

```python
import re
```

Und in der Klasse `picking.assistant.api.mixin`:

```python
    # Muster identisch zu EventSource.odoo_instance im Backend
    # (backend/app/models/events.py). Weicht es ab, baut Odoo Envelopes, die
    # die Gegenseite nicht annimmt.
    _INSTANCE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

    @api.model
    def _instance_name(self):
        """Der Name, unter dem das Backend DIESE Instanz kennt.

        Er steuert, in welche Datenbank ein Callback zurueckschreibt, und ist
        deshalb Konfiguration, keine Ableitung: Odoo kann seinen eigenen
        Profilnamen nicht erraten.
        """
        raw = self.env["ir.config_parameter"].sudo().get_param(
            "picking_assistant.instance_name"
        )
        value = (raw or "").strip()
        if not self._INSTANCE_NAME_RE.match(value):
            raise ValidationError(
                "picking_assistant.instance_name ist nicht gesetzt oder ungueltig."
            )
        return value
```

Sicherstellen, dass `api`, `ValidationError` in der Datei importiert sind.

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

Gleicher Befehl. Erwartet: vier Tests grün.

- [ ] **Step 5: Committen**

```bash
git add odoo/addons/picking_assistant_integration/models/api_security.py odoo/addons/picking_assistant_integration/tests/
git commit -m "feat(odoo): let an instance state the name the backend knows it by"
```

---

### Task 3: Envelope und Fingerprint

**Files:**
- Create: `odoo/addons/quality_alert_custom/models/quality_event.py`
- Modify: `odoo/addons/quality_alert_custom/models/__init__.py`
- Modify: `odoo/addons/quality_alert_custom/__manifest__.py`
- Test: `odoo/addons/quality_alert_custom/tests/test_quality_event.py`

**Interfaces:**
- Consumes: `_instance_name()` aus Task 2, `integration_revision` aus Task 1
- Produces: `self.env["quality.alert.event.builder"].build(alert)` → `dict` mit den Schlüsseln `event_id`, `job_id`, `correlation_id`, `envelope_text`, `payload_fingerprint`

- [ ] **Step 1: Failing test schreiben**

`odoo/addons/quality_alert_custom/tests/test_quality_event.py`:

```python
import hashlib
import json

from odoo.tests.common import TransactionCase


class TestQualityEventBuilder(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "picking_assistant.instance_name", "local"
        )
        self.alert = self.env["quality.alert.custom"].create(
            {"description": "Karton zerdrueckt", "priority": "2"}
        )

    def _built(self):
        return self.env["quality.alert.event.builder"].build(self.alert)

    def test_fingerprint_is_sha256_of_the_stored_bytes(self):
        built = self._built()
        expected = hashlib.sha256(
            built["envelope_text"].encode("utf-8")
        ).hexdigest()
        self.assertEqual(built["payload_fingerprint"], expected)

    def test_envelope_is_canonical_json(self):
        text = self._built()["envelope_text"]
        parsed = json.loads(text)
        self.assertEqual(
            text,
            json.dumps(
                parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ),
        )

    def test_envelope_carries_the_configured_instance(self):
        envelope = json.loads(self._built()["envelope_text"])
        self.assertEqual(envelope["source"]["odoo_instance"], "local")
        self.assertEqual(envelope["source"]["service"], "picking-assistant-api")
        self.assertEqual(envelope["event_name"], "quality.assessment.requested.v1")
        self.assertEqual(envelope["schema_version"], "v2")

    def test_aggregate_points_at_the_alert(self):
        envelope = json.loads(self._built()["envelope_text"])
        self.assertEqual(envelope["aggregate"]["model"], "quality.alert.custom")
        self.assertEqual(envelope["aggregate"]["id"], self.alert.id)
        self.assertEqual(envelope["aggregate"]["revision"], 1)

    def test_payload_carries_five_generations_of_callback_ids(self):
        payload = json.loads(self._built()["envelope_text"])["payload"]
        ids = payload["callback_ids_by_generation"]
        self.assertEqual(sorted(ids), ["1", "2", "3", "4", "5"])
        terminals = [entry["terminal"] for entry in ids.values()]
        self.assertEqual(len(set(terminals)), 5)

    def test_payload_carries_the_job_id_the_acceptance_needs(self):
        built = self._built()
        payload = json.loads(built["envelope_text"])["payload"]
        self.assertEqual(payload["job_id"], built["job_id"])

    def test_two_builds_use_distinct_event_ids(self):
        self.assertNotEqual(self._built()["event_id"], self._built()["event_id"])
```

Import in `odoo/addons/quality_alert_custom/tests/__init__.py` ergänzen:

```python
from . import test_quality_event
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

```bash
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" exec mobilepickingundvoiceassistant-odoo-1 sh -c \
  'odoo -c /etc/odoo/odoo.conf -d pwr_test --db_host=db --db_user=$USER --db_password=$PASSWORD \
   --http-port=8199 --gevent-port=8299 -u quality_alert_custom --test-enable --stop-after-init'
```

Erwartet: FAIL, Modell `quality.alert.event.builder` existiert nicht.

- [ ] **Step 3: Builder implementieren**

`odoo/addons/quality_alert_custom/models/quality_event.py`:

```python
"""Bau des v2-Ereignisses fuer einen Qualitaetsmangel.

Der Fingerprint ist die empfindlichste Stelle der ganzen Kette:
`picking.assistant.event.receipt.api_accept_event` vergleicht ihn BITGENAU mit
dem Wert, den n8n aus dem SHA-256 des empfangenen Rumpfes meldet. Der
Dispatcher uebertraegt `envelope_text` unveraendert als UTF-8, also muss der
Fingerprint ueber genau diese Bytes gebildet werden -- nicht ueber das
`payload`-Teilobjekt und nicht ueber ein zweites `json.dumps` mit anderen
Trennzeichen.
"""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from odoo import api, models

EVENT_NAME = "quality.assessment.requested.v1"
# Generationen steigen nur, wenn der Watchdog eine abgelaufene Lease
# einsammelt. Fuenf davon sind ein Betriebsfall, kein Zustellproblem; der
# Workflow scheitert danach bewusst geschlossen.
CALLBACK_ID_GENERATIONS = 5


class QualityAlertEventBuilder(models.AbstractModel):
    _name = "quality.alert.event.builder"
    _description = "Builder fuer quality.assessment.requested.v1"

    @api.model
    def _canonical(self, envelope):
        return json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    @api.model
    def build(self, alert):
        instance = self.env["picking.assistant.api.mixin"]._instance_name()
        event_id = str(uuid4())
        job_id = str(uuid4())
        correlation_id = str(uuid4())
        photo_count = self.env["ir.attachment"].sudo().search_count(
            [("res_model", "=", alert._name), ("res_id", "=", alert.id)]
        )
        envelope = {
            "schema_version": "v2",
            "event_name": EVENT_NAME,
            "event_id": event_id,
            "correlation_id": correlation_id,
            "causation_id": None,
            "occurred_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "source": {
                "service": "picking-assistant-api",
                "odoo_instance": instance,
            },
            "actor": {
                "type": "picker",
                "user_id": alert.user_id.id or None,
                "name": alert.user_id.name or None,
                "device_id": None,
            },
            "aggregate": {
                "model": alert._name,
                "id": alert.id,
                "revision": alert.integration_revision,
            },
            "payload": {
                "alert_id": alert.id,
                "name": alert.name or "",
                "description": alert.description or "",
                "priority": alert.priority or "0",
                "photo_count": photo_count,
                "product_id": alert.product_id.id or None,
                "location_id": alert.location_id.id or None,
                "picking_id": alert.picking_id.id or None,
                "job_id": job_id,
                # n8n kann in Set-Ausdruecken keine UUID erzeugen und
                # Code-Knoten sind nach der Annahme verboten. Also liefert die
                # erzeugende Seite die Callback-IDs mit.
                "callback_ids_by_generation": {
                    str(generation): {"terminal": str(uuid4())}
                    for generation in range(1, CALLBACK_ID_GENERATIONS + 1)
                },
            },
        }
        envelope_text = self._canonical(envelope)
        return {
            "event_id": event_id,
            "job_id": job_id,
            "correlation_id": correlation_id,
            "envelope_text": envelope_text,
            "payload_fingerprint": hashlib.sha256(
                envelope_text.encode("utf-8")
            ).hexdigest(),
        }
```

In `odoo/addons/quality_alert_custom/models/__init__.py` ergänzen:

```python
from . import quality_event
```

In `odoo/addons/quality_alert_custom/__manifest__.py` die Abhängigkeit ergänzen (der Builder benutzt den Mixin des Integrationsmoduls):

```python
    "depends": ["stock", "mail", "picking_assistant_integration"],
```

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

Gleicher Befehl wie Step 2. Erwartet: sieben Tests grün.

- [ ] **Step 5: Committen**

```bash
git add odoo/addons/quality_alert_custom/
git commit -m "feat(odoo): build the v2 quality event and fingerprint its exact bytes"
```

---

### Task 4: Auslöser in `api_create_alert`

**Files:**
- Modify: `odoo/addons/quality_alert_custom/models/quality_alert.py:163-190`
- Test: `odoo/addons/quality_alert_custom/tests/test_alert_enqueues_event.py`

**Interfaces:**
- Consumes: `quality.alert.event.builder.build(alert)` aus Task 3
- Produces: `api_create_alert` legt zusätzlich Job und Outbox-Zeile an; Rückgabe bleibt `{"alert_id": …, "name": …}`

- [ ] **Step 1: Failing test schreiben**

`odoo/addons/quality_alert_custom/tests/test_alert_enqueues_event.py`:

```python
import hashlib
import json

from odoo.tests.common import TransactionCase


class TestAlertEnqueuesEvent(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "picking_assistant.instance_name", "local"
        )

    def _create(self, description="Karton zerdrueckt"):
        return self.env["quality.alert.custom"].api_create_alert(
            {"description": description, "priority": "1"}
        )

    def _outbox(self):
        return self.env["picking.assistant.outbox"].sudo().search([])

    def test_one_alert_creates_exactly_one_outbox_row(self):
        self._create()
        rows = self._outbox()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.event_name, "quality.assessment.requested.v1")
        self.assertEqual(rows.state, "pending")

    def test_outbox_fingerprint_matches_the_stored_envelope(self):
        self._create()
        row = self._outbox()
        self.assertEqual(
            row.payload_fingerprint,
            hashlib.sha256(row.envelope_text.encode("utf-8")).hexdigest(),
        )

    def test_envelope_points_at_the_created_alert(self):
        result = self._create()
        envelope = json.loads(self._outbox().envelope_text)
        self.assertEqual(envelope["aggregate"]["id"], result["alert_id"])
        self.assertEqual(envelope["payload"]["alert_id"], result["alert_id"])

    def test_alert_starts_pending(self):
        result = self._create()
        alert = self.env["quality.alert.custom"].browse(result["alert_id"])
        self.assertEqual(alert.ai_evaluation_status, "pending")

    def test_rollback_removes_alert_and_event_together(self):
        with self.assertRaisesRegex(RuntimeError, "force rollback"):
            with self.env.cr.savepoint():
                self._create("wird zurueckgerollt")
                raise RuntimeError("force rollback")
        self.env.invalidate_all()
        self.assertFalse(
            self.env["quality.alert.custom"].search(
                [("description", "=", "wird zurueckgerollt")]
            )
        )
        self.assertFalse(self._outbox())
```

Import in `tests/__init__.py` ergänzen:

```python
from . import test_alert_enqueues_event
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Gleicher Odoo-Testbefehl wie in Task 3, Step 2. Erwartet: FAIL, keine Outbox-Zeile.

- [ ] **Step 3: Auslöser einhängen**

In `quality_alert.py`, in `api_create_alert`, direkt vor `return`:

```python
        # Transactional Outbox: der Beleg entsteht in DERSELBEN Transaktion wie
        # der Datensatz. Entweder beides oder nichts -- ein Alert ohne Ereignis
        # waere eine Bewertung, die nie kommt, ein Ereignis ohne Alert eine
        # Bewertung fuer nichts.
        alert.sudo().write({"ai_evaluation_status": "pending"})
        built = self.env["quality.alert.event.builder"].build(alert)
        self.env["picking.assistant.integration.job"]._enqueue_job_event(
            job_type="quality_assessment",
            aggregate_model=alert._name,
            aggregate_res_id=alert.id,
            aggregate_revision=alert.integration_revision,
            event_id=built["event_id"],
            event_name="quality.assessment.requested.v1",
            envelope_text=built["envelope_text"],
            payload_fingerprint=built["payload_fingerprint"],
            correlation_id=built["correlation_id"],
            job_id=built["job_id"],
        )

        return {"alert_id": alert.id, "name": alert.name}
```

Die bestehende `return`-Zeile darunter entfernen, damit sie nicht doppelt steht.

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

Gleicher Befehl. Erwartet: fünf Tests grün, und die Tests aus Task 1 und 3 weiterhin grün.

- [ ] **Step 5: Committen**

```bash
git add odoo/addons/quality_alert_custom/
git commit -m "feat(odoo): enqueue the assessment event in the alert's own transaction"
```

---

### Task 5: Kreuztest der Kanonisierung

**Files:**
- Create: `n8n/tests/fingerprint-parity.test.mjs`
- Create: `n8n/tests/fixtures/envelope-canonical.json`

**Interfaces:**
- Consumes: die Kanonisierungsregel aus Task 3
- Produces: Nachweis, dass Node denselben Hash bildet wie Python

- [ ] **Step 1: Fixture aus Odoo erzeugen**

```bash
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" exec mobilepickingundvoiceassistant-db-1 psql -U odoo -d pwr_test -tAc \
  "select envelope_text || E'\n' || payload_fingerprint from picking_assistant_outbox limit 1;"
```

Ergebnis als zwei Felder in `n8n/tests/fixtures/envelope-canonical.json` ablegen:

```json
{
  "envelope_text": "<die erste Zeile der Ausgabe, unveraendert>",
  "payload_fingerprint": "<die zweite Zeile der Ausgabe>"
}
```

- [ ] **Step 2: Failing test schreiben**

`n8n/tests/fingerprint-parity.test.mjs`:

```javascript
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

import {sha256Hex} from '../custom-nodes/n8n-nodes-pwr/dist/security/pwrSignature.js';

const fixture = JSON.parse(
  readFileSync(new URL('./fixtures/envelope-canonical.json', import.meta.url), 'utf8'),
);

test('the gate hashes exactly what Odoo fingerprinted', () => {
  const body = Buffer.from(fixture.envelope_text, 'utf8');
  assert.equal(sha256Hex(body), fixture.payload_fingerprint);
});

test('re-serialising the envelope in JS would break the fingerprint', () => {
  // Beleg, warum der Workflow den Rumpf NIE neu serialisieren darf: JSON.stringify
  // stellt weder Schluesselreihenfolge noch Trennzeichen so her wie Python.
  const reserialised = Buffer.from(
    JSON.stringify(JSON.parse(fixture.envelope_text)),
    'utf8',
  );
  assert.notEqual(
    createHash('sha256').update(reserialised).digest('hex'),
    fixture.payload_fingerprint,
  );
});
```

- [ ] **Step 3: Test laufen lassen**

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
node --test n8n/tests/fingerprint-parity.test.mjs
```

Erwartet: beide Tests grün. Schlägt der erste fehl, stimmt die Kanonisierung in Task 3 nicht — dort korrigieren, nicht hier.

- [ ] **Step 4: Committen**

```bash
git add n8n/tests/fingerprint-parity.test.mjs n8n/tests/fixtures/envelope-canonical.json
git commit -m "test(n8n): prove Node hashes the same bytes Odoo fingerprinted"
```

---

### Task 6: Startprüfung der Instanznamen im Backend

**Files:**
- Modify: `backend/app/main.py:52-80`
- Test: `backend/tests/test_instance_name_startup.py`

**Interfaces:**
- Consumes: `_instance_name()` aus Task 2
- Produces: `verify_instance_names(runtime)` — Coroutine, wirft `RuntimeError` bei Abweichung

- [ ] **Step 1: Failing test schreiben**

`backend/tests/test_instance_name_startup.py`:

```python
import pytest

from app.config import OdooProfile
from app.main import verify_instance_names


class FakeOdoo:
    def __init__(self, reported):
        self.reported = reported

    async def execute_kw(self, model, method, args, kwargs=None):
        if self.reported is None:
            raise RuntimeError("parameter missing")
        return self.reported


class FakeRuntime:
    def __init__(self, mapping):
        self._mapping = mapping
        self.settings = None

    def instances(self):
        return {
            name: OdooProfile(name, name, "http://odoo:8069", name, "admin", "k", "")
            for name in self._mapping
        }

    def odoo_client(self, name):
        return FakeOdoo(self._mapping[name])


@pytest.mark.asyncio
async def test_matching_names_pass():
    await verify_instance_names(FakeRuntime({"local": "local", "lager-2": "lager-2"}))


@pytest.mark.asyncio
async def test_swapped_name_is_a_startup_error():
    runtime = FakeRuntime({"local": "lager-2"})
    with pytest.raises(RuntimeError, match="local"):
        await verify_instance_names(runtime)


@pytest.mark.asyncio
async def test_unreachable_parameter_is_a_startup_error():
    runtime = FakeRuntime({"local": None})
    with pytest.raises(RuntimeError, match="local"):
        await verify_instance_names(runtime)
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

```bash
cd backend && PYTHONPATH=.deps python3 -m pytest tests/test_instance_name_startup.py -v
```

Erwartet: FAIL, `verify_instance_names` existiert nicht.

- [ ] **Step 3: Prüfung implementieren**

In `backend/app/main.py`, vor der Lifespan-Funktion:

```python
async def verify_instance_names(runtime) -> None:
    """Jede Odoo-Instanz muss sich selbst so nennen, wie das Backend sie kennt.

    Der Name im Envelope steuert, in welche Datenbank ein Callback
    zurueckschreibt. Waere er falsch, landete die Bewertung von Lager 2
    stillschweigend in Lager 1 -- ein Startfehler ist die einzige ehrliche
    Antwort darauf.
    """
    for name in runtime.instances():
        try:
            reported = await runtime.odoo_client(name).execute_kw(
                "picking.assistant.api.mixin", "_instance_name", []
            )
        except Exception as exc:
            raise RuntimeError(
                f"Odoo-Instanz {name!r} meldet keinen Instanznamen: {exc}"
            ) from exc
        if reported != name:
            raise RuntimeError(
                f"Odoo-Instanz {name!r} nennt sich selbst {reported!r}; "
                "picking_assistant.instance_name stimmt nicht mit dem Profil ueberein."
            )
```

Im Lifespan, direkt bevor der Dispatcher-Task startet:

```python
            await verify_instance_names(app.state.runtime)
```

Falls `runtime` keine Methode `instances()` hat, die vorhandene Zugriffsart aus `get_instance_registry(...)` verwenden und den Test entsprechend angleichen.

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

```bash
cd backend && PYTHONPATH=.deps python3 -m pytest tests/test_instance_name_startup.py -v && PYTHONPATH=.deps python3 -m pytest -q
```

Erwartet: drei neue Tests grün, Gesamtsuite weiterhin grün.

- [ ] **Step 5: Committen**

```bash
git add backend/app/main.py backend/tests/test_instance_name_startup.py
git commit -m "feat(backend): refuse to start when an instance misnames itself"
```

---

## Stufe 2 — Empfangende Seite

### Task 7: Projektion des Ergebnisses auf den Alert

**Files:**
- Modify: `odoo/addons/quality_alert_custom/models/quality_alert.py`
- Test: `odoo/addons/quality_alert_custom/tests/test_assessment_projection.py`

**Interfaces:**
- Produces: `alert.api_apply_assessment(status, result, error)` — schreibt die `ai_*`-Felder; `status` ∈ `succeeded | review_required | failed`

- [ ] **Step 1: Failing test schreiben**

`odoo/addons/quality_alert_custom/tests/test_assessment_projection.py`:

```python
from odoo.tests.common import TransactionCase

RESULT = {
    "disposition": "scrap",
    "confidence": 0.95,
    "summary": "Kartons zerdrueckt, Ware unbrauchbar.",
    "recommended_action": "Artikel sperren.",
    "provider": "ollama-local",
    "model": "qwen2.5:7b",
}


class TestAssessmentProjection(TransactionCase):
    def _alert(self):
        return self.env["quality.alert.custom"].create(
            {"description": "Karton zerdrueckt", "ai_evaluation_status": "pending"}
        )

    def test_success_writes_the_verdict(self):
        alert = self._alert()
        alert.api_apply_assessment("succeeded", RESULT, None)
        self.assertEqual(alert.ai_evaluation_status, "completed")
        self.assertEqual(alert.ai_disposition, "scrap")
        self.assertEqual(alert.ai_confidence, 0.95)
        self.assertEqual(alert.ai_provider, "ollama-local")
        self.assertEqual(alert.ai_model, "qwen2.5:7b")
        self.assertTrue(alert.ai_last_analyzed_at)

    def test_review_required_writes_no_verdict(self):
        alert = self._alert()
        alert.api_apply_assessment(
            "review_required", {}, {"code": "llm_unavailable", "message": "Timeout"}
        )
        self.assertEqual(alert.ai_evaluation_status, "review_required")
        self.assertFalse(alert.ai_disposition)
        self.assertFalse(alert.ai_confidence)
        self.assertEqual(alert.ai_failure_reason, "Timeout")

    def test_failed_writes_no_verdict(self):
        alert = self._alert()
        alert.api_apply_assessment("failed", {}, {"message": "Odoo weg"})
        self.assertEqual(alert.ai_evaluation_status, "failed")
        self.assertFalse(alert.ai_disposition)

    def test_projection_does_not_raise_the_revision(self):
        alert = self._alert()
        before = alert.integration_revision
        alert.api_apply_assessment("succeeded", RESULT, None)
        self.assertEqual(alert.integration_revision, before)
```

Import in `tests/__init__.py` ergänzen.

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Odoo-Testbefehl wie in Task 3. Erwartet: FAIL, `api_apply_assessment` fehlt und `review_required` ist kein gültiger Selection-Wert.

- [ ] **Step 3: Statuswert und Projektion implementieren**

In `quality_alert.py` die Selection erweitern:

```python
    ai_evaluation_status = fields.Selection(
        [
            ("pending", "Ausstehend"),
            ("completed", "Abgeschlossen"),
            ("review_required", "Manuelle Pruefung noetig"),
            ("failed", "Fehlgeschlagen"),
        ],
        string="Analyse-Status",
        tracking=True,
    )
```

Und die Projektionsmethode ergänzen:

```python
    # Abbildung Callback-Status -> Analyse-Status. Nur `succeeded` darf ein
    # Urteil schreiben; alles andere laesst ai_disposition leer, damit im
    # System nie eine Bewertung steht, die kein Modell getroffen hat.
    _ASSESSMENT_STATUS_MAP = {
        "succeeded": "completed",
        "review_required": "review_required",
        "failed": "failed",
    }

    def api_apply_assessment(self, status, result, error):
        self.ensure_one()
        mapped = self._ASSESSMENT_STATUS_MAP.get(status)
        if mapped is None:
            raise ValidationError(f"Unbekannter Bewertungsstatus: {status!r}")
        result = result or {}
        error = error or {}
        values = {
            "ai_evaluation_status": mapped,
            "ai_last_analyzed_at": fields.Datetime.now(),
            "ai_failure_reason": error.get("message") or False,
        }
        if mapped == "completed":
            values.update(
                {
                    "ai_disposition": result.get("disposition") or False,
                    "ai_confidence": result.get("confidence") or 0.0,
                    "ai_summary": result.get("summary") or False,
                    "ai_recommended_action": result.get("recommended_action") or False,
                    "ai_provider": result.get("provider") or False,
                    "ai_model": result.get("model") or False,
                }
            )
        self.sudo().write(values)
        return True
```

`ValidationError` importieren, falls in der Datei noch nicht vorhanden.

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

Gleicher Befehl. Erwartet: vier Tests grün.

- [ ] **Step 5: Committen**

```bash
git add odoo/addons/quality_alert_custom/
git commit -m "feat(odoo): project the assessment onto the alert, verdict only on success"
```

---

### Task 8: Projektion im Callback aufrufen

**Files:**
- Modify: `odoo/addons/picking_assistant_integration/models/receipts.py` (in `api_apply_callback`, im terminalen Zweig)
- Test: `odoo/addons/picking_assistant_integration/tests/test_callback_projection.py`

**Interfaces:**
- Consumes: `api_apply_assessment` aus Task 7
- Produces: ein terminaler Callback mit `callback_name == "quality.assessment.status.v1"` schreibt den Alert in derselben Transaktion

- [ ] **Step 1: Failing test schreiben**

`odoo/addons/picking_assistant_integration/tests/test_callback_projection.py`:

```python
import json

from .common import IntegrationCase


class TestCallbackProjection(IntegrationCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "picking_assistant.instance_name", "local"
        )
        self.alert = self.env["quality.alert.custom"].create(
            {"description": "Karton zerdrueckt", "ai_evaluation_status": "pending"}
        )

    def _job_for_alert(self):
        built = self.env["quality.alert.event.builder"].build(self.alert)
        job, _outbox = self.env[
            "picking.assistant.integration.job"
        ]._enqueue_job_event(
            job_type="quality_assessment",
            aggregate_model=self.alert._name,
            aggregate_res_id=self.alert.id,
            aggregate_revision=self.alert.integration_revision,
            event_id=built["event_id"],
            event_name="quality.assessment.requested.v1",
            envelope_text=built["envelope_text"],
            payload_fingerprint=built["payload_fingerprint"],
            correlation_id=built["correlation_id"],
            job_id=built["job_id"],
        )
        return job, built

    def test_terminal_quality_callback_writes_the_alert(self):
        job, built = self._job_for_alert()
        self.env["picking.assistant.callback.receipt"].sudo()._project_quality_result(
            aggregate_model=self.alert._name,
            aggregate_res_id=self.alert.id,
            callback_name="quality.assessment.status.v1",
            status="succeeded",
            result={
                "disposition": "scrap",
                "confidence": 0.9,
                "provider": "ollama-local",
                "model": "qwen2.5:7b",
            },
            error=None,
        )
        self.assertEqual(self.alert.ai_evaluation_status, "completed")
        self.assertEqual(self.alert.ai_disposition, "scrap")

    def test_foreign_callback_name_is_ignored(self):
        self.env["picking.assistant.callback.receipt"].sudo()._project_quality_result(
            aggregate_model=self.alert._name,
            aggregate_res_id=self.alert.id,
            callback_name="shipping.label.status.v1",
            status="succeeded",
            result={"disposition": "scrap"},
            error=None,
        )
        self.assertEqual(self.alert.ai_evaluation_status, "pending")

    def test_running_status_does_not_project(self):
        self.env["picking.assistant.callback.receipt"].sudo()._project_quality_result(
            aggregate_model=self.alert._name,
            aggregate_res_id=self.alert.id,
            callback_name="quality.assessment.status.v1",
            status="running",
            result={},
            error=None,
        )
        self.assertEqual(self.alert.ai_evaluation_status, "pending")
```

Import in `tests/__init__.py` ergänzen.

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Odoo-Testbefehl mit `-u picking_assistant_integration`. Erwartet: FAIL, `_project_quality_result` fehlt.

- [ ] **Step 3: Projektionshelfer und Aufruf implementieren**

In `receipts.py`, Klasse `picking.assistant.callback.receipt`:

```python
    # Nur terminale Zustaende projizieren. `running` ist eine Zwischenmeldung
    # und darf den fachlichen Datensatz nicht anfassen.
    _PROJECTED_STATUSES = ("succeeded", "review_required", "failed")

    def _project_quality_result(
        self, *, aggregate_model, aggregate_res_id, callback_name, status, result, error
    ):
        """Traegt das Ergebnis in derselben Transaktion in den Fachdatensatz.

        Ohne diesen Schritt endet die Kette im Integrationslayer: Job und
        Receipt waeren vollstaendig, der Alert saehe aber unveraendert aus.
        """
        if callback_name != "quality.assessment.status.v1":
            return False
        if status not in self._PROJECTED_STATUSES:
            return False
        if aggregate_model != "quality.alert.custom":
            return False
        alert = self.env[aggregate_model].sudo().browse(int(aggregate_res_id))
        if not alert.exists():
            return False
        alert.api_apply_assessment(status, result, error)
        return True
```

In `api_apply_callback`, im Zweig, der den Job terminal abschließt (dort, wo heute `receipt.write(...)` den Abschluss festhält), unmittelbar vor der Rückgabe:

```python
                        self._project_quality_result(
                            aggregate_model=job.aggregate_model,
                            aggregate_res_id=job.aggregate_res_id,
                            callback_name=callback.get("callback_name"),
                            status=status,
                            result=result,
                            error=error,
                        )
```

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

Gleicher Befehl. Erwartet: drei neue Tests grün, `test_receipts_callbacks.py` weiterhin grün.

- [ ] **Step 5: Committen**

```bash
git add odoo/addons/picking_assistant_integration/
git commit -m "feat(odoo): let the terminal callback reach the alert it was about"
```

---

### Task 9: v2-signierte Bewertungsroute

**Files:**
- Modify: `backend/app/models/n8n.py`
- Modify: `backend/app/routers/n8n_v2.py`
- Test: `backend/tests/test_n8n_v2_assessment_route.py`

**Interfaces:**
- Produces: `POST /api/internal/n8n/v2/assessments/quality`, Anfrage `QualityAssessmentV2Request`, Antwort `QualityAssessmentV2Response`

- [ ] **Step 1: Failing test schreiben**

`backend/tests/test_n8n_v2_assessment_route.py`:

```python
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.llm_client import LlmDispositionResult
from tests.test_n8n_v2_routes import SIGNING_KEY, signed_headers  # noqa: F401

ASSESS_TARGET = "/api/internal/n8n/v2/assessments/quality"

ASSESS = {
    "schema_version": "v2",
    "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
    "job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    "odoo_instance": "o19-a",
    "delivery_generation": 1,
    "processing_lease_token": "lease-" + ("x" * 40),
    "description": "Karton zerdrueckt, Ware nass",
    "priority": "1",
    "photo_count": 2,
    "product_id": 42,
    "location_id": 8,
}


def assess_body(overrides=None):
    payload = dict(ASSESS)
    payload.update(overrides or {})
    return json.dumps(payload, separators=(",", ":")).encode()


class FakeLlm:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def classify_disposition(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


@pytest.fixture
def llm_ok(monkeypatch):
    from app import dependencies

    fake = FakeLlm(
        LlmDispositionResult(
            ok=True,
            model="qwen2.5:7b",
            disposition="scrap",
            confidence=0.95,
            summary="Ware unbrauchbar.",
            recommended_action="Artikel sperren.",
        )
    )
    app.dependency_overrides[dependencies.get_llm_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(dependencies.get_llm_client, None)


def test_signed_assessment_returns_the_verdict(signed_env, llm_ok):
    body = assess_body()
    with TestClient(app) as client:
        response = client.post(
            ASSESS_TARGET,
            content=body,
            headers=signed_headers(
                body, ASSESS_TARGET, idempotency_key=ASSESS["event_id"]
            ),
        )
    assert response.status_code == 200
    data = response.json()
    assert data["llm_ok"] is True
    assert data["disposition"] == "scrap"
    assert data["provider"] == "ollama-local"
    assert llm_ok.calls[0]["description"] == ASSESS["description"]


def test_unsigned_request_is_rejected(signed_env, llm_ok):
    body = assess_body()
    with TestClient(app) as client:
        response = client.post(
            ASSESS_TARGET,
            content=body,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": ASSESS["event_id"],
            },
        )
    assert response.status_code in (401, 403)
    assert llm_ok.calls == []


def test_idempotency_key_must_equal_event_id(signed_env, llm_ok):
    body = assess_body()
    with TestClient(app) as client:
        response = client.post(
            ASSESS_TARGET,
            content=body,
            headers=signed_headers(body, ASSESS_TARGET, idempotency_key="etwas-anderes"),
        )
    assert response.status_code == 409
    assert llm_ok.calls == []


def test_llm_failure_reports_not_ok_without_verdict(signed_env, monkeypatch):
    from app import dependencies

    fake = FakeLlm(LlmDispositionResult(ok=False, model="qwen2.5:7b"))
    app.dependency_overrides[dependencies.get_llm_client] = lambda: fake
    body = assess_body()
    try:
        with TestClient(app) as client:
            response = client.post(
                ASSESS_TARGET,
                content=body,
                headers=signed_headers(
                    body, ASSESS_TARGET, idempotency_key=ASSESS["event_id"]
                ),
            )
    finally:
        app.dependency_overrides.pop(dependencies.get_llm_client, None)
    assert response.status_code == 200
    data = response.json()
    assert data["llm_ok"] is False
    assert data["disposition"] is None
```

Der Fixture `signed_env` wird aus `tests/test_n8n_v2_routes.py` importiert; damit pytest ihn findet, in `backend/tests/conftest.py` ergänzen:

```python
from tests.test_n8n_v2_routes import signed_env  # noqa: F401
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

```bash
cd backend && PYTHONPATH=.deps python3 -m pytest tests/test_n8n_v2_assessment_route.py -v
```

Erwartet: FAIL mit 404 — die Route existiert nicht.

- [ ] **Step 3: Modelle ergänzen**

In `backend/app/models/n8n.py`:

```python
class QualityAssessmentV2Request(BaseModel):
    """Anfrage des v2-Workflows an die Bewertung.

    `extra="forbid"`, weil die v2-Strecke ausschliesslich mit Feldern arbeitet,
    die im Vertrag stehen -- ein unbekanntes Feld ist ein Vertragsbruch, kein
    Detail.
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["v2"]
    event_id: UUID
    job_id: UUID
    odoo_instance: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    delivery_generation: int = Field(ge=1)
    processing_lease_token: str = Field(min_length=32, max_length=256)
    description: str = ""
    priority: str = "0"
    photo_count: int = 0
    product_id: int | None = None
    location_id: int | None = None


class QualityAssessmentV2Response(BaseModel):
    llm_ok: bool
    disposition: str | None = None
    confidence: float | None = None
    summary: str | None = None
    recommended_action: str | None = None
    provider: str
    model: str
```

Nötige Importe (`Literal`, `UUID`, `Field`, `ConfigDict`) oben in der Datei ergänzen, falls nicht vorhanden.

- [ ] **Step 4: Route implementieren**

In `backend/app/routers/n8n_v2.py`, nach `apply_callback`:

```python
@router.post(V2 + "/assessments/quality", response_model=QualityAssessmentV2Response)
async def assess_quality(
    verified: VerifiedInternalRequest = Depends(verify_n8n_to_backend_request),
    llm: LlmClient = Depends(get_llm_client),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Bewertung durch das lokale Modell -- ohne jeden Schreibzugriff auf Odoo.

    Die Route ist die v2-Entsprechung von `/api/internal/llm/quality-disposition`.
    Sie existiert, weil der signierte n8n-Knoten keinen frei gesetzten Header
    tragen kann und die alte Route genau darauf besteht.
    """
    body = _verified_body(QualityAssessmentV2Request, verified, idempotency_key, "event_id")
    result = await llm.classify_disposition(
        description=body.description,
        priority=body.priority,
        photo_count=body.photo_count,
        product_id=body.product_id,
        location_id=body.location_id,
    )
    return QualityAssessmentV2Response(
        llm_ok=result.ok,
        disposition=result.disposition if result.ok else None,
        confidence=result.confidence if result.ok else None,
        summary=result.summary if result.ok else None,
        recommended_action=result.recommended_action if result.ok else None,
        provider=LlmClient.PROVIDER,
        model=result.model,
    )
```

Importe ergänzen: `get_llm_client`, `LlmClient`, `QualityAssessmentV2Request`, `QualityAssessmentV2Response`.

- [ ] **Step 5: Tests laufen lassen, grün bestätigen**

```bash
cd backend && PYTHONPATH=.deps python3 -m pytest tests/test_n8n_v2_assessment_route.py -v && PYTHONPATH=.deps python3 -m pytest -q
```

Erwartet: vier neue Tests grün, Gesamtsuite grün.

- [ ] **Step 6: Committen**

```bash
git add backend/app/models/n8n.py backend/app/routers/n8n_v2.py backend/tests/test_n8n_v2_assessment_route.py backend/tests/conftest.py
git commit -m "feat(backend): expose the local assessment behind the v2 signature"
```

---

### Task 10: Ersatzbewertung abschalten

**Files:**
- Modify: `backend/app/routers/quality.py:126-160` (Funktion `_apply_local_quality_fallback` entfernen) und `:274-330` (Aufrufstelle)
- Modify: `backend/tests/test_mobile_routes.py:440-463` (der bestehende Fallback-Test)
- Prüfen: `backend/tests/test_route_security.py` (nennt `/api/quality-alerts` ebenfalls)

**Interfaces:**
- Produces: `POST /api/quality-alerts` antwortet mit `ai_evaluation_status: "pending"` und schreibt keine Bewertung mehr

- [ ] **Step 1: Bestehende Erwartungen finden**

```bash
cd backend && grep -rn "backend-local-fallback\|ai_fallback\|_apply_local_quality_fallback" tests/ app/ | head -20
```

Jede Fundstelle in `tests/` ist eine Erwartung, die sich ändert.

- [ ] **Step 2: Test auf das neue Verhalten umschreiben**

In `backend/tests/test_mobile_routes.py` den Test, der heute
`payload["ai_fallback"] is True` und
`write_fields["ai_provider"] == "backend-local-fallback"` behauptet
(Zeilen 440-463), ersetzen durch:

```python
def test_alert_creation_leaves_the_verdict_to_the_chain(quality_env):
    """Kein Ersatzurteil mehr: die Route legt den Alert an und ist fertig.

    Frueher schrieb sie bei nicht zugestelltem v1-Webhook eine
    Stichwortheuristik. Seit die Kette ueber die Outbox laeuft, waere das ein
    zweiter Schreiber auf dieselben Felder -- und eine Bewertung, die kein
    Modell getroffen hat.
    """
    response = create_alert(quality_env, description="Karton zerdrueckt")
    assert response.status_code == 200
    data = response.json()
    assert data["ai_evaluation_status"] == "pending"
    assert "ai_fallback" not in data
    written = quality_env.odoo.writes_for("quality.alert.custom")
    assert all("ai_disposition" not in values for values in written)
```

Die Hilfsnamen (`quality_env`, `create_alert`, `writes_for`) an die in der Datei bereits vorhandenen Fixtures angleichen.

- [ ] **Step 3: Test laufen lassen, Fehlschlag bestätigen**

```bash
cd backend && PYTHONPATH=.deps python3 -m pytest tests/test_quality_routes.py -v
```

Erwartet: FAIL, weil die Route noch die Heuristik schreibt.

- [ ] **Step 4: Fallback und v1-Auslösung entfernen**

In `backend/app/routers/quality.py`:

1. Funktion `_apply_local_quality_fallback` und die nur von ihr benutzte `_infer_shadow_assessment` löschen.
2. Im Anschluss an `api_create_alert` den gesamten Block `event_result = coerce_event_result(await n8n.fire_event("quality-alert-created", …))` samt der daran hängenden Fallback-Behandlung entfernen.
3. Antwort vereinheitlichen:

```python
    response = {
        "alert_id": alert_id,
        "name": name,
        "photo_count": len(photo_list),
        # Die Bewertung kommt ueber die v2-Kette; Odoo hat den Alert bereits
        # auf `pending` gesetzt, als es das Ereignis eingereiht hat.
        "ai_evaluation_status": "pending",
    }
    await workflow.finalize_idempotent_request(reservation, response, 200)
    return response
```

4. Nicht mehr benutzte Importe und den Parameter `n8n: N8NWebhookClient = Depends(get_n8n_client)` entfernen, sofern die Route ihn sonst nirgends verwendet.

- [ ] **Step 5: Tests laufen lassen, grün bestätigen**

```bash
cd backend && PYTHONPATH=.deps python3 -m pytest -q
```

Erwartet: Gesamtsuite grün.

- [ ] **Step 6: Committen**

```bash
git add backend/app/routers/quality.py backend/tests/test_quality_routes.py
git commit -m "refactor(backend)!: stop inventing a verdict when the chain has not answered"
```

---

## Stufe 3 — Der Workflow

### Task 11: Workflow-Datei und Registry-Eintrag

**Files:**
- Create: `n8n/workflows/quality-assessment-v2.json`
- Modify: `n8n/workflow-registry.json`

**Interfaces:**
- Consumes: Route aus Task 9, Ereignis aus Task 4
- Produces: Webhook `quality-assessment-v2`, Ereignisziel für `quality.assessment.requested.v1`

- [ ] **Step 1: Vorlage aus der Historie holen**

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
git show b0cbbc6~1:./n8n/workflows/pwr-foundation-smoke-v2.json > /tmp/claude-1000/-home-endri/3a1fea15-b531-4cce-830b-91c37da61907/scratchpad/smoke-v2.json
```

Diese Datei ist die bewiesene Form bis einschließlich `If Process`: Webhook, Gate, Reject Response, Build Acceptance, PWR Signed Acceptance, Accepted Response, If Process werden mit identischen Parametern übernommen.

- [ ] **Step 2: Workflow bauen**

`n8n/workflows/quality-assessment-v2.json` mit folgenden Knoten. Die ersten sieben aus der Vorlage übernehmen (`Build Acceptance` ohne die Smoke-Felder `test_delay_seconds` und `artifact_probe`, dafür mit `callback_ids_by_generation` aus dem Payload). Danach:

`Build Assessment Request` (`n8n-nodes-base.set`), Zuweisungen:

| Feld | Ausdruck |
|---|---|
| `schema_version` | `v2` |
| `event_id` | `={{ $('Build Acceptance').item.json.event_id }}` |
| `job_id` | `={{ $('Build Acceptance').item.json.job_id }}` |
| `odoo_instance` | `={{ $('Build Acceptance').item.json.odoo_instance }}` |
| `delivery_generation` | `={{ $('Build Acceptance').item.json.delivery_generation }}` |
| `processing_lease_token` | `={{ $('PWR Signed Acceptance').item.json.processing_lease_token }}` |
| `description` | `={{ $('Build Acceptance').item.json.payload.description }}` |
| `priority` | `={{ $('Build Acceptance').item.json.payload.priority }}` |
| `photo_count` | `={{ $('Build Acceptance').item.json.payload.photo_count }}` |
| `product_id` | `={{ $('Build Acceptance').item.json.payload.product_id }}` |
| `location_id` | `={{ $('Build Acceptance').item.json.payload.location_id }}` |
| `idempotency_key` | `={{ $('Build Acceptance').item.json.event_id }}` |

Dafür muss `Build Acceptance` zusätzlich `payload` durchreichen:
`{"name": "payload", "type": "object", "value": "={{ $json.body.payload }}"}`.

`PWR Signed Assessment` (`pwrSignedHttpRequest`): `method: POST`,
`target: /api/internal/n8n/v2/assessments/quality`, `host: backend`,
`bodyMode: json`, `idempotencyKeyProperty: idempotency_key`,
`responseMode: json`, `onError: continueRegularOutput`.

`If Assessment OK` (`n8n-nodes-base.if`): Bedingung `={{ $json.llm_ok }}` **equal** `true`.

`Build Success Callback` und `Build Review Callback` (`n8n-nodes-base.set`), je ein Feld `callback_body` und ein Feld `idempotency_key`:

```
callback_id  = $('Build Acceptance').item.json.callback_ids
                 [String($('Build Acceptance').item.json.delivery_generation)].terminal
```

Fehlt der Eintrag, wirft der Ausdruck — genau so wie in der Smoke-Vorlage, damit der Lauf geschlossen scheitert statt still falsch zu schreiben.

`callback_body` (Erfolgszweig):

```json
{
  "schema_version": "v2",
  "callback_name": "quality.assessment.status.v1",
  "callback_id": "<terminal>",
  "source_event_id": "<event_id>",
  "correlation_id": "<correlation_id>",
  "odoo_instance": "<odoo_instance>",
  "job_id": "<job_id>",
  "sequence": 1,
  "attempt": 1,
  "delivery_generation": "<generation>",
  "processing_lease_token": "<lease>",
  "status": "succeeded",
  "execution_id": "<$execution.id>",
  "occurred_at": "<ISO-8601 Z>",
  "next_retry_at": null,
  "result": {
    "disposition": "<disposition>", "confidence": "<confidence>",
    "summary": "<summary>", "recommended_action": "<recommended_action>",
    "provider": "<provider>", "model": "<model>"
  },
  "error": null,
  "metrics": {"assessment_ms": "<Dauer>"}
}
```

Der Prüfzweig ist identisch, aber mit `"status": "review_required"`, `"result": {}` und
`"error": {"code": "llm_unavailable", "message": "<Fehlertext oder 'assessment unavailable'>"}`.

Beide Zweige zeigen auf `PWR Signed Terminal Callback` (`pwrSignedHttpRequest`,
`target: /api/internal/n8n/v2/callbacks/status`, `host: backend`, `bodyMode: json`,
`idempotencyKeyProperty: idempotency_key`).

Der `false`-Ausgang von `If Process` bleibt unverbunden.

- [ ] **Step 3: Registry-Eintrag ergänzen**

In `n8n/workflow-registry.json` unter `workflows`:

```json
{
  "file": "quality-assessment-v2.json",
  "name": "Quality Assessment v2",
  "generation": "v2",
  "event_names": ["quality.assessment.requested.v1"],
  "webhook_paths": ["quality-assessment-v2"],
  "callback_paths": [
    "/api/internal/n8n/v2/events/accept",
    "/api/internal/n8n/v2/assessments/quality",
    "/api/internal/n8n/v2/callbacks/status"
  ],
  "artifact_path_templates": [],
  "authentication": "native_header_hmac",
  "managed": true,
  "production_activation": true,
  "test_only": false,
  "activation_order": 10,
  "allowed_target_hosts": ["backend"],
  "credential_bindings": [
    {"node": "Webhook", "credential_type": "httpHeaderAuth", "logical_name": "pwr.v2.inbound-header"},
    {"node": "PWR Signature Gate", "credential_type": "pwrInboundHmac", "logical_name": "pwr.v2.backend-to-n8n-hmac"},
    {"node": "PWR Signed Acceptance", "credential_type": "pwrOutboundHmac", "logical_name": "pwr.v2.n8n-to-backend-hmac"},
    {"node": "PWR Signed Assessment", "credential_type": "pwrOutboundHmac", "logical_name": "pwr.v2.n8n-to-backend-hmac"},
    {"node": "PWR Signed Terminal Callback", "credential_type": "pwrOutboundHmac", "logical_name": "pwr.v2.n8n-to-backend-hmac"}
  ]
}
```

- [ ] **Step 4: Verifier laufen lassen**

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
python3 infrastructure/scripts/verify-workflows.py
```

Erwartet: keine Befunde. Jeder Befund nennt die verletzte Pflicht — die Datei danach korrigieren, nicht den Verifier.

- [ ] **Step 5: Backend-Suite laufen lassen**

```bash
cd backend && PYTHONPATH=.deps python3 -m pytest -q
```

Erwartet: grün. `load_event_targets` liest den neuen Eintrag; ein Tippfehler im Pfad fällt hier auf.

- [ ] **Step 6: Committen**

```bash
git add n8n/workflows/quality-assessment-v2.json n8n/workflow-registry.json
git commit -m "feat(n8n): land the verifier-conform quality assessment workflow"
```

---

### Task 12: Credentials, Import, Aktivierung

**Files:**
- Keine Codeänderung; Betrieb

- [ ] **Step 1: Credentials neu provisionieren**

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" compose -f docker-compose.yml -f docker-compose.dev.yml --profile provision \
  run --rm n8n-credentials
```

Erwartet: drei Credentials angelegt (`pwr.v2.inbound-header`, `pwr.v2.backend-to-n8n-hmac`, `pwr.v2.n8n-to-backend-hmac`).

- [ ] **Step 2: Owner-Setup**

http://127.0.0.1:5678 im Browser öffnen und den Besitzer anlegen. Die Instanz wurde am 2026-08-04 geleert, deshalb fragt n8n erneut danach.

- [ ] **Step 3: Importieren und aktivieren**

```bash
bash infrastructure/scripts/import-workflows.sh
```

Erwartet: `quality-assessment-v2.json` importiert und aktiviert. `assert_activatable` verweigert bei doppeltem Namen — tritt das auf, existiert noch ein Rest in n8n, der zuerst weg muss.

- [ ] **Step 4: Webhook-Registrierung prüfen**

```bash
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" exec mobilepickingundvoiceassistant-db-1 psql -U odoo -d n8n -tAc \
  "select \"webhookPath\", method from webhook_entity;"
```

Erwartet: genau eine Zeile, `quality-assessment-v2 | POST`.

- [ ] **Step 5: Committen**

Nichts zu committen; Ergebnis der Prüfungen in der Aufgabennotiz festhalten.

---

## Stufe 4 — Betrieb und Beweis

### Task 13: Dispatcher und Ausführungsprotokoll einschalten

**Files:**
- Modify: `docker-compose.yml` (Dienste `backend` und `n8n`)
- Modify: `.env.example`

- [ ] **Step 1: Compose ergänzen**

Im Dienst `backend` unter `environment`:

```yaml
      # Ohne dieses Flag laeuft der Outbox-Dispatcher nicht und kein Ereignis
      # wird je zugestellt (Default in config.py ist False).
      DISPATCHER_ENABLED: ${DISPATCHER_ENABLED:-true}
```

Im Dienst `n8n` unter `environment` ändern:

```yaml
      # Ohne gespeicherte Erfolgslaeufe gibt es keinen Ausfuehrungsnachweis.
      EXECUTIONS_DATA_SAVE_ON_SUCCESS: all
```

In `.env.example` ergänzen und den toten Wert korrigieren:

```
DISPATCHER_ENABLED=true
# Innerhalb von Compose gilt http://n8n:5678/webhook; ein Backend ausserhalb
# von Compose darf NICHT gegen eine fremde Domain signieren.
N8N_WEBHOOK_BASE=http://n8n:5678/webhook
```

- [ ] **Step 2: Neu starten und Dispatcher belegen**

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" compose -f docker-compose.yml -f docker-compose.dev.yml --profile second-odoo up -d backend n8n
"$DOCKER" logs --tail 30 mobilepickingundvoiceassistant-backend-1 2>&1 | grep -i "dispatcher\|instance"
```

Erwartet: kein Startfehler zu Instanznamen, Dispatcher läuft.

- [ ] **Step 3: Committen**

```bash
git add docker-compose.yml .env.example
git commit -m "chore(infra): turn on the dispatcher and keep the successful runs"
```

---

### Task 14: Live-Nachweis

**Files:**
- Keine Codeänderung; Nachweis

- [ ] **Step 1: Instanznamen setzen**

```bash
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
for db in masterfischer_o19:local lager2_o19:lager-2; do
  name="${db#*:}"; dbname="${db%%:*}"
  "$DOCKER" exec mobilepickingundvoiceassistant-db-1 psql -U odoo -d "$dbname" -c \
    "insert into ir_config_parameter (key, value) values ('picking_assistant.instance_name', '$name')
     on conflict (key) do update set value = excluded.value;"
done
```

- [ ] **Step 2: Module auf beiden Instanzen aktualisieren**

```bash
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" exec mobilepickingundvoiceassistant-odoo-1 sh -c \
  'odoo -c /etc/odoo/odoo.conf -d masterfischer_o19 --db_host=db --db_user=$USER --db_password=$PASSWORD \
   --http-port=8199 --gevent-port=8299 -u quality_alert_custom,picking_assistant_integration --stop-after-init'
"$DOCKER" exec mobilepickingundvoiceassistant-odoo-lager-2-1 sh -c \
  'odoo -c /etc/odoo/odoo.conf -d lager2_o19 --db_host=db --db_user=$USER --db_password=$PASSWORD \
   --http-port=8199 --gevent-port=8299 -u quality_alert_custom,picking_assistant_integration --stop-after-init'
```

- [ ] **Step 3: Ollama vorwärmen**

```bash
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" exec mobilepickingundvoiceassistant-ollama-1 ollama run qwen2.5:7b "OK"
```

Ohne Warmlauf liegt die erste CPU-Inferenz deutlich über 45 s und der erste Durchlauf landet in `review_required`.

- [ ] **Step 4: Erfolgslauf auf Lager 1**

Über die PWA einen Alert mit der Beschreibung „Karton komplett zerbrochen, Ware zerstört" und Priorität 1 anlegen. Dann:

```bash
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" exec mobilepickingundvoiceassistant-db-1 psql -U odoo -d masterfischer_o19 -tAc \
  "select name, ai_evaluation_status, ai_provider, ai_disposition, ai_confidence, ai_model
     from quality_alert_custom order by id desc limit 1;"
```

Erwartet innerhalb von 60 s: `completed | ollama-local | scrap | 0.9x | qwen2.5:7b`.
**`ai_provider` muss `ollama-local` sein** — jeder andere Wert hieße, dass nicht das Modell geantwortet hat.

- [ ] **Step 5: Negativlauf**

```bash
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" stop mobilepickingundvoiceassistant-ollama-1
```

Erneut einen Alert anlegen, dann dieselbe Abfrage. Erwartet:
`review_required`, `ai_disposition` **leer**, `ai_failure_reason` gesetzt.
Danach `"$DOCKER" start mobilepickingundvoiceassistant-ollama-1`.

- [ ] **Step 6: Zweite Instanz**

Denselben Erfolgslauf gegen Lager 2 fahren (PWA-Instanzumschalter auf „Lager 2"). Prüfen:

```bash
"$DOCKER" exec mobilepickingundvoiceassistant-db-1 psql -U odoo -d lager2_o19 -tAc \
  "select name, ai_evaluation_status, ai_provider from quality_alert_custom order by id desc limit 1;"
"$DOCKER" exec mobilepickingundvoiceassistant-db-1 psql -U odoo -d masterfischer_o19 -tAc \
  "select count(*) from quality_alert_custom where create_date > now() - interval '5 minutes';"
```

Erwartet: der Datensatz steht in `lager2_o19`, und in `masterfischer_o19` ist **nichts** dazugekommen.

- [ ] **Step 7: Nachweis sichern**

```bash
"$DOCKER" exec mobilepickingundvoiceassistant-db-1 psql -U odoo -d n8n -c \
  "select \"workflowId\", status, \"startedAt\", \"stoppedAt\" from execution_entity order by id desc limit 5;"
```

Erwartet: gespeicherte Erfolgsläufe (aus Task 13) als Ausführungsnachweis.

---

## Self-Review

**Spec-Abdeckung:**

| Spec-Abschnitt | Task |
|---|---|
| §5 Workflow | 11 |
| §6.1 neue Bewertungsroute | 9 |
| §6.2 Heuristik abschalten | 10 |
| §6.3 Dispatcher an | 13 |
| §6.4 Startprüfung | 6 |
| §7.1 Auslöser + Fingerprint | 3, 4, 5 |
| §7.2 Instanzname | 2, 14 (Step 1) |
| §7.3 aggregate_revision | 1 |
| §7.4 Projektion | 7, 8 |
| §9 Betrieb | 12, 13 |
| §10 Tests und Nachweis | in jeder Task, Live-Teil in 14 |

**Offene Abhängigkeit:** Task 6 setzt voraus, dass `runtime` die konfigurierten
Instanzen aufzählbar macht. Trifft das nicht zu, verwendet der Implementierende
`get_instance_registry(runtime.settings)` und gleicht den Test an — das ist im
Task als Schritt vermerkt.

**Reihenfolge:** Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14.
Nach Task 10 ist die erzeugende und empfangende Seite vollständig; die Ereignisse
liegen dann sichtbar mit `unregistered_event_target` in der Outbox, bis Task 11
den Konsumenten landet.
