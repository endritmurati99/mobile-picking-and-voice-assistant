# Design: Odoo-Instanz-Switch (Multi-Mandant)

- **Datum:** 2026-06-27
- **Status:** Approved (Design), bereit für Implementierungsplan
- **Komponente:** Backend (FastAPI), kleiner additiver PWA-Eingriff
- **Branch:** `feat/odoo-switch`
- **Verwandt:** `Projekt-Wiki/05 - Future Functions/Odoo-Instanz-Switching (Multi-Mandant).md`

## 1. Kontext & Motivation

Heute ist genau **eine** Odoo-Instanz fest verdrahtet: `ODOO_URL`, `ODOO_DB`, `ODOO_USER`,
`ODOO_API_KEY`, `ODOO_PASSWORD` liegen in `.env` und werden in `backend/app/config.py` als
Einzelfelder geladen (`config.py:7-11`). Der `OdooClient` liest diese global beim Erzeugen
(`odoo_client.py:21-22`), und `get_odoo_client()` ist ein prozessweites `@lru_cache`-Singleton
(`dependencies.py:20-22`).

**Ziel (Kolloquium-Demo):** Sichtbar machen, dass das Backend austauschbar ist — **dieselbe PWA**
arbeitet je nach Auswahl gegen die lokale PoC-Instanz (`masterfischer`) **oder** eine andere
Odoo-Instanz (z. B. LogILab) — **ohne Neustart, ohne Re-Deploy**. Demonstriert Mandantenfähigkeit.

## 2. Abgenommene Entscheidungen

1. **Umfang = Sync-Pfad.** Reads + direkte Writes (Pickings, Bestand, Bilder, Claim/Heartbeat/
   Release, Confirm-Line, Cluster/Batch inkl. Karton, Quality-Alert-**Anlage**) folgen der
   gewählten Instanz. Der **asynchrone n8n-Pfad bleibt auf `local`** und wird **nicht**
   instanz-bewusst gemacht (dokumentierte PoC-Grenze, siehe §8).
2. **Trigger = kleiner PWA-Umschalter.** Minimaler Instanz-Selektor in der PWA, der den Header
   `X-Odoo-Instance` setzt; Default = `local`. Backend akzeptiert zusätzlich `?instance=`.

## 3. Architektur

### 3.1 Ist-Zustand (verifiziert)

| Element | Datei:Zeile | Verhalten heute |
|---|---|---|
| Settings-Singleton | `config.py:36` | `settings = Settings()`, modulweit; `odoo_*`-Felder `config.py:7-11` |
| OdooClient-Konstruktor | `odoo_client.py:20-32` | nimmt **0 Parameter**, liest `settings.odoo_url/db` direkt; eigener httpx-Pool |
| Auth/uid-Cache | `odoo_client.py:23-24,57-68` | `_uid`/`_secret` als Instanz-State, lazy |
| Client-Factory | `dependencies.py:20-22` | `@lru_cache` → **ein** prozessweiter Client |
| Service-Factories | `dependencies.py:30-39` | pro Request neu, erhalten aber das Client-Singleton |
| Per-Request-Header-Hook | `dependencies.py:62-77` | `get_write_request_context` liest `X-Picker-User-Id`, `X-Device-Id`, `Idempotency-Key` |
| Direkte Client-Nutzer | `pickings.py:108`, `voice.py:345`, `quality.py:173` | `Depends(get_odoo_client)` |
| n8n-Callback-Nutzer | `n8n_internal.py:414,550,687,854,1004` | `Depends(get_odoo_client)` (sollen auf `local` bleiben) |
| n8n-Envelope | `n8n_webhook.py:270-293` | **kein** Instanz-Identifier |
| App-Lifecycle | `main.py:7-30` | keine lifespan/shutdown-Hooks |
| Backend-Env | `docker-compose.yml:73-78` | `ODOO_URL/DB/USER/API_KEY/PASSWORD` |

