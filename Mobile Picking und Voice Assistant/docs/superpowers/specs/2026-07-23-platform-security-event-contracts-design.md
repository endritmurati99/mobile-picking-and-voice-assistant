# Design Spec: Platform Security and Event Contracts

- **Datum:** 2026-07-23
- **Status:** Vom User als erste Foundation des Modernisierungsprogramms freigegeben; schriftlicher Review vor Ausfuehrungsplanung
- **Programm:** `docs/superpowers/specs/2026-07-23-parallel-modernization-program-design.md`
- **Scope:** PWA-Authentifizierung, Odoo-Instanzbindung, n8n-Sicherheit, Event-Vertraege, persistente Zustellung und Netzwerkgrenzen

---

## 1. Entscheidung

Visual Quality, Versandlabels und weitere privilegierte n8n-Automationen
werden erst auf produktive Schnittstellen geschaltet, nachdem eine
gemeinsame Foundation umgesetzt ist.

Die Foundation fuehrt ein:

1. authentifizierte, instanzgebundene Picker-Sessions,
2. beidseitig authentifizierte und gegen Replay geschuetzte
   FastAPI-n8n-Kommunikation,
3. einen versionierten Event- und Callback-Vertrag,
4. Odoo-basierte Integration-Jobs und eine persistente Outbox,
5. durchgaengiges Odoo-Instanzrouting,
6. interne Media- und Artifact-Schnittstellen,
7. getrennte Edge-, Core- und Automation-Netzgrenzen.

Odoo bleibt System of Record. Fachzustand, Integration-Job und
Outbox-Eintrag entstehen in derselben Odoo-Transaktion.

## 2. Verifizierter Ist-Zustand

### 2.1 n8n-Ingress ist nicht authentifiziert

FastAPI sendet optional `X-Webhook-Secret`, aber die n8n-Webhook-Nodes
pruefen ihn nicht. `N8N_WEBHOOK_SECRET` wird dem n8n-Container nicht
bereitgestellt. Gleichzeitig ist n8n direkt ueber Port `5678` und ueber
Caddy erreichbar.

Besonders kritisch ist `shortage-reported`: Ein beliebiger eingehender
Request kann Ziel-IDs liefern. Der Workflow fuegt beim Rueckruf selbst den
vertrauten Callback-Secret hinzu und kann damit einen privilegierten
Odoo-Nachschubtransfer ausloesen.

### 2.2 Callbacks verlieren die Odoo-Instanz

Der aktuelle Event-Envelope enthaelt keine Odoo-Instanz. Die Callback-Modelle
kennen ebenfalls keine Instanz. Privilegierte n8n-Callbacks verwenden
explizit den Odoo-Client `local`, auch wenn der urspruengliche PWA-Request
gegen eine andere Instanz lief.

Numerisch gleiche IDs aus verschiedenen Odoo-Datenbanken koennen dadurch
auf der falschen Instanz geaendert werden.

### 2.3 Picker-Identitaet ist keine Authentifizierung

`X-Picker-User-Id`, `X-Device-Id` und `X-Odoo-Instance` stammen vollstaendig
vom Client. FastAPI prueft bei der Picker-ID nur, ob ein interner
Odoo-Benutzer mit dieser ID aktiv ist. Alle Odoo-Schreibvorgaenge laufen
technisch ueber den konfigurierten Service-Account.

Die Header liefern damit Attribution, aber keinen Beweis, dass der Request
vom angegebenen Picker oder einem autorisierten Geraet stammt.

### 2.4 Events koennen verloren gehen

`N8NWebhookClient.fire_event()` versucht die Zustellung einmal. Bei Fehlern
wird lediglich ein degradierter Integrationsstatus zurueckgegeben. Es gibt
keine persistente Outbox, keine Lease, keinen Wiederanlauf und keine
Dead-Letter-Ablage.

Das ist fuer Versandlabels unzulaessig: Ein kurzzeitiger n8n-Ausfall nach
erfolgreichem Packabschluss darf das Label-Ereignis nicht dauerhaft
verlieren.

### 2.5 Die neuen Fachprozesse existieren noch nicht

- `quality-alert-created` sendet nur `photo_count`, keine Bildreferenzen.
- Die heutige Ollama-Auswertung ist text-only.
- Der AI-Shadow-Callback schreibt keine visuelle Bewertung nach Odoo.
- `pick-confirmed` folgt einem `button_validate`-Aufruf, prueft aber keinen
  expliziten Packabschluss.
- `batch-confirmed` enthaelt nur eine Batch-ID.
- Cluster-Packages sind wiederverwendbare Zielkartons, keine
  Versandparcels.

Deshalb werden bestehende Events nicht stillschweigend zu Label- oder
Bildanalyse-Triggern umgedeutet.

## 3. Ziele

- Ein Request kann seine Picker-ID, Rollen oder Odoo-Instanz nicht selbst
  autoritativ festlegen.
- Kein externer Request kann einen privilegierten n8n-Workflow ohne
  gueltige Credentials und Signatur starten.
- Ein Callback schreibt genau auf die Instanz, aus der sein Event stammt.
- Events ueberleben n8n-Ausfall, Backend-Restart und Netzwerkunterbrechung.
- Echte Retries erzeugen keine doppelten Odoo-Aenderungen, Analysen oder
  Versandlabels.
- Bild- und Labeldaten werden nicht als Base64 in Event-JSON transportiert.
- Die PWA ist der einzige LAN-Client der Anwendungs-API; interne Callback-
  und Adminschnittstellen bleiben intern.
- Alte v1-Workflows koennen waehrend eines kontrollierten Uebergangs
  weiterlaufen, aber neue Features verwenden ausschliesslich v2.

## 4. Nicht-Ziele

Diese Foundation implementiert nicht:

- das konkrete Vision-Modell oder dessen Bewertungs-Prompt,
- die fachliche Schadensklassifikation,
- einen konkreten Carrier,
- PDF-/ZPL-Layout und Druckersteuerung,
- den eigentlichen Packabschluss-Dialog,
- Voice-v2-NLU,
- den Odoo-19-Datenbank-Cutover,
- eine externe Cloud-Queue.

Diese Punkte erhalten eigene Specs. Die Foundation stellt nur die sicheren
und zuverlaessigen Vertraege bereit.

## 5. Zielarchitektur und Trust Boundaries

```text
Warehouse Browser
  -> HTTPS :443
  -> Caddy
  -> FastAPI public API
  -> authenticated picker session
  -> instance-bound Odoo client

Odoo business transaction
  -> integration job
  -> outbox record
  -> FastAPI outbox dispatcher
  -> authenticated internal n8n webhook
  -> local model or carrier adapter
  -> authenticated internal FastAPI callback
  -> same instance-bound Odoo client

n8n / Odoo / PostgreSQL / model services
  -> no direct Warehouse-LAN exposure
```

Trust Boundaries:

1. Der Browser ist nicht vertrauenswuerdig.
2. Caddy ist die einzige LAN-Edge.
3. FastAPI ist Policy- und API-Grenze.
4. Odoo besitzt fachlichen Zustand und Integrationspersistenz.
5. n8n ist ein privilegierter, aber nicht autoritativer Orchestrator.
6. Modell- und Carrier-Antworten sind untrusted input und werden validiert.

## 6. Picker-Session und Principal

### 6.1 Session-Erstellung

FastAPI stellt bereit:

