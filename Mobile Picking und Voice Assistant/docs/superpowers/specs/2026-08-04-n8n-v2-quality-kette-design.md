# Design: v2-Qualitätskette (Odoo → Backend → n8n → LLM → Odoo)

**Datum:** 2026-08-04
**Status:** Entwurf zur Freigabe
**Ersetzt:** die am 2026-08-04 gelöschten v1-Workflows (`quality-alert-created.json` und acht weitere)

---

## 1. Ausgangslage

Am 2026-08-04 wurden die n8n-Instanz und alle Workflow-Dateien im Repo geleert
(Backup: `Desktop/Bachelor/backup-n8n-2026-08-04/`, Git-Historie ab `HEAD`).
Zurück blieb eine Plattform, die vollständig gebaut, getestet und **nie benutzt**
worden ist:

* `backend/app/models/events.py:8` kennt zwei Ereignisse
  (`quality.assessment.requested.v1`, `shipment.parcel.ready.v1`) und zwei
  Rückmeldungen.
* `backend/app/services/outbox_dispatcher.py` least fällige Outbox-Zeilen je
  Odoo-Instanz und stellt sie signiert zu.
* `backend/app/routers/n8n_v2.py` nimmt Annahme und Callback entgegen.
* `odoo/addons/picking_assistant_integration/` hält Outbox, Job, Leases,
  Nonces und Receipts.
* `infrastructure/scripts/workflow_verifier.py` beweist zehn Graph-Pflichten
  für jeden v2-Workflow.

Der einzige v2-Workflow, den es je gab (`pwr-foundation-smoke-v2.json`), war
als `test_only` markiert und hat nie fachlich gearbeitet. **Der Grund, warum
die Plattform tot war, ist ein einziger:** niemand ruft
`_enqueue_job_event` (`odoo/addons/picking_assistant_integration/models/integration_job.py:95`)
auf, also entsteht nie ein Ereignis.

## 2. Ziel

Eine fachlich vollständige Kette: Ein Picker meldet einen Qualitätsmangel, ein
lokales Sprachmodell bewertet ihn, und das Ergebnis steht am Odoo-Datensatz —
über die signierte v2-Strecke, nachweisbar Ende zu Ende, ohne Cloud.

**Nicht Ziel:** Breite. Die v1-Ketten (Kommissionierung, Fehlmenge,
Sprachausnahme, Tagesbericht) werden bewusst nicht wiederhergestellt.

## 3. Getroffene Entscheidungen

| # | Entscheidung | Begründung |
|---|---|---|
| E1 | Eine tiefe Kette statt mehrerer flacher | nutzt die v2-Plattform vollständig aus; als Kapitel geschlossen darstellbar |
| E2 | Auslöser in Odoo, in derselben Transaktion wie der Alert | Transactional Outbox: kein Alert ohne Ereignis, kein Ereignis ohne Alert |
| E3 | **Ein** verifierkonformer n8n-Workflow, keine Sub-Workflows | `executeWorkflow` fehlt in beiden Allowlisten des Verifiers (`workflow_verifier.py:825`, `:891`); ein Sub-Workflow verlässt den Graphen, über den die Dominanz bewiesen wird |
| E4 | LLM über das Backend, nicht direkt aus n8n | Prompt, JSON-Zwang, Zeitlimit bleiben in getestetem Python; ausgehende Netzwerkzugriffe sind ohnehin auf den signierten Knoten beschränkt (`:799`) |
| E5 | Neue v2-signierte Bewertungsroute statt der v1-Header-Route | der signierte Knoten kann kein `X-N8N-Callback-Secret` senden (`PwrSignedHttpRequest.node.ts:265`, `dependencies.py:572`) |
| E6 | Kein Ersatzurteil bei LLM-Ausfall, sondern `review_required` | das System behauptet nie eine Bewertung, die kein Modell getroffen hat |
| E7 | Repo ist Quelle, Import über das bestehende Skript | `stage_workflow.py` injiziert Laufzeit-IDs; die geprüften Dateien bleiben ID-frei |

## 4. Architektur

Sechs Stationen, jede mit genau einem Besitzer:

```
[1] Odoo        quality.alert.custom.api_create_alert
                  └─ legt Alert an  UND  _enqueue_job_event(...)   ← eine Transaktion
[2] Backend     OutboxDispatcher.run_once(instance)
                  └─ POST http://n8n:5678/webhook/quality-assessment-v2   (HMAC signiert)
[3] n8n         quality-assessment-v2
                  ├─ Signatur prüfen
                  ├─ POST /api/internal/n8n/v2/events/accept        → process, lease
                  ├─ Antwort {"accepted": true, "event_id": …}      ← innerhalb 10 s
                  └─ POST /api/internal/n8n/v2/assessments/quality  → Bewertung
[4] Backend     LlmClient.classify_disposition → Ollama (qwen2.5:7b, CPU)
[5] n8n         POST /api/internal/n8n/v2/callbacks/status          (succeeded | review_required)
[6] Odoo        api_apply_callback
                  └─ Job-Zustand, Receipt  UND  Projektion auf ai_*  ← eine Transaktion
```

Station 1 und Station 6 sind dasselbe Muster an beiden Enden: die
Zustandsänderung und ihr Beleg entstehen zusammen oder gar nicht. Das ist das
tragende Argument der Architektur.

### 4.1 Warum n8n intern nicht zerlegt wird

Der Verifier beweist, dass **jeder** wirksame Knoten vom `true`-Zweig des
`process`-Gates dominiert wird und dass die Annahme ihrerseits das Gate
dominiert (Pflichten 7 und 9, `workflow_verifier.py:1306`). Erreichbarkeit
genügt ausdrücklich nicht — ein Nebenpfad um das Gate herum wäre ebenfalls
erreichbar. Ein Sub-Workflow-Aufruf verlässt den analysierten Graphen und macht
diesen Beweis unmöglich. Die Kette ist deshalb nicht kleiner geschnitten,
sondern liegt eine Ebene höher: sechs Segmente über vier Systeme, jedes mit
eigener Signatur und eigenem Beleg.

## 5. Der Workflow

**Datei:** `n8n/workflows/quality-assessment-v2.json`
**Vorlage:** `git show HEAD:./n8n/workflows/pwr-foundation-smoke-v2.json`
(gleicher Webhook-Pfad, gleiche Knotenfolge bis zum `process`-Gate)

### 5.1 Knoten

| Knoten | Typ | Wesentliche Parameter |
|---|---|---|
| `Webhook` | `n8n-nodes-base.webhook` | `path: quality-assessment-v2`, `httpMethod: POST`, `authentication: headerAuth`, `responseMode: responseNode`, `options.rawBody: true` |
| `PWR Signature Gate` | `pwrSignatureGate` | `expectedMethod: POST`, `expectedTarget: /webhook/quality-assessment-v2` |
| `Reject Response` | `respondToWebhook` | einziger Knoten am `Rejected`-Ausgang |
| `Build Acceptance` | `set` | baut `event_id`, `job_id`, `odoo_instance`, `payload_fingerprint` (aus `pwr.body_sha256`), `ingress_key_id`, `ingress_nonce`, `delivery_generation`, `idempotency_key = event_id` |
| `PWR Signed Acceptance` | `pwrSignedHttpRequest` | `target: /api/internal/n8n/v2/events/accept`, `host: backend`, `bodyMode: json` |
| `Accepted Response` | `respondToWebhook` | Körper **exakt** `{"accepted": true, "event_id": "={{ $json.event_id }}"}` — kein weiteres Feld, sonst `ambiguous_acceptance` |
| `If Process` | `if` | `process` **equal** `true` |
| `Build Assessment Request` | `set` | Alert-Daten aus dem Ereignis-Payload + Job-/Lease-Felder |
| `PWR Signed Assessment` | `pwrSignedHttpRequest` | `target: /api/internal/n8n/v2/assessments/quality`, `host: backend`, `onError: continueRegularOutput` |
| `If Assessment OK` | `if` | `llm_ok` equal `true` |
| `Build Success Callback` / `Build Review Callback` | `set` | `CallbackEnvelopeV2`, `status: succeeded` bzw. `review_required`; beide münden in denselben Callback-Knoten |
| `PWR Signed Terminal Callback` | `pwrSignedHttpRequest` | `target: /api/internal/n8n/v2/callbacks/status`, `host: backend` |