### 3.2 Soll-Zustand

```
PWA (Dropdown, localStorage)
  └─ api.js: hängt X-Odoo-Instance an JEDEN Request (eine Stelle in request())
        └─ FastAPI
             ├─ resolve_instance(request) → Profilname (default "local", unbekannt → 400)
             ├─ get_request_odoo_client → Per-Profil-Cache[name] → OdooClient(profile)   ← nutzerseitig
             └─ get_default_odoo_client → Per-Profil-Cache["local"]                       ← n8n-Callbacks
        └─ Odoo-Instanz (jeweils System of Record, getrennt)
```

## 4. Komponenten

### 4.1 Profil-Register (`config.py`)
- Neuer Typ `OdooProfile` (dataclass/pydantic): `name`, `display_name`, `url`, `db`, `user`,
  `api_key`, `password`.
- Das **`local`**-Profil wird aus den bestehenden `odoo_*`-Feldern gebildet → kein bestehender
  Wert/Pfad ändert sich (volle Rückwärtskompatibilität).
- Zusätzliche Profile aus **einem** neuen Env-Var `ODOO_INSTANCES_JSON` (JSON-Objekt
  `{name: {url, db, user, api_key?, password?, display_name?}}`), in `config.py` zu
  `settings.odoo_instances: dict[str, OdooProfile]` geparst.
- Helfer `get_instance_registry() -> dict[str, OdooProfile]` (immer inkl. `local`).
- **Eindeutigkeit `local`:** Das `local`-Profil kommt **immer** aus den `odoo_*`-Feldern; ein
  evtl. `local`-Key in `ODOO_INSTANCES_JSON` wird **ignoriert** (kanonische Quelle = `odoo_*`).
- **`display_name`:** optional je Profil; fehlt er, fällt er auf den `name` zurück. Für `local`
  Default-Anzeigename „Lokal".
- Robustheit: ungültiges JSON → klare Startup-Fehlermeldung (fail-fast), `local` immer vorhanden.
- Secrets bleiben in `.env` (gitignored). `docker-compose.yml` reicht `ODOO_INSTANCES_JSON` additiv durch.

### 4.2 `OdooClient` (`odoo_client.py`)
- Konstruktor wird zu `OdooClient(profile: OdooProfile)` und liest url/db/user/secret aus dem
  Profil statt aus `settings`. uid/secret-Cache + httpx-Pool bleiben **pro Instanz** erhalten.
- Rückwärtskompatibilität intern: Default-Erzeugung nutzt das `local`-Profil. Kein Verhaltens-
  unterschied für bestehende Aufrufe. (`authenticate`/`execute_kw` unverändert.)

### 4.3 Dependency-Injection (`dependencies.py`)
- **Per-Profil-Cache** statt `@lru_cache`-Singleton: modulglobales `dict[str, OdooClient]`,
  lazy via `_get_cached_client(name)`.
- `resolve_instance(x_odoo_instance: Header|None, instance: Query|None) -> str`:
  normalisiert (`strip().lower()`), default `"local"`, prüft gegen Register → **unbekannt = HTTP 400**
  (kein stiller Fallback).
- `get_request_odoo_client(instance=Depends(resolve_instance)) -> OdooClient` — nutzerseitig.
- `get_default_odoo_client() -> OdooClient` — fest `local`, für n8n-Callbacks.
- Service-Factories (`get_picking_service`, `get_cluster_service`, `get_mobile_workflow_service`)
  beziehen `get_request_odoo_client`.
- Direkte Nutzer in `pickings.py`/`voice.py`/`quality.py` → `get_request_odoo_client`.
- n8n-Callback-Endpunkte in `n8n_internal.py` → `get_default_odoo_client`.

> **Wichtig (FastAPI-Fallstrick):** `_get_cached_client(name)` ist eine **reine** Funktion (keine
> Dependency), damit der Instanz-Parameter nicht versehentlich als Query-Param auf jedem Endpunkt
> auftaucht. Nur `resolve_instance`/`get_request_odoo_client`/`get_default_odoo_client` sind Depends.