```text
POST /api/auth/picker-session
GET  /api/auth/me
POST /api/auth/csrf
POST /api/auth/logout
```

Der Login-Request enthaelt:

```json
{
  "login": "picker.login",
  "password": "entered-once",
  "device_id": "browser-generated-uuid",
  "odoo_instance": "o19"
}
```

FastAPI:

1. validiert die Instanz gegen die Registry,
2. authentifiziert Login und Passwort direkt gegen diese Odoo-Instanz,
3. prueft, ob der Benutzer intern, aktiv und Mitglied einer erlaubten
   Picking- oder Supervisor-Gruppe ist,
4. speichert niemals das Passwort,
5. erzeugt ein zufaelliges 256-Bit-Session-Secret,
6. speichert nur den SHA-256-Hash des Tokens in Odoo,
7. setzt das Token als Cookie `pwr_session`.

Das Cookie-Token hat die Form:

```text
v1.<odoo-instance>.<256-bit-random-secret>
```

Der Instanzteil ist nur ein Routing-Hinweis. Er wird erst autoritativ,
nachdem der Hash des vollstaendigen Tokens in genau dieser Instanz gefunden,
die Session gueltig und die gebundene Instanz identisch ist. Eine
manipulierte Instanz fuehrt zu `401` und niemals zu einer Suche oder einem
Fallback ueber alle Datenbanken.

Cookie-Regeln:

```text
Secure
HttpOnly
SameSite=Strict
Path=/api
Max-Age=28800
```

Eine Session gilt maximal acht Stunden. Sie ist an genau eine
`picker_user_id`, eine `device_id`, eine `odoo_instance` und eine
Rollenmenge gebunden. Ein Instanzwechsel erfordert eine neue
Authentifizierung.

Die clientseitig erzeugte `device_id` bleibt ein Audit- und
Korrelationsmerkmal, kein Authentifizierungsfaktor. Eine echte
Geraetebindung benoetigt einen separaten Enrollment-Prozess und wird in
dieser Foundation nicht vorgetaeuscht.

Die Foundation definiert dafuer die Odoo-Gruppen:

```text
picking_assistant_integration.group_picker
picking_assistant_integration.group_supervisor
picking_assistant_integration.group_api_service
```

Nur die ersten beiden Gruppen duerfen Browser-Sessions erhalten.
`group_api_service` schuetzt alle neuen Integration-Methoden. Jede neue
oeffentliche `api_*`-Odoo-Methode prueft diese Gruppe explizit, auch wenn sie
intern `sudo()` verwendet.

Die Foundation migriert nicht saemtliche bestehenden direkten
`search_read`, `create`, `write` und `execute_kw`-Aufrufe auf eine neue
Odoo-Facade. Der Odoo-19-Cutover inventarisiert deshalb die heute
erforderlichen Fachrechte des FastAPI-Service-Accounts. Bestehende
Fachrechte bleiben zunaechst erhalten; neue Session-, Job-, Outbox- und
Receipt-Modelle sind ausschliesslich fuer `group_api_service` zugaenglich.
Eine vollstaendige Least-Privilege-Migration aller Legacy-RPCs ist ein
separates Hardening und keine versteckte Voraussetzung dieser Foundation.

### 6.2 CSRF-Schutz

Bei der Session-Erstellung erzeugt FastAPI zusaetzlich ein zufaelliges
CSRF-Token. Dessen Hash wird in der Session gespeichert; das Klartexttoken
wird einmalig in der Login-Antwort geliefert.

Die PWA haelt das CSRF-Token in `sessionStorage`, nicht in `localStorage`.
Nach einem Reload kann sie ueber das authentifizierte
`POST /api/auth/csrf` ein neu rotiertes Token beziehen. Dieser Endpunkt ist
als einziger authentifizierter POST vom bestehenden CSRF-Token ausgenommen,
prueft aber strikt die konfigurierte `Origin` und die Session. Eine fremde
Origin kann die Antwort wegen Same-Origin-Policy und `SameSite=Strict`
nicht auslesen.

Jede Browser-Mutation erfordert:

```text
X-CSRF-Token: <session-bound-token>
```

FastAPI prueft ausserdem `Origin` gegen die konfigurierte PWA-Origin.
Lesezugriffe benoetigen Session, aber keinen CSRF-Header.

### 6.3 Autoritativer Principal

Nach erfolgreicher Session-Pruefung erzeugt FastAPI einen Principal mit:

```json
{
  "picker_user_id": 7,
  "picker_name": "Mina Muster",
  "device_id": "device-42",
  "odoo_instance": "o19",
  "roles": ["picker"],
  "session_id": "server-side-id",
  "expires_at": "2026-07-23T20:00:00Z"
}
```

Nur dieser Principal bestimmt Benutzer, Geraet, Rollen und Instanz.
`X-Picker-User-Id`, `X-Device-Id` und `X-Odoo-Instance` werden im sicheren
Modus nicht als Autoritaetsquelle verwendet. Die im Principal gespeicherte
`device_id` bezeichnet nur das bei der Anmeldung angegebene Auditmerkmal.

Aktivstatus und Pickerrolle werden spaetestens alle fuenf Minuten gegen
Odoo revalidiert. Vor jeder Supervisor-Aktion erfolgt die Revalidierung
sofort. Deaktivierung oder Gruppenentzug widerruft alle betroffenen
Sessions vor der Fachoperation.

`mobile_header_grace_mode` wird standardmaessig `false`. Ein expliziter
Legacy-Modus ist nur fuer lokale Entwicklung erlaubt, erzeugt bei jedem
Request eine Warnung und darf in der kontrollierten Rollout-Konfiguration
nicht aktiv sein.

### 6.4 Login-Schutz

- Maximal fuenf fehlgeschlagene Loginversuche pro Loginname und Quell-IP
  innerhalb von 15 Minuten.
- Fehlerantworten unterscheiden nicht zwischen unbekanntem Benutzer und
  falschem Passwort.
- Logout widerruft die serverseitige Session sofort.
- Abgelaufene und widerrufene Sessions werden taeglich bereinigt.
- `/api/pickers` ist nicht mehr anonym erreichbar.

Fehlversuche und Sperrfenster werden in der Zielinstanz persistent
gespeichert; ein Backend-Restart setzt das Limit nicht zurueck.

FastAPI vertraut `X-Forwarded-For` nur, wenn der direkte Netzwerkpeer der
konfigurierte Caddy-Service ist. Fuer alle anderen Peers gilt die direkte
Quelladresse. Die persistierte IP-Kennung ist ein keyed HMAC mit einem
separaten Throttle-Key, kein nackter oder reversibler IP-Wert.

Credentialed CORS erlaubt nur die explizit konfigurierten HTTPS-PWA-Origins.
Wildcard-Origins sind im Sessionmodus ungueltig und verhindern den
Produktionsstart.

## 7. Odoo-Instanzbindung

Jede Session autorisiert genau eine Instanz aus der konfigurierten Registry.
Alle Request-Services erhalten den Odoo-Client aus dem verifizierten
Principal.

Fuer v2-Callbacks gilt:

- `odoo_instance` ist ein signiertes Pflichtfeld.
- Es gibt keinen stillen Fallback auf `local`.
- Ein neuer `get_callback_odoo_client()` erzeugt den Client ausschliesslich
  aus dem verifizierten Callback-Kontext.