Beide Zweige von `If Assessment OK` zeigen auf **einen** Callback-Knoten; ein
`merge`-Knoten ist post-Annahme nicht zugelassen und auch nicht nötig, weil je
Lauf nur ein Zweig Items führt. `sequence` ist 1, da diese Kette genau eine
Rückmeldung je Zustellung sendet; `idempotency_key = callback_id`, weil
`_verified_body` den Header gegen `callback_id` prüft.

**`callback_id` kann n8n nicht selbst erzeugen.** Ausdrücke in `set`-Knoten
haben keinen Zugriff auf einen UUID-Generator, und `code`-Knoten sind
post-Annahme verboten. Der Smoke-Workflow löste das über
`payload.callback_ids_by_generation` — im Test eine feste Fixture. Für die
produktive Kette übernimmt **Odoo** diese Rolle: `_enqueue_job_event` legt im
Payload eine Abbildung `{"1": {"terminal": "<uuid>"}, "2": {…}, …}` für die
Generationen 1 bis 5 ab. Der Workflow wählt den Eintrag zur signierten
Generation und **scheitert geschlossen**, wenn keiner existiert — dann läuft
die Lease ab, der Watchdog erhöht die Generation, und der Job endet
irgendwann sichtbar als `dead` statt still falsch zu schreiben. Fünf
Generationen bedeuten fünf Lease-Wiederherstellungen; ein Job, der so weit
kommt, ist ohnehin ein Betriebsfall und kein Zustellproblem.

`Accepted Response` reicht seine Eingabe durch, damit die Ausführung nach der
Antwort weiterlaufen kann.

Der `false`-Zweig von `If Process` endet ohne Knoten (Pflicht 8). Post-Annahme
sind ausschließlich `pwrSignedHttpRequest`, `respondToWebhook`, `set`, `if`,
`wait` zulässig — insbesondere **kein** `code`-Knoten. Alle Feldabbildungen
laufen deshalb über `set`-Ausdrücke.

Die `set`-Knoten dürfen keine Fotoanalyse behaupten: der Verifier lehnt einen
Quality-Workflow ab, der aus `photo_count` allein eine Bildauswertung ableitet.
Bilder sind in dieser Kette nicht Gegenstand der Bewertung.

### 5.2 Registry-Eintrag

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

`workflow_targets.py:56` verlangt für jeden v2-Eintrag genau einen
Webhook-Pfad; `load_registry` verlangt zusätzlich, dass Registry und Verzeichnis
`n8n/workflows/` deckungsgleich sind.

Die Aktivierung läuft über `assert_activatable`
(`infrastructure/scripts/stage_workflow.py:74`): sie verlangt
`production_activation`, verifizierte Credentials und **keinen doppelten
Workflow-Namen auf der Instanz**. Genau diese dritte Bedingung ist der Schutz
gegen die Dublette, die es früher zweimal „Pick Confirmed" gab.

## 6. Backend-Änderungen

### 6.1 Neue Route `POST /api/internal/n8n/v2/assessments/quality`

* Wache: `verify_n8n_to_backend_request` + `_verified_body(..., "event_id")`,
  also identische Guard-Kette wie `/events/accept`. Der `Idempotency-Key` muss
  gleich `event_id` sein.
* Körper (StrictModel): `schema_version`, `event_id`, `job_id`, `odoo_instance`,
  `delivery_generation`, `processing_lease_token`, `description`, `priority`,
  `photo_count`, `product_id`, `location_id`.
* Antwort: `llm_ok`, `disposition`, `confidence`, `summary`,
  `recommended_action`, `provider`, `model`, `latency_ms`.
* Intern unverändert `LlmClient.classify_disposition`; kein Odoo-Schreibzugriff.
* Die alte Route `/api/internal/llm/quality-disposition` bleibt vorerst
  bestehen (v1-Kompatibilität), wird von dieser Kette aber nicht benutzt.

### 6.2 Backend-Heuristik abschalten