### 4.4 API (`routers/instances.py`, neu; `main.py` include)
- `GET /api/instances` → `[{ "name": "...", "display_name": "..." }]` — **nur** Name + Anzeigename,
  **keine** URL/DB/Secrets.
- Selektor projektweit: Header `X-Odoo-Instance` (bevorzugt) oder `?instance=`.
- Unbekanntes Profil → `400 {"detail": "Unbekannte Odoo-Instanz: <name>"}`.

### 4.5 PWA-Umschalter (`pwa/js/api.js`, `pwa/js/app.js`, `pwa/index.html`, `pwa/css/app.css`)
- Kleines Dropdown (Kopfzeile), befüllt aus `GET /api/instances`, Default „Lokal".
- Auswahl in `localStorage` (`odoo_instance`); `api.js` setzt den Header `X-Odoo-Instance` zentral
  in `request(...)` für **alle** Calls (analog `getDeviceId`).
- Invariante bleibt: PWA spricht nur mit FastAPI. Additiv, Touch unberührt.

## 5. Datenfluss (Beispiel: Picking-Liste auf `logilab`)

1. PWA-Dropdown = „LogILab" → `localStorage.odoo_instance = "logilab"`.
2. `GET /api/pickings` mit Header `X-Odoo-Instance: logilab` (+ bestehende Picker-Header).
3. `resolve_instance` → `"logilab"` (im Register, sonst 400).
4. `get_request_odoo_client` → `_get_cached_client("logilab")` → `OdooClient(logilab-Profil)`.
5. `PickingService` nutzt diesen Client → JSON-RPC an die LogILab-Odoo-Instanz.
6. Antwort an PWA; Telemetrie loggt `odoo_instance=logilab`.

## 6. Fehlerbehandlung
- Unbekanntes Profil → **400**, kein Fallback auf `local`.
- Fehlende `ODOO_INSTANCES_JSON` → nur `local` verfügbar (== heutiges Verhalten).
- Ungültiges JSON in `ODOO_INSTANCES_JSON` → fail-fast beim Start mit klarer Meldung.
- Verbindungs-/Auth-Fehler einer Nicht-lokal-Instanz → bestehende `OdooAPIError`-Pfade
  (HTTP-Status wie heute), pro Instanz isoliert (eigener uid/secret-Cache).

## 7. Sicherheit
- Secrets ausschließlich in `.env`/Umgebung, niemals im Repo; `ODOO_INSTANCES_JSON` ist
  `.env`-only und steht in `.gitignore`-geschütztem Bereich.
- `GET /api/instances` gibt **nie** URL/DB/Key zurück (nur Name + Anzeigename).
- **Keine Datenvermischung:** jede Instanz hat eigenen Client/uid/secret; `local` und `logilab`
  teilen keinen Auth-State. Reads/Writes der einen Instanz erreichen nie die andere.
- Bestehende Schutzmechanismen (Picker-Identität, IDOR-Scoping, Idempotenz) bleiben unverändert
  und gelten pro Instanz.

## 8. Bewusst außerhalb des Scopes (PoC-Grenze)
- **n8n-Async-Pfad bleibt auf `local`.** Event-Envelope wird **nicht** instanz-bewusst; Callbacks
  (`n8n_internal.py`) schreiben weiter über den `local`-Client zurück. Folge: Wird auf einer
  Nicht-lokal-Instanz ein Sync-Write gemacht (z. B. Confirm), läuft der nachgelagerte n8n-Effekt
  (falls überhaupt ausgelöst) gegen `local`. Für die Demo (gleiche PWA, andere DB, Reads + direkte
  Writes) irrelevant. Die gewählte Instanz wird in der Telemetrie geloggt, damit dies nachvollziehbar
  bleibt. Volle n8n-Instanz-Bewusstheit ist eine separate spätere Erweiterung.