- Callback-Idempotenz und Fachwrite verwenden denselben Client.
- Event-, Job-, Log- und Metrikschluessel werden mit der Instanz gescoped.

Ein Callback mit unbekannter oder nicht erlaubter Instanz wird vor jedem
Odoo-Zugriff abgelehnt.

## 8. Event-Envelope v2

Neue asynchrone Events verwenden:

```json
{
  "schema_version": "v2",
  "event_name": "quality.assessment.requested.v1",
  "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
  "correlation_id": "0b2f7909-4ad9-44c1-8527-e775fe6d4bec",
  "causation_id": null,
  "occurred_at": "2026-07-23T12:00:00Z",
  "source": {
    "service": "picking-assistant-api",
    "odoo_instance": "o19"
  },
  "actor": {
    "type": "picker",
    "user_id": 7,
    "name": "Mina Muster",
    "device_id": "device-42"
  },
  "aggregate": {
    "model": "quality.alert.custom",
    "id": 42,
    "revision": 1
  },
  "payload": {}
}
```

Semantik:

- `event_id` ist immutable und der Delivery-/Dedupe-Schluessel.
- `correlation_id` dient nur dem Tracing.
- `causation_id` verweist auf das ausloesende Event oder bleibt `null`.
- `schema_version` versioniert die Huelle.
- Die fachliche Payload-Version steht im `event_name`.
- `source.odoo_instance` ist fuer alle Odoo-bezogenen Events Pflicht.
- `aggregate.revision` verhindert, dass veraltete Ergebnisse unbemerkt
  neuere Fachzustaende ueberschreiben.

HTTP-Zustellungen verwenden:

```text
Idempotency-Key: <event_id>
Content-Type: application/json
```

Ein Retry verwendet denselben Event-Identifier und denselben
byte-identischen Body.

## 9. Erste v2-Events

### 9.1 `quality.assessment.requested.v1`

Die spaetere Visual-Quality-Spec definiert die fachliche Payload. Der
Foundation-Vertrag schreibt bereits vor:

- `job_id`
- Alert-ID und Referenz
- Picking-, Product-, Location- und Lot-Kontext
- Beschreibung und Prioritaet
- `media[]` mit `media_ref`, Dateiname, MIME-Type, Groesse und SHA-256
- keine Base64-Bilddaten

Ein text-only Fallback darf niemals behaupten, ein Foto analysiert zu haben.

### 9.2 `shipment.parcel.ready.v1`

Die spaetere Shipping-Spec definiert die fachliche Payload. Der
Foundation-Vertrag schreibt bereits vor:

- genau ein Event pro Versandparcel und `packing_revision`
- `job_id`, `parcel_id`, Picking- und Package-Referenz
- Empfaenger- und Absender-Snapshot
- Carrier und Service
- Gewicht, Masse und fachliche Referenzen
- keine Carrier-Credentials

Das Event darf erst nach einem expliziten Packabschluss und verifiziertem
Picking-Zustand `done` entstehen. `pick-confirmed` und `batch-confirmed`
werden nicht als Label-Trigger wiederverwendet.

## 10. Webhook-Authentifizierung und Replay-Schutz

### 10.1 FastAPI zu n8n

Jeder v2-Webhook verwendet:

```text
X-PWR-Key-Id: <active-key-id>
X-PWR-Timestamp: <unix-seconds>
X-PWR-Nonce: <uuid>
X-PWR-Signed-Method: POST
X-PWR-Signed-Target: /webhook/quality-assessment-v2
X-PWR-Delivery-Generation: 1
X-PWR-Signature: v1=<lowercase-hex-hmac>
```

Die Signatur ist HMAC-SHA256 ueber:

```text
SIGNED_METHOD + "\n"
+ SIGNED_TARGET + "\n"
+ DELIVERY_GENERATION + "\n"
+ TIMESTAMP + "\n"
+ NONCE + "\n"
+ SHA256(RAW_BODY)
```

`SIGNED_METHOD` und `SIGNED_TARGET` sind die unveraenderten Headerwerte. Bei
FastAPI-Empfaengern muessen sie exakt der tatsaechlichen HTTP-Methode und
dem unveraenderten Raw-Pfad entsprechen.

`DELIVERY_GENERATION` ist eine positive dezimale Ganzzahl ohne fuehrende
Nullen. Das Signature Gate uebergibt den verifizierten Wert zusammen mit
Event-ID, Fingerprint und Nonce an `accept_event()`. Bei Callbacks muss der
Header exakt `delivery_generation` im signierten Body entsprechen. Media-
und Artifact-Zugriffe muessen der aktuell geleasten Job-Generation
entsprechen.

Die in dieser Spec definierten v2-Webhook-, Callback-, Media- und
Artifact-Endpunkte verwenden keine Query-Parameter; alle Routingfelder
liegen im Pfad oder signierten Body. Ein nicht leerer Query-String wird mit
`400` abgelehnt.

Regeln:

- getrennte Secrets fuer FastAPI-zu-n8n und n8n-zu-FastAPI,
- mindestens 32 zufaellige Bytes je Secret,
- konstantzeitlicher Signaturvergleich,
- maximal 300 Sekunden Zeitabweichung,
- Nonce-Deduplizierung fuer mindestens zehn Minuten,
- aktiver und vorheriger Key duerfen waehrend Rotation parallel gelten,
- unbekannte Key-ID, alte Zeitstempel, wiederverwendete Nonces und
  Body-Manipulation werden fail-closed abgelehnt.

Der n8n-Webhook verwendet zusaetzlich native Header-Authentifizierung. Die
HMAC-Pruefung ist die erste fachliche Workflow-Stufe. Kein Workflow darf vor
diesem Gate externe Aktionen, Odoo-Callbacks oder Modellaufrufe ausfuehren.

Technische n8n-Vorgaben:

- Webhook-Nodes verwenden `authentication: headerAuth`.
- Webhook-Nodes setzen `options.rawBody: true`, damit die Signatur gegen die
  tatsaechlich empfangenen Bytes geprueft wird.
- Ein lokales, versioniertes Custom Node `PWR Signature Gate` prueft HMAC,
  Timestamp, Nonce, konfigurierte Route und Raw-Body.
- Da der normale n8n-Webhook-Node keinen originalen Raw-Request-Target an
  Folgeknoten liefert, besitzt jedes Gate unveraenderliche Parameter
  `expected_method` und `expected_target`. Es prueft, dass
  `X-PWR-Signed-Method` und `X-PWR-Signed-Target` exakt diesen Registry-
  Werten entsprechen. Der Webhook-Trigger selbst ist genau auf dieselbe
  Route registriert; ein nicht leeres Query-Objekt wird abgelehnt.
- Das Custom Node bezieht aktive und vorherige HMAC-Keys ueber einen
  eigenen n8n-Credential-Typ; kein Workflow-Code erhaelt den Klartextwert.
- HMAC-Keys und Credential-IDs werden nicht in Workflow-JSON gespeichert.
- Der native Header-Auth-Secret liegt im n8n Credential Store.
- `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` bleibt aktiv. Freier Environment-
  Zugriff aus Code-Nodes ist fuer den Signaturpfad nicht erforderlich.
- Nur Administratoren duerfen Credentials, Custom Nodes oder Workflows
  erstellen und bearbeiten.