`backend/app/routers/quality.py:126` `_apply_local_quality_fallback` schreibt
heute bei jedem nicht zugestellten v1-Webhook eine Stichwort-Bewertung mit
`ai_provider=backend-local-fallback` — seit dem Löschen des v1-Workflows also
bei **jedem** Alert. Das widerspricht E6 und erzeugt einen zweiten Schreiber auf
dieselben Felder.

Neu: die Alert-Erstellung feuert keinen v1-Webhook mehr und schreibt keine
Ersatzbewertung. Sie setzt `ai_evaluation_status = pending`; alles Weitere
kommt über die Kette.

### 6.3 Dispatcher einschalten

`config.py:189` `dispatcher_enabled` steht auf `False` und wird nirgends
gesetzt. Neu: `DISPATCHER_ENABLED=true` in `docker-compose.yml` und
`.env.example`. Der Wert `N8N_WEBHOOK_BASE` in der lokalen `.env` zeigt auf
`https://n8n.diti-ai.org/webhook` und ist tot (Compose setzt hart
`http://n8n:5678/webhook`); er wird in `.env.example` korrigiert, damit ein
Backend außerhalb von Compose nicht an einen fremden Host signiert.

### 6.4 Startprüfung Instanzname

Beim Start liest das Backend je konfigurierter Instanz den Odoo-Parameter
`picking_assistant.instance_name` und vergleicht ihn mit dem Profilnamen aus
`get_instance_registry()`. Abweichung oder fehlender Parameter ist ein
Startfehler, keine Warnung.

## 7. Odoo-Änderungen

### 7.1 Auslöser in `api_create_alert`

`odoo/addons/quality_alert_custom/models/quality_alert.py:163` legt den Alert
an. Direkt danach, in derselben Transaktion:

1. `aggregate_revision` des Alerts lesen (siehe 7.3),
2. Envelope nach `EventEnvelopeV2` bauen,
3. `envelope_text = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`,
4. `payload_fingerprint = sha256(envelope_text.encode("utf-8")).hexdigest()`,
5. `_enqueue_job_event(job_type="quality.assessment", aggregate_model="quality.alert.custom", …)`.

**Der Fingerprint ist bitgenau.** `api_accept_event`
(`receipts.py:436`) vergleicht ihn mit dem Wert, den n8n aus
`pwr.body_sha256` meldet — und das Gate hasht genau die Bytes, die der
Dispatcher überträgt (`outbox_dispatcher.py:146` sendet `envelope_text` als
UTF-8 unverändert). Jede andere Definition (Hash nur über `payload`, oder ein
zweites `json.dumps` mit anderen Trennzeichen) endet in einem 409, der wie ein
Signaturfehler aussieht. Ein Kreuztest hält Python- und Node-Seite zusammen.

`event_id` und `correlation_id` sind frische UUIDs aus Odoo; `causation_id`
bleibt leer, weil die Meldung des Pickers der Anfang der Kausalkette ist.

**Ereignis-Payload:**

```json
{
  "alert_id": 154, "name": "QA/0154",
  "description": "…", "priority": "1", "photo_count": 2,
  "product_id": 42, "location_id": 8, "picking_id": 17,
  "job_id": "<uuid>",
  "callback_ids_by_generation": {
    "1": {"terminal": "<uuid>"}, "2": {"terminal": "<uuid>"},
    "3": {"terminal": "<uuid>"}, "4": {"terminal": "<uuid>"},
    "5": {"terminal": "<uuid>"}
  }
}
```

`job_id` gehört in den Payload, weil der Annahme-Aufruf ihn braucht und der
Envelope-Kopf ihn nicht führt (so löst es auch die Smoke-Vorlage:
`$json.body.payload.job_id`).

### 7.2 Instanzname

Neuer Parameter `picking_assistant.instance_name` (`ir.config_parameter`), je
Instanz gesetzt (`local`, `lager-2`). Er füllt `source.odoo_instance` im
Envelope und steuert damit, in welche Datenbank der Callback zurückschreibt
(`n8n_v2.py:180`). Ohne ihn wäre seit dem Start von Lager 2 nicht entscheidbar,
welche der beiden Instanzen ein Ereignis gesendet hat.