- Kein Multi-Instanz-Idempotenz-Scoping (Idempotenz lebt in der jeweiligen Odoo-Instanz selbst).
- Keine UI-Mandanten-Verwaltung (Profile sind Config, kein CRUD).

## 9. Tests
- **Unit (`tests/`):**
  - `resolve_instance`: bekannter Name → Profil; kein Header → `local`; unbekannt → 400.
  - Per-Profil-Cache: zweimaliger Abruf desselben Profils liefert **denselben** Client; verschiedene
    Profile liefern verschiedene Clients.
  - Config-Parsing: `ODOO_INSTANCES_JSON` korrekt → Register inkl. `local`; ungültig → Fehler.
  - `GET /api/instances` enthält keine Secret-/URL-Felder.
- **Integration:** Request **ohne** Header verhält sich identisch zu heute (Default `local`) —
  Regressionsschutz über bestehende Picking-Tests.
- **PWA (Playwright/e2e + `api.test.mjs`):** Dropdown setzt Header; Default lokal; `getInstances`-Wrapper.
- **Security:** unbekanntes Profil → 400; `/api/instances` ohne Secrets.

## 10. Akzeptanzkriterien
- [ ] Backend kennt ein Register von Odoo-Profilen (`name → url, db, user, api_key`).
- [ ] Auswahl pro Request via `X-Odoo-Instance` (oder `?instance=`); Default = `local`.
- [ ] Umschalten ohne Neustart/Re-Deploy.
- [ ] Secrets bleiben aus dem Repo.
- [ ] Unbekanntes Profil → 400, kein stiller Fallback.
- [ ] `GET /api/instances` liefert Namen/Anzeigenamen ohne Secrets.
- [ ] Kleiner PWA-Umschalter (Default lokal), der den Header setzt.
- [ ] Verhalten ohne Header/ohne `ODOO_INSTANCES_JSON` == heute (rückwärtskompatibel).
- [ ] Tests grün (Unit/Integration/PWA/Security).

## 11. Betroffene Dateien
- `backend/app/config.py` — `OdooProfile`, `ODOO_INSTANCES_JSON`-Parsing, `get_instance_registry`.
- `backend/app/services/odoo_client.py` — Konstruktor nimmt Profil.
- `backend/app/dependencies.py` — Per-Profil-Cache, `resolve_instance`, `get_request_odoo_client`,
  `get_default_odoo_client`, angepasste Service-Factories.
- `backend/app/routers/instances.py` — **neu** (`GET /api/instances`); `main.py` include.
- `backend/app/routers/pickings.py`, `voice.py`, `quality.py` — Direkt-Nutzer auf request-aware Client.
- `backend/app/routers/n8n_internal.py` — Callbacks auf `get_default_odoo_client`.
- `pwa/js/api.js` — Header zentral setzen, `getInstances`-Wrapper.
- `pwa/js/app.js`, `pwa/index.html`, `pwa/css/app.css` — kleiner Dropdown-Selektor.
- `docker-compose.yml` — `ODOO_INSTANCES_JSON` additiv durchreichen.
- Tests: `backend/tests/…`, `pwa/js/tests/api.test.mjs`, ggf. `e2e/…`.

## 12. Risiken & Annahmen
- Unterschiedliche Datenmodelle je Instanz (z. B. `quality.alert.custom`/`stock_picking_batch`
  fehlt extern) → für die Demo Reads/Standard-Picking annehmen; abweichende Felder sind eine
  separate Adapter-/Feature-Flag-Frage (out of scope).
- Zertifikate/Netz der externen Instanz müssen erreichbar sein (httpx, ggf. TLS-Trust) — Demo-Setup.
- `OdooClient`-Konstruktor-Änderung: Aufrufer/Tests prüfen (Tests mocken `odoo` i. d. R. als AsyncMock,
  daher geringes Risiko).