- Native Header-Authentifizierung bleibt die erste n8n-Zugriffsschranke;
  HMAC, Timestamp, Event-ID und Replay-Receipt bilden die zweite.

Fuer ausgehende n8n-Requests gibt es ein zweites lokales Custom Node
`PWR Signed HTTP Request`. Dieses Node:

1. serialisiert den JSON-Body beziehungsweise uebernimmt Raw-Binaerdaten,
2. berechnet den Body-Hash aus exakt diesen Bytes,
3. erzeugt Timestamp, Nonce und Signatur,
4. sendet selbst Methode, Ziel, Header und exakt dieselben Bytes.

Kein normaler HTTP-Request-Node darf einen zuvor signierten Body erneut
serialisieren. Acceptance-Calls, Status-Callbacks, Media-Downloads und
Artifact-Uploads verwenden ausschliesslich dieses Node und einen eigenen
credential-gestuetzten n8n-zu-FastAPI-Key.

### 10.2 n8n zu FastAPI

Callbacks und interne Media-/Artifact-Requests verwenden denselben
Signaturmechanismus mit einem separaten Callback-Key.

Callbacks laufen direkt ueber das interne Automation-Netz und nicht ueber
den oeffentlichen Caddy-Pfad. Der bestehende statische
`X-N8N-Callback-Secret` darf waehrend der Migration als zusaetzliche
Kontrolle bestehen bleiben, ersetzt aber nicht HMAC und Replay-Schutz.

## 11. Callback-Envelope v2

Gemeinsame Struktur:

```json
{
  "schema_version": "v2",
  "callback_name": "quality.assessment.status.v1",
  "callback_id": "cbdc037f-8458-4be0-938a-4bc8242116af",
  "source_event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
  "correlation_id": "0b2f7909-4ad9-44c1-8527-e775fe6d4bec",
  "odoo_instance": "o19",
  "job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
  "sequence": 2,
  "attempt": 1,
  "delivery_generation": 1,
  "processing_lease_token": "opaque-lease-proof",
  "status": "succeeded",
  "execution_id": "n8n-workflow-execution",
  "occurred_at": "2026-07-23T12:00:04Z",
  "next_retry_at": null,
  "result": {},
  "error": null,
  "metrics": {}
}
```

Erste Callback-Namen:

- `quality.assessment.status.v1`
- `shipping.label.status.v1`

HTTP:

```text
Idempotency-Key: <callback_id>
```

Regeln:

- gleicher Key und gleicher Fingerprint: gespeicherte Antwort wiedergeben,
- gleicher Key mit anderem Fingerprint: `409 Conflict`,
- niedrigere Sequenz: `200` mit `ignored_stale`,
- gleiche Sequenz mit anderem Inhalt: `409 Conflict`,
- illegale Zustandsaenderung: `409 Conflict`,
- alte Delivery-Generation oder falscher Lease-Token: `409 Conflict`,
- unbekannter Job, Event oder Instanz: kein Odoo-Write.

Jeder statusaendernde Callback, einschliesslich `running`, traegt
`delivery_generation` und `processing_lease_token` als signierte
Pflichtfelder. Ein Prozess, der laenger als drei Minuten laeuft, sendet
spaetestens alle zwei Minuten einen `running`-Heartbeat mit neuer
`callback_id` und hoeherer `sequence`. Ein gueltiger Heartbeat verlaengert
die Processing-Lease auf fuenf Minuten. Heartbeats einer alten Generation
oder eines alten Lease-Tokens verlaengern nichts.

Transport- und Processing-Retry sind getrennt:

- Ein HTTP-Transport-Retry behaelt Event-/Callback-ID, Body,
  `Idempotency-Key`, Delivery-Generation, Attempt und Sequence
  byte-identisch. Nur Timestamp, Nonce und daraus berechnete Signatur sind
  neu.
- Ein neuer Processing-Versuch erhoeht `delivery_generation` und `attempt`,
  erhaelt ein neues Lease-Token und verwendet fuer alle neuen Statusupdates
  neue Callback-IDs. Die Job-Sequence laeuft monoton weiter.
- Bei einem neuen Processing-Versuch bleibt der Event-Body byte-identisch;
  nur der signierte Header `X-PWR-Delivery-Generation` wird erhoeht.
- `attempt` bezeichnet niemals einen HTTP-Transportversuch.
- Ein Callback-Transport-Retry darf seinen Body nicht aendern; andernfalls
  kollidiert dieselbe Callback-ID absichtlich mit einem anderen Fingerprint
  und wird `409`.

## 12. Persistente Job-Zustandsmaschine

Gemeinsame Zustaende:

```text
queued
  -> running
  -> succeeded
  -> review_required
  -> retry_scheduled
  -> failed
```

Erlaubte Uebergaenge:

```text
queued -> running
running -> succeeded
running -> review_required
running -> retry_scheduled
running -> failed
retry_scheduled -> running
```

`succeeded`, `review_required` und `failed` sind fuer denselben Job
terminal. Eine manuelle Wiederholung erzeugt einen neuen Job mit
`supersedes_job_id`.

`review_required` ist fuer niedrige Konfidenz, unzureichende Medien oder
widerspruechliche Ergebnisse verpflichtend. Es ist kein technischer Fehler
und wird nicht automatisch wiederholt.

## 13. Odoo-Modelle

Eine neue, klar abgegrenzte Integrationskomponente stellt bereit:

### 13.1 `picking.assistant.session`

- Session-ID
- Token-Hash
- CSRF-Hash
- Benutzer
- Geraete-ID
- Rollen
- Erstellungs-, Ablauf- und Widerrufszeit
- letzter erfolgreicher Zugriff

Die Instanz ist durch die jeweilige Odoo-Datenbank gegeben.

### 13.2 `picking.assistant.auth.throttle`

- normalisierter Loginname
- gehashte Quell-IP
- Fensterbeginn
- Fehlversuchsanzahl
- Sperrende

Die Daten werden ausschliesslich zur Login-Drosselung verwendet und nach
24 Stunden entfernt.

### 13.3 `picking.assistant.integration.job`

- `job_id`
- Job-Typ
- Aggregate-Modell, ID und Revision
- Zustand und Sequenz
- Delivery-Generation
- Processing-Lease und Lease-Ablauf
- `supersedes_job_id`
- Ergebnis-, Fehler- und Metrikdaten
- Erstellungs-, Start- und Abschlusszeit

### 13.4 `picking.assistant.outbox`

- `event_id`
- `job_id`
- Eventname und serialisierter v2-Envelope
- Payload-Fingerprint
- Zustand `pending`, `leased`, `delivered` oder `dead`
- Attempt-Anzahl
- `next_attempt_at`
- Lease-Owner und Lease-Ablauf
- letzter Fehler
- Zustellzeit

Unique-Constraint:

```text
event_id
```

### 13.5 `picking.assistant.callback.receipt`

- `callback_id`
- `source_event_id`
- `job_id`
- Sequenz
- Fingerprint
- gespeicherter HTTP-Status und Response-Body
- Empfangszeit

Unique-Constraints:

```text
callback_id
(job_id, sequence)
```

### 13.6 `picking.assistant.event.receipt`

- `event_id`
- Payload-Fingerprint
- Delivery-Generation
- Zustand `accepted`, `processing`, `completed` oder `retryable`
- Processing-Lease-Token und Lease-Ablauf
- erster und letzter Empfang

Unique-Constraint:

```text
event_id
```

### 13.7 `picking.assistant.webhook.nonce`

- Richtung `backend_to_n8n` oder `n8n_to_backend`
- Key-ID
- Nonce
- Empfangszeit und Ablaufzeit

Unique-Constraint:

```text
(direction, key_id, nonce)
```

Der n8n-Signature-Gate uebergibt den verifizierten Nonce an den internen
Acceptance-Call; FastAPI speichert ihn zusammen mit dem Event-Receipt
atomar in der Quellinstanz. Callback-Nonces werden vor dem Fachwrite in der
Zielinstanz reserviert. Abgelaufene Nonces werden nach zehn Minuten
bereinigt.

Fachzustandsaenderung, Job und Outbox-Eintrag muessen ueber eine
Odoo-Modellmethode in derselben Datenbanktransaktion entstehen.

Die Foundation stellt dafuer interne Enqueue- und Receipt-Helper bereit.
Visual Quality und Shipping liefern jeweils eine eigene Odoo-Modellmethode,
die Fachwrite, Job und Outbox innerhalb genau eines RPC-Aufrufs und damit
einer Odoo-Transaktion ausfuehrt. Der gespeicherte Envelope ist der exakte
UTF-8-Byteinhalt beziehungsweise dessen verlustfreie Textdarstellung; er
wird bei Retry nicht aus `fields.Json` neu serialisiert.

## 14. Outbox-Dispatcher

FastAPI betreibt einen Dispatcher pro konfigurierter Odoo-Instanz.

Ablauf:

1. Faellige Records werden ueber eine atomare Odoo-Methode geleased.
2. Der Dispatcher sendet den gespeicherten byte-identischen Envelope.
3. n8n antwortet nur nach erfolgreichem Auth- und Schema-Gate mit:

```json
{
  "accepted": true,
  "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32"
}
```

4. Nur eine passende Akzeptanz markiert den Record als `delivered`.
5. Timeout oder uneindeutiges Ergebnis fuehrt zu einem Retry mit derselben
   Event-ID.

Backoff:

```text
10 Sekunden
1 Minute
5 Minuten
30 Minuten
2 Stunden
6 Stunden
```

Nach zehn fehlgeschlagenen Versuchen wird das Event `dead`. Ein
Supervisor kann es nach Ursachenbehebung mit derselben Event-ID erneut
freigeben.

Nach dem sechsten Versuch bleibt der Abstand fuer die Versuche sieben bis
zehn jeweils bei sechs Stunden.

Die Transportannahme durch n8n beendet nur die Outbox-Zustellung, nicht den
Integration-Job. Ein Watchdog prueft jede Minute nicht-terminale Jobs.
Bleibt innerhalb von fuenf Minuten weder ein `running`- noch ein
terminaler Callback aus, setzt er denselben Job auf `retry_scheduled` und
gibt dasselbe Event mit derselben Event-ID erneut zur Zustellung frei.

Als erste Workflow-Stufe nach HMAC validiert n8n Event-ID, Fingerprint,
Nonce und Delivery-Generation ueber einen signierten internen
Acceptance-Call:

```text
accept_event(event_id, fingerprint, nonce, delivery_generation)
```

Die Odoo-Methode reserviert atomar den Nonce, sperrt oder erzeugt das
Event-Receipt, vergleicht Fingerprint und Generation und vergibt eine
Processing-Lease.

Ergebnis:

- erster gueltiger Versuch: `process=true` plus Lease-Token,
- identischer Replay mit aktiver Lease oder abgeschlossenem Receipt:
  `process=false`,
- anderer Fingerprint: `409`,
- abgelaufene Lease oder explizit `retry_scheduled`: neue Generation,
  `process=true` und neues Lease-Token.

Nur der Besitzer des Lease-Tokens darf den Job auf `running` oder einen
terminalen Zustand setzen. Damit startet ein einfacher HTTP-Replay weder
einen zweiten Modellaufruf noch einen zweiten Carrier-Auftrag.

Mehrere Backend-Instanzen duerfen parallel laufen. Die Odoo-Leases
verhindern doppelte aktive Zustellung und Verarbeitung. Der Watchdog
ueberfuehrt abgelaufene `processing`-Receipts atomar in `retryable`, den Job
von `running` nach `retry_scheduled` und die zugehoerige Outbox von
`delivered` nach `pending`.

Retention:

- zugestellte Outbox-Eintraege: 30 Tage,
- Dead-Letter-Eintraege: 90 Tage,
- Event-Receipts: 90 Tage nach terminalem Job,
- Callback-Receipts: 90 Tage,
- Integration-Jobs: 90 Tage nach terminalem Zustand,
- abgelaufene Sessions: 7 Tage nach Ablauf.

Event-Receipts bleiben mindestens so lange wie die zugehoerige Outbox oder
der Dead-Letter-Record erhalten. Ein Legal Hold am Job sperrt Job, Event-
und Callback-Auditdaten sowie zugehoerige Media/Artifacts
gegen automatische Loeschung. Ein taeglicher Odoo-Cron entfernt nur
Records ausserhalb dieser Fristen und ohne Hold.

## 15. Idempotenzregeln

- Jede fachlich zustandsaendernde PWA-Mutation benoetigt einen stabilen
  `Idempotency-Key`.
- Derselbe Benutzer-Intent behaelt bei Netzwerk-Retries denselben Key.
- Keys sind nach Instanz, Principal und Operation gescoped.
- Cluster Create, Confirm, Abort und Validate verwenden denselben
  serverseitigen Reservierungsflow wie normale Picking-Mutationen.
- Ein fehlender Key deaktiviert Idempotenz nicht still, sondern fuehrt bei
  diesen Fachmutationen zu `400 Bad Request`.
- Keys duerfen 1 bis 128 ASCII-Zeichen enthalten.
- Heartbeats verwenden keine unbegrenzt neuen persistenten Keys.
- Bestehende Idempotenzdaten erhalten einen Cleanup-Cron.
- Versandprovider muessen `job_id` als externe Idempotenzreferenz
  unterstuetzen oder vor Wiederholung per Referenz abfragbar sein.
- Nach einem uneindeutigen Provider-Ergebnis gibt es ohne Abfragefunktion
  keine automatische Label-Neuerzeugung.

Pflichtfaelle sind Picking-/Line-Confirm, Picking-Validate,
Cluster-Create/Confirm/Abort/Validate, Quality-Disposition,
Replenishment, Packabschluss sowie Label-Create/Reprint/Cancel.

Ausgenommen sind Login, CSRF-Rotation, Logout, reine Lesezugriffe,
Heartbeat, Voice-Recognition, Voice-Assist ohne Fachwrite und TTS. Loest
Voice-Assist nach bestaetigter Policy eine Fachmutation aus, gilt fuer diese
nachgelagerte Mutation wieder die Pflicht.

## 16. Media- und Artifact-Vertraege

Events und Callbacks enthalten keine grossen binaeren Payloads.

### 16.1 Media-Abruf

Visual-Quality-Events enthalten opaque `media_ref`-Werte. n8n ruft Medien
ueber eine intern signierte Schnittstelle ab:

```text
GET /api/internal/instances/{odoo_instance}/jobs/{job_id}/media/{media_ref}
```

FastAPI prueft:

- HMAC und Replay-Schutz,
- Job und Odoo-Instanz,
- Zuordnung von Medium, Alert und Job,
- MIME-Type,
- SHA-256,
- Groessenlimit.