### 7.3 `aggregate_revision`

`_enqueue_job_event` verlangt `aggregate_revision >= 1`;
`quality.alert.custom` hat kein solches Feld. Neu: `integration_revision`
(Integer, Default 1), erhöht bei jeder Änderung an `description`, `priority`
oder den Fotos. Ein späteres Ereignis zum selben Alert trägt damit eine höhere
Revision und kann ein älteres ablösen.

### 7.4 Projektion im Callback

`api_apply_callback` schreibt heute nur Job und Receipt. Neu: für
`callback_name = quality.assessment.status.v1` wird das `result` in derselben
Transaktion auf den Alert projiziert:

| Callback | Alert-Feld |
|---|---|
| `result.disposition` | `ai_disposition` |
| `result.confidence` | `ai_confidence` |
| `result.summary` | `ai_summary` |
| `result.recommended_action` | `ai_recommended_action` |
| `result.provider` | `ai_provider` (erwartet `ollama-local`) |
| `result.model` | `ai_model` |
| `occurred_at` | `ai_last_analyzed_at` |
| `status` | `ai_evaluation_status` |

`ai_evaluation_status` kennt heute nur `pending | completed | failed`
(`quality_alert.py:83`) und bekommt den vierten Wert `review_required`.
Abbildung: `succeeded → completed`, `review_required → review_required`,
`failed → failed` mit `ai_failure_reason` aus `error.message`.

## 8. Fehler, Fristen, Idempotenz

**Zeitbudget.** `SignedWebhookTransport` wartet 10 s auf die Annahme und
akzeptiert exakt `{"accepted": true, "event_id": …}`. Die Bewertung dauert
30–45 s auf der Lab-CPU. Deshalb steht `Accepted Response` **hinter** dem
Annahme-Aufruf (nur dort ist `respondToWebhook` erlaubt) und **vor** dem
`process`-Gate. Der Annahme-Aufruf selbst ist ein kurzer Odoo-Roundtrip.

**Verarbeitungs-Lease.** `PROCESSING_LEASE_SECONDS = 300` (`receipts.py:27`) —
fünf Minuten, also reichlich Luft. Läuft die Lease dennoch ab, weist der
Callback mit `processing_lease_expired` zurück und der Watchdog
(`api_recover_stalled_jobs`) erhöht die Generation und stellt neu zu.

**Wiederholte Zustellung.** Die Ingress-Nonce wird beim Annehmen reserviert
(`receipts.py:383`); eine zweite Zustellung derselben Generation prallt ab. Ist
bereits eine Lease aktiv oder der Receipt abgeschlossen, antwortet die Annahme
mit `process: false` und der Lauf endet wirkungslos.

**LLM-Ausfall.** `onError: continueRegularOutput` am Bewertungsknoten, danach
`If Assessment OK`. Fehlschlag heißt `status: review_required` mit
`error.code = llm_unavailable`; es wird **keine** Ersatzbewertung geschrieben.

**Odoo nicht erreichbar.** Die Outbox-Zeile bleibt liegen und läuft über den
eingefrorenen Backoff `(10, 60, 300, 1800, 7200, 21600 …)` (`outbox.py:10`).

## 9. Betrieb

1. `docker compose --profile provision run --rm n8n-credentials` — legt die
   drei logischen Credentials neu an (die Instanz wurde geleert).
2. Owner-Setup in n8n einmalig im Browser.
3. `infrastructure/scripts/import-workflows.sh` importiert, staged die IDs und
   aktiviert; die State-Datei wird neu aufgebaut, weil die alten Laufzeit-IDs
   mit der Datenbank verschwunden sind.
4. `EXECUTIONS_DATA_SAVE_ON_SUCCESS` von `none` auf `all` — ohne gespeicherte
   Erfolgsläufe gibt es keinen Ausführungsnachweis für die Arbeit.

## 10. Tests und Nachweis