Erlaubt sind JPEG, PNG und WebP bis 15 MiB pro Datei.

Die Pruefung verwendet nicht nur den angegebenen MIME-Type:

- Magic Bytes und Decoder muessen das Format bestaetigen.
- Dekodierte Bilder duerfen hoechstens 24 Megapixel besitzen.
- Mehrbild-, animierte und inkonsistente Polyglot-Dateien werden abgelehnt.
- Der gespeicherte Dateiname wird serverseitig aus Job und Attachment-ID
  erzeugt; ein Originalname wird nur sanitisiert als Metadatum gehalten.

### 16.2 Artifact-Upload

Label-Workflows speichern PDF oder ZPL ueber:

```text
POST /api/internal/instances/{odoo_instance}/jobs/{job_id}/events/{source_event_id}/artifacts/{artifact_kind}
```

Der Request-Body besteht aus den unveraenderten PDF- oder ZPL-Bytes, nicht
aus Multipart-Formdata. Instanz, Job, Source-Event und Artifact-Typ liegen
im signierten Pfad. `PWR Signed HTTP Request` hasht, signiert und sendet
exakt diese Raw-Bytes. FastAPI speichert das Artifact als Odoo-Attachment
und gibt eine opaque Artifact-Referenz zurueck. Erst danach meldet der
Success-Callback diese Referenz.

Erlaubt sind PDF und ZPL bis 10 MiB pro Artifact.

Vor Speicherung oder Druck:

- PDF muss geparst werden, darf hoechstens 20 Seiten besitzen und weder
  JavaScript, Launch-Actions, eingebettete Dateien noch Verschluesselung
  enthalten.
- ZPL muss als kontrollierter Text dekodierbar sein. Tilde-Kommandos,
  Datei-/Netzwerkzugriffe, Firmware-, Speicher-, Wireless- und
  Druckerkonfigurationskommandos sind verboten.
- Die Shipping-Spec definiert eine positive Allowlist der tatsaechlich
  benoetigten Layout-, Text-, Barcode- und QR-Kommandos.
- Das System erzeugt den Attachment-Dateinamen aus `job_id` und Format.

### 16.3 Zugriff und Retention

Standardfristen:

- Quality-Originalbilder: 30 Tage nach geschlossenem Quality Alert,
- `review_required`-Bilder: bis Review-Abschluss plus 30 Tage,
- normalisierte Quality-Findings und Entscheidungs-Audit: 180 Tage,
- Label-Artifact und Empfaenger-/Absender-Snapshot: 90 Tage nach Versand
  oder Storno,
- erfolgreiche n8n-Ausfuehrungsdaten: 14 Tage,
- fehlgeschlagene n8n-Ausfuehrungsdaten: 30 Tage.

Ein expliziter Odoo-Legal-Hold verhindert die automatische Loeschung des
zugehoerigen Jobs und seiner Medien. Picker sehen nur Medien und Artifacts
ihrer autorisierten Vorgangsansicht. Quality Reviewer sehen
Quality-Medien, Shipping-Rollen sehen Labels; n8n erhaelt nur jobgebundene
Kurzzeitzugriffe. Logs enthalten weder Bilder noch Labelinhalt oder
vollstaendige Adress-Snapshots.

## 17. Netzwerkdesign

Compose trennt:

### 17.1 Edge-Netz

- Caddy
- PWA-Service
- FastAPI

Nur Caddy publiziert Warehouse-LAN-Ports. HTTP wird auf HTTPS umgeleitet.

### 17.2 Core-Netz

- FastAPI
- Odoo
- PostgreSQL

Odoo und PostgreSQL besitzen keine Warehouse-LAN-Bindings.

### 17.3 Automation-Netz

- FastAPI
- n8n
- PostgreSQL
- Vision-/LLM-Dienste
- Whisper und Piper

n8n und Modellserver besitzen keine Warehouse-LAN-Bindings.

PostgreSQL darf beiden internen Netzen angehoeren, publiziert aber keinen
Host-Port. Odoo und n8n verwenden getrennte Datenbanken, Benutzer und
Passwoerter. Der n8n-Benutzer besitzt keine Odoo-Rollen oder Rechte.
`infrastructure/scripts/init-n8n-db.sql` gilt nur fuer frische Volumes.

Fuer das vorhandene `pg_data` gibt es ein separates einmaliges,
idempotentes Migrationsskript mit Runbook. Es:

1. sichert Rollen, Grants und n8n-Datenbank,
2. legt den dedizierten n8n-Login an,
3. uebertraegt Ownership beziehungsweise Grants fuer n8n-Schema, Tabellen
   und Sequenzen,
4. prueft n8n-Start und Schreibzugriff mit dem neuen Login,
5. entzieht erst danach der alten Odoo-Rolle den n8n-Zugriff.

Das Runbook enthaelt einen Rueckweg, der die vorherigen Grants aus dem
gesicherten Rollenreport wiederherstellt.

Adminzugriff:

- n8n- und Odoo-Adminports nur auf `127.0.0.1`,
- alternativ spaeter ueber einen getrennten TLS-Adminhost mit
  Zugriffskontrolle,
- n8n Public API und Swagger nicht ueber das Warehouse-LAN,
- Odoo-Datenbankliste nicht oeffentlich.

Caddy:

- blockiert `/api/internal/*` vor dem allgemeinen `/api/*`-Proxy,
- publiziert keine n8n-Webhook- oder Editorpfade,
- publiziert keinen direkten Odoo-HTTP-Link,
- erlaubt als Anwendungszugang nur PWA und oeffentliche FastAPI-Routen.

Pre-Auth-Allowlist:

```text
POST /api/auth/picker-session
GET  /api/auth/instances
GET  /api/health/live
```

`/api/auth/instances` liefert nur stabilen Instanzschluessel und
Anzeigenamen, keine URL, Datenbank oder Credentials. Alle anderen
Anwendungsrouten verlangen eine Session oder einen verifizierten internen
Service-Principal.

Im Produktionsprofil liefern folgende Oberflaechen `404`:

```text
/docs
/redoc
/openapi.json
/api/docs
/api/redoc
/api/openapi.json
/api/internal/*
/api/obsidian/*
/api/demo/*
```

Readiness, Metriken und interne Diagnostik sind nur im internen Netz
erreichbar.

FastAPI setzt im Produktionsprofil `docs_url=None`, `redoc_url=None` und
`openapi_url=None`; die Caddy-Denylist ist zusaetzliche Defense in Depth.

Die aeussere Firewall beziehungsweise das Warehouse-VLAN erlaubt Clients
nur HTTPS-Port `443` zum Host.

TLS-Live-Gate:

- Zertifikat enthaelt den verwendeten LAN-DNS-Namen und die konfigurierte
  LAN-IP als Subject Alternative Names.
- Die lokale CA aus `infrastructure/certs/README.md` und `docs/SETUP.md`
  ist auf jedem iOS-/Android-Geraet installiert und als vertrauenswuerdig
  aktiviert.
- Kamera, Mikrofon, Secure-Cookie und PWA-Installation werden auf einem
  echten Mobilgeraet ueber den Produktionsnamen getestet.
- Ein automatischer Check warnt 30 Tage vor Zertifikatsablauf.
- Die dokumentierte Rotation ersetzt Zertifikat und Key atomar und prueft
  danach Browser, Caddy und mobile CA-Trust erneut.

Im Produktionsprofil startet FastAPI nicht, wenn HMAC-, native
Header-Auth-, Callback- oder Odoo-Service-Credentials fehlen,
symmetrische Secrets weniger als 32 zufaellige Bytes besitzen oder
`mobile_header_grace_mode=true` ist.

## 18. Workflow- und Contract-Registry

Eine zentrale Registry definiert:

- erlaubte v1- und v2-Workflows,
- lokale Workflow-Dateien,
- Eventnamen,
- Webhook-Pfade,
- Callback-Pfade,
- erforderliche Authentifizierung,
- erlaubte Zielhosts,
- Aktivierungsreihenfolge.

`import-workflows.sh` und `verify-workflows.py` lesen beziehungsweise
validieren dieselbe Registry. Neue Workflows werden nicht mehr an mehreren
Stellen als unabhaengige Hardcode-Listen gepflegt.

Credential-Bootstrap:

- Die Registry referenziert logische Credential-Namen, keine
  installationsabhaengigen IDs.
- Ein lokales Provisioning-Skript erzeugt beziehungsweise rotiert native
  Header-Auth-, `PWR Signature Gate`- und
  `PWR Signed HTTP Request`-Credentials ueber die containerinterne
  n8n-CLI.
- Secrets kommen nur aus geschuetzten Secret-Dateien oder dem
  Prozess-Environment und werden weder in Argumentlisten, Logs noch
  Workflow-JSON geschrieben.
- Der Importer liest die realen Credential-IDs vor dem Import aus n8n,
  injiziert sie nur in eine temporaere Workflow-Kopie und loescht diese
  danach.
- Fehlende oder mehrdeutige logische Credentials verhindern Import und
  Aktivierung.
- Rotation provisioniert zuerst den neuen Key, behaelt den vorherigen Key
  fuer das definierte Uebergangsfenster und entfernt ihn erst nach einem
  bestandenen Signatur-Smoke.

Der Verifier muss fehlschlagen, wenn:

- ein Webhook keine native Authentifizierung besitzt,
- das HMAC-Gate fehlt oder nicht erster fachlicher Schritt ist,
- ein Callback keine Signatur- und Idempotenzheader setzt,
- ein interner Callback-Pfad nicht erlaubt ist,
- ein Workflow direkt Odoo oder einen nicht erlaubten Host anspricht,
- ein v2-Event keine Instanz oder Event-ID enthaelt,
- ein Quality-Workflow nur `photo_count` als angebliche Bildanalyse nutzt.

## 19. Rueckwaertskompatibilitaet und Rollout

Bestehende v1-Events bleiben waehrend der Migration unveraendert. Neue
Visual-Quality- und Shipping-Features verwenden ausschliesslich v2.

Die produktive Foundation ist Odoo-19-only. Der bisherige
Odoo-18-Defaultpfad bleibt bis zu seinem Cutover auf Legacy v1 und erhaelt
keine Kopie des neuen Add-ons unter `odoo/addons18`. Der Odoo-19-Cutover und
sein Runtime-/Modell-Faktengate werden vor dem Foundation-Merge integriert.
Foundation rebased danach auf diesen Stand und uebernimmt Compose sowie die
betroffenen Odoo-Core-Dateien exklusiv.

Reihenfolge:

1. Odoo-19-Cutover-Branch integrieren und Runtime-Faktengate bestehen.
2. Dedizierte n8n-Datenbankrolle migrieren.
3. Neue Odoo-19-Modelle und Backend-Schemas mit deaktiviertem Dispatcher
   deployen.
4. Session- und Callback-Tests gegen zwei getrennte Odoo-19-Datenbanken
   ausfuehren.
5. Header-Auth- und HMAC-Credentials fuer beide Richtungen provisionieren.
6. v2-Workflows inaktiv importieren.
7. Workflow-Authentifizierung und Validator im inaktiven Zustand pruefen.
8. Dispatcher nur fuer einen Testeventtyp aktivieren.
9. Zustellung, Replay, falsche Instanz, Restart und Dead-Letter pruefen.
10. PWA auf Session und CSRF umstellen.
11. Legacy-Header-Modus deaktivieren.
12. Caddy- und Host-Port-Flaeche schliessen.
13. Erst danach Visual Quality und Shipping einzeln aktivieren.

Es gibt keinen Big-Bang-Wechsel aller vorhandenen Workflows.

## 20. Dateiverantwortung

Foundation besitzt:

- `backend/app/config.py`
- `backend/app/dependencies.py`
- `backend/app/main.py`
- `backend/tests/conftest.py` und gemeinsame Integrationsfixtures
- neue Auth-, Principal-, HMAC-, Event- und Dispatcher-Module
- gemeinsame n8n-Schemas
- `backend/app/services/n8n_webhook.py`
- die Legacy-Callback-Migration in `backend/app/routers/n8n_internal.py`
- neues Add-on `odoo/addons/picking_assistant_integration/**`
- nach dem Odoo-19-Handoff die Odoo-19-Idempotenzlogik in
  `odoo/addons/picking_assistant_core/**`
- lokales Custom Node und Credential-Typ unter `n8n/custom-nodes/**`
- `docker-compose.yml`
- `.env.example`
- `infrastructure/caddy/Caddyfile`
- `infrastructure/scripts/init-n8n-db.sql`
- neues n8n-Credential-Provisioning-Skript
- `infrastructure/scripts/import-workflows.sh`
- `infrastructure/scripts/verify-workflows.py`

Visual Quality besitzt spaeter:

- Quality-Payload und Result-Schemas,
- sicheren Attachment-Kontext,
- Vision-Adapter und Quality-Workflow,
- neuen Router `backend/app/routers/n8n_quality.py`,
- `backend/app/models/quality.py`,
- neues Add-on `odoo/addons/picking_assistant_visual_quality/**`.

Shipping besitzt spaeter:

- Parcel- und Packing-Modell,
- Carrier-Adapter und Label-Workflow,
- Artifact-Fachlogik,
- neuen Router `backend/app/routers/n8n_shipping.py`,
- neues Add-on `odoo/addons/picking_assistant_shipping/**`.

`pwa/js/api.js` wird fuer die Session-Umstellung einmalig im
Foundation-Integrationsschritt geaendert. Die PWA-Spur startet danach von
diesem Integrationsstand und besitzt die Datei fuer alle weiteren
Mobile-/Offline-Aenderungen.

Der Odoo-19-Workstream landet zuerst und uebergibt danach Compose und
Odoo-Core-Dateien an Foundation. Visual Quality und Shipping starten ihre
Odoo-Add-ons erst von diesem integrierten Stand und liefern
Router-Registrierungs- sowie Workflow-Registry-Deltas an Foundation.

## 21. Fehlerverhalten