| Ebene | Prüfung |
|---|---|
| Odoo-Unit | `api_create_alert` legt genau eine Outbox-Zeile an; Rollback des Alerts rollt das Ereignis mit zurück |
| Kreuztest | `sha256(envelope_text)` in Python == `body_sha256` des Gates in Node — eine Datei, zwei Leser |
| Backend-Unit | neue Bewertungsroute: Signatur, Idempotency-Key-Gleichheit, `llm_ok: false` bei Ollama-Ausfall |
| Backend-Unit | Projektion: `succeeded → completed`, `review_required → review_required` |
| Verifier | `verify-workflows.py` gegen `quality-assessment-v2.json` — alle zehn Pflichten |
| Registry | Registry und Verzeichnis deckungsgleich; `load_event_targets` liefert genau ein Ziel |
| Live-E2E | Alert über die PWA anlegen → nach ≤ 60 s `ai_provider = ollama-local` am Odoo-Datensatz, dazu n8n-Execution und Backend-Log |
| Live-Negativ | Ollama gestoppt → `ai_evaluation_status = review_required`, **kein** `ai_disposition` |
| Zwei Instanzen | derselbe Ablauf gegen Lager 1 und Lager 2; jeder Callback landet in der richtigen Datenbank |

## 11. Bewusst nicht enthalten

* Bildauswertung durch das Modell (Fotos bleiben Anhang; der Verifier verbietet
  ausdrücklich, aus `photo_count` eine Bildanalyse abzuleiten).
* Wiederherstellung der v1-Ketten.
* `shipment.parcel.ready.v1` — das zweite deklarierte Ereignis bleibt unbedient.
* Erweiterung des Verifiers um Sub-Workflows.
* Ein zweiter Versuch mit größerem Zeitlimit vor `review_required`.

## 12. Umsetzungsreihenfolge

Vier Stufen, jede für sich prüfbar. Keine Stufe braucht die nächste, um grün zu
sein.

1. **Erzeugende Seite.** `integration_revision`, `instance_name`-Parameter,
   Fingerprint-Definition, `_enqueue_job_event` in `api_create_alert`,
   Backend-Startprüfung. Nachweis: ein Alert erzeugt genau eine Outbox-Zeile mit
   korrektem Fingerprint; Kreuztest Python/Node grün.
2. **Empfangende Seite.** Neue Bewertungsroute, Projektion im Callback,
   `review_required` als vierter Statuswert, Abschalten der Backend-Heuristik.
   Nachweis: Backend-Suite grün, Projektion per Unit-Test belegt.
3. **Workflow.** `quality-assessment-v2.json`, Registry-Eintrag, Verifier-Lauf,
   Import und Aktivierung. Nachweis: `verify-workflows.py` ohne Befund,
   Workflow aktiv, Webhook registriert.
4. **Betrieb und Beweis.** Dispatcher an, Execution-Logging an, Live-E2E auf
   Lager 1 und Lager 2, Negativlauf mit gestopptem Ollama.

Nach Stufe 1 und 2 ist die Kette funktionsfähig, aber ohne Konsument: die
Outbox-Zeilen bleiben mit `unregistered_event_target` liegen und laufen über den
Backoff — ein sauberer, sichtbarer Zwischenzustand, kein Datenverlust.

## 13. Offene Risiken

1. **n8n-Ausdrücke statt Code.** Ohne `code`-Knoten müssen alle Abbildungen als
   `set`-Ausdrücke geschrieben werden. Bei verschachtelten Callback-Körpern ist
   das mühsam und schlecht testbar; Gegenmittel ist der Verifier-Lauf plus ein
   echter Live-Durchlauf, nicht Nachdenken am Canvas.
2. **Fingerprint-Kanonisierung.** Der Kreuztest muss vor dem ersten Live-Lauf
   grün sein, sonst kostet ein 409 unnötig Suchzeit.
3. **Erste CPU-Inferenz nach Kaltstart** kann deutlich über 45 s liegen.
   `VOICE_LLM_WARMUP` wärmt heute nur das Sprachmodell; für die Bewertung ist
   ein eigener Warmlauf nötig oder der erste Durchlauf landet in
   `review_required`.
4. **Odoo-Modulupgrade** für `integration_revision` und den vierten Statuswert
   trifft beide Instanzen und muss auf `masterfischer_o19` und `lager2_o19`
   laufen.