| Situation | Verhalten |
| --- | --- |
| Keine oder ungueltige Session | `401`, kein Odoo-Zugriff |
| Fehlende Rolle oder falsche Instanz | `403`, kein Odoo-Zugriff |
| Fehlendes CSRF bei Browser-Mutation | `403` |
| Fehlender Idempotency-Key | `400` |
| Unbekannte Event-/Callback-Version | `422` |
| Ungueltige HMAC oder Header-Auth | `401` |
| Abgelaufener Timestamp oder Replay-Nonce | `409` |
| Gleicher Key, anderer Fingerprint | `409` |
| Veraltete Callback-Sequenz | `200 ignored_stale` |
| n8n nicht erreichbar | Event bleibt in Outbox, Backoff |
| Odoo nicht erreichbar | Lease wird nicht bestaetigt, spaeterer Retry |
| Unbekannte Odoo-Instanz im Callback | `403`, kein Fallback auf `local` |
| Unklares Provider-Ergebnis | Job `review_required` oder kontrollierte Referenzabfrage |
| Maximalversuche erreicht | Outbox `dead`, Supervisor-Aktion erforderlich |

Fehlermeldungen und Logs duerfen keine Sessiontokens, Passwoerter,
HMAC-Secrets, Processing-Lease-Tokens, Carrier-Credentials oder binaere
Inhalte enthalten.

## 22. Teststrategie

### 22.1 Auth-Tests

- frei gesetzte Picker-, Device- und Instance-Header reichen nicht aus,
- gueltige Odoo-Anmeldung erzeugt eine instanzgebundene Session,
- falsches Passwort und unbekannter Benutzer liefern dieselbe Antwort,
- abgelaufene, widerrufene und fremde Sessions werden abgelehnt,
- CSRF- und Origin-Pruefung blockieren Mutationen,
- Picker darf keine Supervisor-Aktion ausfuehren.

### 22.2 HMAC- und Workflow-Tests

- bekannte Signatur-Testvektoren fuer beide Richtungen,
- manipulierte Bodies, Pfade, Zeitstempel und Nonces werden abgelehnt,
- Replay innerhalb und ausserhalb des Zeitfensters,
- Rotation mit aktivem und vorherigem Key,
- `PWR Signed HTTP Request` sendet fuer JSON und Raw-Binaerdaten exakt die
  Bytes, die es gehasht hat,
- Signature Gate lehnt falsche erwartete Route, Methode oder nicht leere
  Query ab,
- Workflow-Verifier lehnt unauthentifizierte Webhooks ab,
- kein fachlicher Node laeuft vor dem Auth-Gate.

### 22.3 Instanztests

- zwei laufende Odoo-19-Testdatenbanken besitzen absichtlich gleiche
  numerische IDs,
- Event aus Instanz A schreibt nur nach Instanz A,
- numerisch gleiche IDs in Instanz B bleiben unveraendert,
- Idempotenz und Fachwrite nutzen nachweislich denselben Client,
- unbekannte Instanz faellt nicht auf `local` zurueck.

### 22.4 Outbox-Tests

- Fachwrite und Outbox entstehen atomar,
- n8n-Ausfall behaelt das Event,
- Backend-Restart setzt offene Zustellung fort,
- abgelaufene Lease wird erneut verarbeitet,
- parallele Dispatcher liefern ein Event fachlich einmal,
- gleicher Event-Body wird bei Retry wiederverwendet,
- Dead-Letter und manuelle Freigabe funktionieren,
- Retention entfernt nur abgelaufene Records.

Diese Gates laufen nicht nur gegen Odoo-Mocks. Odoo-19-Addon-Tests pruefen
Transaktionsrollback und Constraints; ein Live-Test mit zwei parallelen
RPC-Verbindungen prueft Lease- und Acceptance-Rennen. Ein Kill/Restart-Test
beendet Backend und n8n zwischen Annahme und Callback und weist die
Fortsetzung ohne doppelte Fachwirkung nach.

### 22.5 Callback-Tests

- identischer Callback liefert gespeicherte Antwort,
- gleicher Key mit anderem Body liefert `409`,
- veraltete Sequenz wird ignoriert,
- alter Lease-Token und alte Delivery-Generation werden nach Retry
  abgelehnt,
- `running`-Heartbeat verlaengert nur die aktuelle Lease,
- Callback-Transport-Retry veraendert Attempt, Sequence und Body nicht,
- terminaler Job wird nicht wieder geoeffnet,
- Media und Artifacts sind job- und instanzgebunden.

### 22.6 Netzwerk-Smokes

- eine Probe von einem zweiten Host im Warehouse-Netz erreicht nur HTTPS
  `443`,
- n8n, Odoo, PostgreSQL und Modellports sind aus dem LAN nicht erreichbar,
- `/api/internal/*` ist ueber Caddy blockiert,
- Docs, OpenAPI, Obsidian und Demo-Routen liefern im Produktionsprofil
  `404`,
- interne Containerkommunikation funktioniert weiterhin,
- n8n verbindet sich mit eigener Datenbankrolle und kann keine Odoo-
  Datenbankobjekte lesen,
- das Bestandsdaten-Migrationsrunbook und sein Grant-Rollback laufen gegen
  eine Kopie des vorhandenen Volumes,
- mobiles Endgeraet vertraut Zertifikat und CA, und Secure-Cookie, Kamera,
  Mikrofon sowie PWA-Installation funktionieren,
- Neustart von Backend und n8n verliert keine offenen Events.

### 22.7 Live-n8n- und Binaerdaten-Gates

- echter n8n-Webhook prueft `headerAuth`, `rawBody`, HMAC, Query-Bindung und
  Replay-Receipt,
- echter n8n-Callback und Artifact-Upload verwenden den credential-
  gestuetzten `PWR Signed HTTP Request` ohne nachtraegliche
  Reserialisierung,
- Aktivierung wird ohne alle benoetigten Credentials verweigert,
- Eventannahme und Callback laufen gegen eine echte n8n-Ausfuehrung,
- Dekompressionsbomben, Polyglot-Bilder und falsche Magic Bytes werden
  abgelehnt,
- PDF mit JavaScript oder Embedded File und ZPL mit verbotenem
  Konfigurationskommando werden abgelehnt.

## 23. Akzeptanzkriterien

Die Foundation ist abgeschlossen, wenn:

- alle fachlich zustandsaendernden Browser-Mutationen einen
  authentifizierten Principal, CSRF und stabilen Idempotency-Key erfordern,
- Client-Header keine Picker- oder Instanzautoritaet mehr besitzen und die
  Device-ID nur als Auditmerkmal gilt,
- alle neuen n8n-Webhooks native Authentifizierung, HMAC und Replay-Schutz
  pruefen,
- jeder v2-Event und Callback die Odoo-Instanz signiert traegt,
- Callback-Idempotenz und Fachwrite garantiert dieselbe Instanz verwenden,
- Fachwrite, Integration-Job und Outbox atomar in Odoo entstehen,
- Eventzustellung einen n8n-Ausfall und Backend-Restart ueberlebt,
- Visual-Quality-Medien und Label-Artefakte ohne Base64-Eventpayloads
  uebertragen werden,
- bestehende `pick-confirmed`- und `batch-confirmed`-Events nicht als
  Packabschluss missbraucht werden,
- der Workflow-Verifier unauthentifizierte oder falsch geroutete Workflows
  blockiert,
- Caddy keine internen API-, n8n- oder direkten Odoo-Pfade im
  Warehouse-LAN veroeffentlicht,
- n8n eine eigene Datenbankrolle verwendet,
- Foundation auf dem verifizierten Odoo-19-Profil laeuft und Odoo 18 bis
  zum Cutover ausschliesslich Legacy v1 verwendet,
- alle Auth-, HMAC-, Instanz-, Outbox-, Callback- und Netzwerk-Gates
  reproduzierbar bestanden sind.
