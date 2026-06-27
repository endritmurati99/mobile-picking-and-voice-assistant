# Odoo-Instanz-Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das FastAPI-Backend kann pro Request zwischen mehreren Odoo-Instanzen umschalten (Header `X-Odoo-Instance`), Default bleibt die lokale Instanz; ein kleiner PWA-Umschalter macht es im Kolloquium klickbar.

**Architecture:** Ein Profil-Register (`name → OdooProfile`) in `config.py`; `OdooClient` nimmt ein Profil; ein Per-Profil-Client-Cache in `dependencies.py` ersetzt das `@lru_cache`-Singleton; eine `resolve_instance`-Dependency liest den Selektor (unbekannt → 400) und `get_request_odoo_client` liefert den passenden Client an die Services. n8n-Callbacks bleiben bewusst auf `local`.

**Tech Stack:** Python 3 / FastAPI / pydantic-settings / httpx (Backend); Vanilla JS + node:test + Playwright (PWA).

**Spec:** `docs/superpowers/specs/2026-06-27-odoo-instance-switch-design.md`

## Global Constraints

- **Invariante:** PWA spricht nur mit FastAPI; Odoo = System of Record **pro Instanz** (keine Datenvermischung); Touch bleibt Fallback.
- **Rückwärtskompatibilität (hart):** Ohne `ODOO_INSTANCES_JSON` und ohne `X-Odoo-Instance`-Header verhält sich alles **exakt** wie heute. Default-Profilname = `local`, Anzeigename `Lokal`.
- **Sicherheit:** Secrets nur in `.env`/Umgebung, nie im Repo; `GET /api/instances` gibt **nur** `name` + `display_name` zurück (keine `url`/`db`/`api_key`/`password`).
- **Fehlerverhalten:** unbekanntes Profil → **HTTP 400**, kein stiller Fallback; ungültiges `ODOO_INSTANCES_JSON` → fail-fast (`ValueError`).
- **Scope:** Nur Sync-Pfad. n8n-Async-Callbacks bleiben auf `local` (kein Envelope-Eingriff).
- **Konventionen:** Deutsche Fehlermeldungen/Kommentare wie im Bestand; Odoo-18-Felder (`quantity`, `move_ids`). Backend-Tests laufen über `make test`; PWA-Unit über `node --test`, PWA-e2e über `make test-ui`.
- **Naming-Entscheidung (Abweichung vom Spec):** Statt eines zusätzlichen `get_default_odoo_client` dient das bestehende `get_odoo_client` als expliziter **lokal/Default**-Getter (gleiches Verhalten, weniger Churn, n8n-Callbacks bleiben unverändert darauf). Im Code per Docstring kenntlich gemacht.

---

### Task 1: Profil-Register in `config.py` (+ docker-compose passthrough)

**Files:**
- Modify: `Mobile Picking und Voice Assistant/backend/app/config.py`
- Modify: `Mobile Picking und Voice Assistant/docker-compose.yml` (backend `environment`)
- Test: `Mobile Picking und Voice Assistant/backend/tests/test_instance_registry.py` (create)

**Interfaces:**
- Produces: `OdooProfile` (frozen dataclass: `name, display_name, url, db, user, api_key="", password=""`); `get_instance_registry() -> dict[str, OdooProfile]`; `settings.odoo_instances_json: str`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_instance_registry.py`:

```python
"""Tests fuer das Odoo-Profil-Register (config)."""
import pytest

from app import config
from app.config import OdooProfile, get_instance_registry


@pytest.fixture(autouse=True)
def _reset_instances(monkeypatch):
    # Default: kein Zusatz-JSON, bekannte local-Werte.
    monkeypatch.setattr(config.settings, "odoo_url", "http://odoo:8069")
    monkeypatch.setattr(config.settings, "odoo_db", "picking")
    monkeypatch.setattr(config.settings, "odoo_user", "admin")
    monkeypatch.setattr(config.settings, "odoo_api_key", "k")
    monkeypatch.setattr(config.settings, "odoo_password", "p")
    monkeypatch.setattr(config.settings, "odoo_instances_json", "")


def test_local_profile_always_present_from_settings():
    reg = get_instance_registry()
    assert "local" in reg
    local = reg["local"]
    assert isinstance(local, OdooProfile)
    assert local.url == "http://odoo:8069"
    assert local.db == "picking"
    assert local.display_name == "Lokal"


def test_extra_profile_parsed_from_json(monkeypatch):
    monkeypatch.setattr(
        config.settings, "odoo_instances_json",
        '{"logilab": {"url": "https://logilab:8069", "db": "logilab", '
        '"user": "admin", "api_key": "x", "display_name": "LogILab"}}',
    )
    reg = get_instance_registry()
    assert set(reg) == {"local", "logilab"}
    assert reg["logilab"].url == "https://logilab:8069"
    assert reg["logilab"].display_name == "LogILab"


def test_local_key_in_json_is_ignored(monkeypatch):
    monkeypatch.setattr(
        config.settings, "odoo_instances_json",
        '{"local": {"url": "https://evil:8069", "db": "evil"}}',
    )
    reg = get_instance_registry()
    assert reg["local"].url == "http://odoo:8069"  # bleibt kanonisch aus odoo_*


def test_display_name_falls_back_to_name(monkeypatch):
    monkeypatch.setattr(
        config.settings, "odoo_instances_json",
        '{"logilab": {"url": "https://logilab:8069", "db": "logilab"}}',
    )
    assert get_instance_registry()["logilab"].display_name == "logilab"


def test_invalid_json_raises(monkeypatch):
    monkeypatch.setattr(config.settings, "odoo_instances_json", "{not json")
    with pytest.raises(ValueError):
        get_instance_registry()


def test_profile_missing_url_or_db_raises(monkeypatch):
    monkeypatch.setattr(
        config.settings, "odoo_instances_json", '{"x": {"db": "only-db"}}',
    )
    with pytest.raises(ValueError):
        get_instance_registry()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test` (or `python -m pytest "backend/tests/test_instance_registry.py" -v`)
Expected: FAIL — `ImportError: cannot import name 'OdooProfile'` / `get_instance_registry`.

- [ ] **Step 3: Implement in `config.py`**

Add at the top of `config.py` (after the existing import line):

```python
import json
from dataclasses import dataclass
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class OdooProfile:
    name: str
    display_name: str
    url: str
    db: str
    user: str
    api_key: str = ""
    password: str = ""
```

Add a new field inside `class Settings` (next to the other `odoo_*` fields):

```python
    odoo_instances_json: str = ""
```

Add at the very end of the file (after `settings = Settings()`):

```python
def get_instance_registry() -> dict[str, OdooProfile]:
    """Register aller bekannten Odoo-Instanzen. `local` kommt immer kanonisch aus
    den odoo_*-Settings; weitere Profile aus ODOO_INSTANCES_JSON (Secrets .env-only)."""
    registry: dict[str, OdooProfile] = {
        "local": OdooProfile(
            name="local",
            display_name="Lokal",
            url=settings.odoo_url,
            db=settings.odoo_db,
            user=settings.odoo_user,
            api_key=settings.odoo_api_key,
            password=settings.odoo_password,
        )
    }
    raw = (settings.odoo_instances_json or "").strip()
    if not raw:
        return registry
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ODOO_INSTANCES_JSON ist kein gueltiges JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("ODOO_INSTANCES_JSON muss ein JSON-Objekt sein.")
    for name, cfg in parsed.items():
        key = str(name).strip().lower()
        if key == "local":
            continue  # local ist kanonisch aus odoo_* — JSON-local wird ignoriert
        if not isinstance(cfg, dict):
            raise ValueError(f"ODOO_INSTANCES_JSON['{name}'] muss ein Objekt sein.")
        if "url" not in cfg or "db" not in cfg:
            raise ValueError(f"ODOO_INSTANCES_JSON['{name}'] braucht 'url' und 'db'.")
        registry[key] = OdooProfile(
            name=key,
            display_name=str(cfg.get("display_name") or key),
            url=str(cfg["url"]),
            db=str(cfg["db"]),
            user=str(cfg.get("user") or "admin"),
            api_key=str(cfg.get("api_key") or ""),
            password=str(cfg.get("password") or ""),
        )
    return registry
```

- [ ] **Step 4: Run test to verify it passes**

Run: `make test` (or the targeted pytest above)
Expected: PASS (6 tests in `test_instance_registry.py`).

- [ ] **Step 5: Add the env passthrough in `docker-compose.yml`**

In the backend service `environment:` block (next to `ODOO_API_KEY`/`ODOO_PASSWORD`), add:

```yaml
      ODOO_INSTANCES_JSON: ${ODOO_INSTANCES_JSON:-}
```

- [ ] **Step 6: Commit**

```bash
git add "Mobile Picking und Voice Assistant/backend/app/config.py" \
        "Mobile Picking und Voice Assistant/backend/tests/test_instance_registry.py" \
        "Mobile Picking und Voice Assistant/docker-compose.yml"
git commit -m "feat(config): Odoo-Profil-Register (OdooProfile, ODOO_INSTANCES_JSON)"
```

---

### Task 2: `OdooClient` nimmt ein Profil

**Files:**
- Modify: `Mobile Picking und Voice Assistant/backend/app/services/odoo_client.py:19-68`
- Test: `Mobile Picking und Voice Assistant/backend/tests/test_odoo_client.py` (add tests)

**Interfaces:**
- Consumes: `OdooProfile` from Task 1.
- Produces: `OdooClient(profile: OdooProfile | None = None)` — bei `None` wird ein `local`-Profil aus `settings` gebaut (Verhalten wie heute). `_auth_secrets`/`authenticate` nutzen `self._profile`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_odoo_client.py`:

```python
from app.config import OdooProfile


def test_client_uses_explicit_profile():
    profile = OdooProfile(
        name="logilab", display_name="LogILab",
        url="https://logilab:8069", db="logilab", user="bot",
        api_key="abc", password="",
    )
    client = OdooClient(profile)
    assert client._url == "https://logilab:8069"
    assert client._db == "logilab"
    assert client._auth_secrets() == ["abc"]


@pytest.mark.anyio
async def test_authenticate_uses_profile_user_and_secret():
    profile = OdooProfile(
        name="logilab", display_name="LogILab",
        url="https://logilab:8069", db="logilab", user="bot",
        api_key="abc", password="",
    )
    client = OdooClient(profile)
    with patch.object(client, "_json_rpc", new_callable=AsyncMock) as mock_rpc:
        mock_rpc.return_value = 11
        uid = await client.authenticate()
    assert uid == 11
    # erstes Positional-Arg-Tupel: (service, method, args)
    args = mock_rpc.await_args.args[2]
    assert args == ["logilab", "bot", "abc", {}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test` (or `python -m pytest "backend/tests/test_odoo_client.py" -v`)
Expected: FAIL — `OdooClient()` nimmt aktuell kein Argument / `_auth_secrets` ist `@staticmethod` und liest globale `settings`.

- [ ] **Step 3: Implement in `odoo_client.py`**

Change the import line (top of file):

```python
from app.config import settings, OdooProfile
```

Replace `__init__` (lines 20-32):

```python
    def __init__(self, profile: OdooProfile | None = None):
        # Ohne Profil: kanonische lokale Instanz aus settings (Verhalten wie bisher).
        if profile is None:
            profile = OdooProfile(
                name="local", display_name="Lokal",
                url=settings.odoo_url, db=settings.odoo_db, user=settings.odoo_user,
                api_key=settings.odoo_api_key, password=settings.odoo_password,
            )
        self._profile = profile
        self._url = profile.url
        self._db = profile.db
        self._uid = None
        self._secret = None
        self._client = httpx.AsyncClient(
            timeout=_ODOO_TIMEOUT,
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
                keepalive_expiry=30.0,
            ),
        )
```

Replace `_auth_secrets` (lines 34-41) — now an instance method reading the profile:

```python
    def _auth_secrets(self) -> list[str]:
        candidates: list[str] = []
        for secret in (self._profile.api_key, self._profile.password):
            normalized = str(secret or "").strip()
            if normalized and normalized not in candidates:
                candidates.append(normalized)
        return candidates
```

In `authenticate` (lines 57-68) replace `settings.odoo_user` with the profile user:

```python
            uid = await self._json_rpc(
                "common", "authenticate",
                [self._db, self._profile.user, secret, {}]
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `make test` (or `python -m pytest "backend/tests/test_odoo_client.py" -v`)
Expected: PASS — both new tests **and** the existing `OdooClient()`-based tests (the `client` fixture patches `app.services.odoo_client.settings`, so the `profile=None` branch builds the local profile from the patched values).

- [ ] **Step 5: Commit**

```bash
git add "Mobile Picking und Voice Assistant/backend/app/services/odoo_client.py" \
        "Mobile Picking und Voice Assistant/backend/tests/test_odoo_client.py"
git commit -m "feat(odoo): OdooClient akzeptiert ein OdooProfile (Default = local aus settings)"
```

---

### Task 3: Per-Profil-Cache + `resolve_instance` + DI-Wrappers in `dependencies.py`

**Files:**
- Modify: `Mobile Picking und Voice Assistant/backend/app/dependencies.py:1-39`
- Test: `Mobile Picking und Voice Assistant/backend/tests/test_dependencies_instance.py` (create)

**Interfaces:**
- Consumes: `get_instance_registry`, `OdooProfile` (Task 1); `OdooClient(profile)` (Task 2).
- Produces: `resolve_instance(x_odoo_instance=None, instance=None) -> str` (default `"local"`, unbekannt → `HTTPException(400)`); `get_request_odoo_client(instance=Depends(resolve_instance)) -> OdooClient`; `get_odoo_client() -> OdooClient` (jetzt = lokaler/Default-Client, ohne `@lru_cache`); Service-Factories nehmen den Client per `Depends`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_dependencies_instance.py`:

```python
"""Tests fuer Instanz-Aufloesung und Per-Profil-Client-Cache."""
import pytest
from fastapi import HTTPException

from app import dependencies
from app.config import OdooProfile
from app.dependencies import resolve_instance, get_request_odoo_client, get_odoo_client


@pytest.fixture(autouse=True)
def _fake_registry(monkeypatch):
    reg = {
        "local": OdooProfile("local", "Lokal", "http://odoo:8069", "picking", "admin", "k", "p"),
        "logilab": OdooProfile("logilab", "LogILab", "https://logilab:8069", "logilab", "bot", "x", ""),
    }
    monkeypatch.setattr(dependencies, "get_instance_registry", lambda: reg)
    dependencies._clients.clear()
    yield
    dependencies._clients.clear()


def test_resolve_instance_defaults_to_local():
    assert resolve_instance(x_odoo_instance=None, instance=None) == "local"


def test_resolve_instance_known_header():
    assert resolve_instance(x_odoo_instance="LogiLab", instance=None) == "logilab"


def test_resolve_instance_query_fallback():
    assert resolve_instance(x_odoo_instance=None, instance="logilab") == "logilab"


def test_resolve_instance_unknown_raises_400():
    with pytest.raises(HTTPException) as exc:
        resolve_instance(x_odoo_instance="bogus", instance=None)
    assert exc.value.status_code == 400


def test_request_client_cached_per_profile():
    a = get_request_odoo_client("logilab")
    b = get_request_odoo_client("logilab")
    assert a is b
    assert a._db == "logilab"
    assert get_request_odoo_client("local") is not a
    assert get_odoo_client() is get_request_odoo_client("local")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test` (or `python -m pytest "backend/tests/test_dependencies_instance.py" -v`)
Expected: FAIL — `resolve_instance`/`get_request_odoo_client`/`dependencies._clients` existieren nicht.

- [ ] **Step 3: Implement in `dependencies.py`**

Update the imports block (top): keep `from functools import lru_cache` (still used by `get_n8n_client`), add `Query`, add the registry import:

```python
"""Dependency Injection fuer FastAPI."""
from functools import lru_cache
import secrets

from fastapi import Depends, Header, HTTPException, Query

from app.services.mobile_workflow import (
    InvalidPickerIdentityError,
    MobileWorkflowService,
    PickerIdentity,
    WriteRequestContext,
)
from app.services.cluster_service import ClusterService
from app.services.n8n_webhook import N8NWebhookClient
from app.services.odoo_client import OdooClient
from app.services.picking_service import PickingService
from app.config import settings, get_instance_registry
```

Replace the OdooClient factory + service factories (lines 20-39) with:

```python
# Per-Profil-Client-Cache: je Odoo-Instanz EIN langlebiger Client
# (eigener uid/secret-Cache + httpx-Pool). Reine Funktion (keine Dependency),
# damit der Instanz-Name nicht als Query-Param auf jedem Endpunkt auftaucht.
_clients: dict[str, OdooClient] = {}


def _get_cached_client(name: str) -> OdooClient:
    if name not in _clients:
        _clients[name] = OdooClient(get_instance_registry()[name])
    return _clients[name]


def get_odoo_client() -> OdooClient:
    """Lokale/Default-Instanz. Genutzt von n8n-Callbacks (bewusst immer local)."""
    return _get_cached_client("local")


@lru_cache()
def get_n8n_client() -> N8NWebhookClient:
    return N8NWebhookClient()


def resolve_instance(
    x_odoo_instance: str | None = Header(default=None, alias="X-Odoo-Instance"),
    instance: str | None = Query(default=None),
) -> str:
    """Waehlt das Odoo-Profil pro Request. Default 'local'; unbekannt -> 400."""
    name = (x_odoo_instance or instance or "local").strip().lower()
    if name not in get_instance_registry():
        raise HTTPException(status_code=400, detail=f"Unbekannte Odoo-Instanz: {name}")
    return name


def get_request_odoo_client(instance: str = Depends(resolve_instance)) -> OdooClient:
    return _get_cached_client(instance)


def get_picking_service(
    odoo: OdooClient = Depends(get_request_odoo_client),
    n8n: N8NWebhookClient = Depends(get_n8n_client),
) -> PickingService:
    return PickingService(odoo, n8n)


def get_cluster_service(
    odoo: OdooClient = Depends(get_request_odoo_client),
    n8n: N8NWebhookClient = Depends(get_n8n_client),
) -> ClusterService:
    return ClusterService(odoo, n8n)


def get_mobile_workflow_service(
    odoo: OdooClient = Depends(get_request_odoo_client),
) -> MobileWorkflowService:
    return MobileWorkflowService(odoo)
```

> Note: `get_n8n_client` bleibt unverändert (`@lru_cache`). Nur `get_odoo_client` wechselt vom `@lru_cache`-Singleton auf den Per-Profil-Cache (`_get_cached_client("local")`).

- [ ] **Step 4: Run test to verify it passes**

Run: `make test` (or `python -m pytest "backend/tests/test_dependencies_instance.py" -v`)
Expected: PASS (5 tests). Auch die bestehenden Route-Tests (`test_cluster_routes.py`, `test_mobile_routes.py`) bleiben grün, weil sie die Service-Factories via `dependency_overrides` ersetzen.

- [ ] **Step 5: Commit**

```bash
git add "Mobile Picking und Voice Assistant/backend/app/dependencies.py" \
        "Mobile Picking und Voice Assistant/backend/tests/test_dependencies_instance.py"
git commit -m "feat(di): Per-Profil-Client-Cache + resolve_instance + get_request_odoo_client"
```

---

### Task 4: `GET /api/instances`

**Files:**
- Create: `Mobile Picking und Voice Assistant/backend/app/routers/instances.py`
- Modify: `Mobile Picking und Voice Assistant/backend/app/main.py:5,30`
- Test: `Mobile Picking und Voice Assistant/backend/tests/test_instances_routes.py` (create)

**Interfaces:**
- Consumes: `get_instance_registry` (Task 1).
- Produces: `GET /api/instances` → `list[{"name": str, "display_name": str}]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_instances_routes.py`:

```python
"""Route-Test fuer GET /api/instances."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_list_instances_returns_local_without_secrets():
    resp = client.get("/api/instances")
    assert resp.status_code == 200
    data = resp.json()
    names = {item["name"] for item in data}
    assert "local" in names
    local = next(item for item in data if item["name"] == "local")
    assert local["display_name"] == "Lokal"
    # Keine Secrets/URLs leaken:
    for item in data:
        assert set(item.keys()) == {"name", "display_name"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test` (or `python -m pytest "backend/tests/test_instances_routes.py" -v`)
Expected: FAIL — Route `/api/instances` existiert nicht (404).

- [ ] **Step 3: Implement the router**

Create `backend/app/routers/instances.py`:

```python
"""Liste der verfuegbaren Odoo-Instanzen (nur Namen, keine Secrets)."""
from fastapi import APIRouter

from app.config import get_instance_registry

router = APIRouter()


@router.get("/instances")
def list_instances() -> list[dict[str, str]]:
    return [
        {"name": profile.name, "display_name": profile.display_name}
        for profile in get_instance_registry().values()
    ]
```

In `main.py` add `instances` to the import (line 5) and include the router (after line 30):

```python
from app.routers import cluster, health, instances, integration, n8n_internal, obsidian, pickings, quality, scan, voice
```

```python
app.include_router(instances.router, prefix="/api", tags=["instances"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `make test` (or `python -m pytest "backend/tests/test_instances_routes.py" -v`)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add "Mobile Picking und Voice Assistant/backend/app/routers/instances.py" \
        "Mobile Picking und Voice Assistant/backend/app/main.py" \
        "Mobile Picking und Voice Assistant/backend/tests/test_instances_routes.py"
git commit -m "feat(api): GET /api/instances (Name + Anzeigename, ohne Secrets)"
```

---

### Task 5: Nutzerseitige Direkt-Nutzer auf den request-aware Client umstellen

**Files:**
- Modify: `Mobile Picking und Voice Assistant/backend/app/routers/pickings.py:108` (+ Import)
- Modify: `Mobile Picking und Voice Assistant/backend/app/routers/quality.py:173` (+ Import)
- Modify: `Mobile Picking und Voice Assistant/backend/app/routers/voice.py:345` (+ Import)
- Test: `Mobile Picking und Voice Assistant/backend/tests/test_instance_routing.py` (create)

**Interfaces:**
- Consumes: `get_request_odoo_client` (Task 3).
- n8n-Callbacks (`n8n_internal.py`) bleiben unveraendert auf `get_odoo_client` (= local).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_instance_routing.py`:

```python
"""Instanz-Selektor am HTTP-Layer: 400 bei unbekannter Instanz, additiv bei bekannter."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_request_odoo_client
from app.main import app


def test_unknown_instance_returns_400_before_odoo():
    # Produktbild-Endpunkt braucht keine Picker-Identitaet -> resolve_instance
    # schlaegt VOR jedem Odoo-Call zu.
    with TestClient(app) as client:
        resp = client.get("/api/products/1/image", headers={"X-Odoo-Instance": "bogus"})
    assert resp.status_code == 400
    assert "Unbekannte Odoo-Instanz" in resp.json()["detail"]


def test_known_instance_is_accepted_additively():
    fake = AsyncMock()
    fake.search_read.return_value = []  # -> 404 "Kein Bild", aber Instanz akzeptiert
    app.dependency_overrides[get_request_odoo_client] = lambda: fake
    try:
        with TestClient(app) as client:
            resp = client.get("/api/products/1/image", headers={"X-Odoo-Instance": "local"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 404  # Endpunkt lief, kein Bild vorhanden
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test` (or `python -m pytest "backend/tests/test_instance_routing.py" -v`)
Expected: FAIL — `test_unknown_instance_returns_400_before_odoo` schlägt fehl, weil `get_product_image` noch `get_odoo_client` (ohne `resolve_instance`) nutzt → kein 400.

- [ ] **Step 3: Implement the router swaps**

In `pickings.py`: find the import of `get_odoo_client` (top of file) and add `get_request_odoo_client`; change line 108:

```python
    odoo: OdooClient = Depends(get_request_odoo_client),
```

In `quality.py`: add `get_request_odoo_client` to the dependencies import; change line 173:

```python
    odoo: OdooClient = Depends(get_request_odoo_client),
```

In `voice.py`: add `get_request_odoo_client` to the dependencies import; change line 345:

```python
    odoo: OdooClient = Depends(get_request_odoo_client),
```

> Belasse `get_odoo_client`-Imports, falls noch an anderer Stelle in derselben Datei genutzt (z. B. `n8n_internal.py`). Nur die drei nutzerseitigen Direkt-Nutzer wechseln.

- [ ] **Step 4: Run test to verify it passes**

Run: `make test` (or `python -m pytest "backend/tests/test_instance_routing.py" -v`)
Expected: PASS (beide Tests). Außerdem voller Backend-Lauf grün: `make test`.

- [ ] **Step 5: Commit**

```bash
git add "Mobile Picking und Voice Assistant/backend/app/routers/pickings.py" \
        "Mobile Picking und Voice Assistant/backend/app/routers/quality.py" \
        "Mobile Picking und Voice Assistant/backend/app/routers/voice.py" \
        "Mobile Picking und Voice Assistant/backend/tests/test_instance_routing.py"
git commit -m "feat(routes): nutzerseitige Odoo-Direktnutzer auf get_request_odoo_client"
```

---

### Task 6: PWA — `X-Odoo-Instance`-Header zentral + `getInstances`/`setActiveInstance`

**Files:**
- Modify: `Mobile Picking und Voice Assistant/pwa/js/api.js:6-13,65-72,172-198`
- Test: `Mobile Picking und Voice Assistant/pwa/js/tests/api.test.mjs` (add tests)

**Interfaces:**
- Produces: `getActiveInstance() -> string` (Default `"local"`); `setActiveInstance(name)`; `getInstances()` → `GET /instances`; `request(...)` hängt `X-Odoo-Instance` an, **nur** wenn ≠ `local` (Default bleibt byte-identisch zu heute).

- [ ] **Step 1: Write the failing test**

Append to `pwa/js/tests/api.test.mjs` (and add `getInstances, setActiveInstance` to the import list at the top):

```javascript
test('request adds X-Odoo-Instance only when a non-local instance is active', async () => {
    const originalFetch = global.fetch;
    const store = new Map();
    const originalStorage = global.localStorage;
    global.localStorage = {
        getItem(k) { return store.has(k) ? store.get(k) : null; },
        setItem(k, v) { store.set(k, v); },
        removeItem(k) { store.delete(k); },
    };
    let capturedHeaders = null;
    global.fetch = async (_url, options) => {
        capturedHeaders = options.headers;
        return { ok: true, status: 200, json: async () => ([]) };
    };

    try {
        // Default: kein Header
        await getPickings();
        assert.equal(capturedHeaders['X-Odoo-Instance'], undefined);

        // Nicht-lokal: Header gesetzt
        setActiveInstance('logilab');
        await getPickings();
        assert.equal(capturedHeaders['X-Odoo-Instance'], 'logilab');

        // Zurueck auf local: Header wieder weg
        setActiveInstance('local');
        await getPickings();
        assert.equal(capturedHeaders['X-Odoo-Instance'], undefined);
    } finally {
        global.fetch = originalFetch;
        global.localStorage = originalStorage;
    }
});

test('getInstances requests GET /instances', async () => {
    const originalFetch = global.fetch;
    let capturedUrl = null;
    global.fetch = async (url) => {
        capturedUrl = url;
        return { ok: true, status: 200, json: async () => ([{ name: 'local', display_name: 'Lokal' }]) };
    };
    try {
        const list = await getInstances();
        assert.equal(capturedUrl, '/api/instances');
        assert.equal(list[0].name, 'local');
    } finally {
        global.fetch = originalFetch;
    }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test "Mobile Picking und Voice Assistant/pwa/js/tests/api.test.mjs"`
Expected: FAIL — `setActiveInstance`/`getInstances` nicht exportiert.

- [ ] **Step 3: Implement in `api.js`**

Add a storage key in `STORAGE_KEYS` (object at line 6):

```javascript
    odooInstance: 'picking-assistant-odoo-instance',
```

Add helpers (e.g. directly after `getDeviceId`, line 72):

```javascript
export function getActiveInstance() {
    return safeStorageGet(STORAGE_KEYS.odooInstance) || 'local';
}

export function setActiveInstance(name) {
    const value = String(name || 'local').trim().toLowerCase();
    if (value && value !== 'local') {
        safeStorageSet(STORAGE_KEYS.odooInstance, value);
    } else {
        safeStorageRemove(STORAGE_KEYS.odooInstance);
    }
}
```

In `request(...)` (line 172), after the line `const headers = { ...(options.headers || {}) };` add:

```javascript
    const activeInstance = getActiveInstance();
    if (activeInstance && activeInstance !== 'local') {
        headers['X-Odoo-Instance'] = activeInstance;
    }
```

Add the API wrapper (next to the other exported request wrappers):

```javascript
export async function getInstances(options = {}) {
    return request('GET', '/instances', null, { signal: options.signal });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test "Mobile Picking und Voice Assistant/pwa/js/tests/api.test.mjs"`
Expected: PASS (all tests, incl. the two new ones).

- [ ] **Step 5: Commit**

```bash
git add "Mobile Picking und Voice Assistant/pwa/js/api.js" \
        "Mobile Picking und Voice Assistant/pwa/js/tests/api.test.mjs"
git commit -m "feat(pwa): X-Odoo-Instance-Header zentral + getInstances/setActiveInstance"
```

---

### Task 7: PWA — kleiner Instanz-Umschalter (Dropdown) + e2e

**Files:**
- Modify: `Mobile Picking und Voice Assistant/pwa/index.html:20-35` (in `.header-actions`)
- Modify: `Mobile Picking und Voice Assistant/pwa/js/app.js` (Import aus `./api.js`; `initInstanceSwitch()`; Aufruf in `init()` bei `app.js:3022`)
- Modify: `Mobile Picking und Voice Assistant/pwa/css/app.css` (Style `.instance-switch`)
- Test: `Mobile Picking und Voice Assistant/e2e/instance-switch.spec.js` (create)

**Interfaces:**
- Consumes: `getInstances`, `setActiveInstance`, `getActiveInstance` (Task 6).

- [ ] **Step 1: Write the failing test**

Create `e2e/instance-switch.spec.js`:

```javascript
const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');

test('Instanz-Umschalter setzt X-Odoo-Instance-Header auf Folge-Requests', async ({ page }) => {
  await mockPwaApi(page);
  await page.route('**/api/instances', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([
        { name: 'local', display_name: 'Lokal' },
        { name: 'logilab', display_name: 'LogILab' },
      ]),
    });
  });

  // Header auf einem nachfolgenden Pickings-Request einsammeln.
  let sawInstanceHeader = null;
  await page.route('**/api/pickings', async (route) => {
    sawInstanceHeader = route.request().headers()['x-odoo-instance'] || null;
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Lena Lager' }).click();

  const select = page.locator('#instance-switch');
  await expect(select).toBeVisible();
  await select.selectOption('logilab');

  // Eine erneute Pickings-Abfrage anstoßen (Pull-to-refresh / Reload der Liste).
  await page.reload();
  await page.getByRole('button', { name: 'Lena Lager' }).click();

  expect(sawInstanceHeader).toBe('logilab');
});
```

> Falls `mockPwaApi`/der Login-Flow abweicht, an die bestehenden e2e-Specs (`e2e/cluster.spec.js`) angleichen: gleicher Login-Button und `mockPwaApi`-Helper.

- [ ] **Step 2: Run test to verify it fails**

Run: `make test-ui` (oder `npx playwright test e2e/instance-switch.spec.js`)
Expected: FAIL — `#instance-switch` existiert nicht.

- [ ] **Step 3: Implement the dropdown**

In `index.html`, inside `<div class="header-actions">` (line 20), add as the first child:

```html
                    <select id="instance-switch" class="instance-switch" aria-label="Odoo-Instanz" title="Odoo-Instanz">
                    </select>
```

In `app.js`, extend the existing `import { ... } from './api.js';` with `getInstances, setActiveInstance, getActiveInstance`. Add this function (near other small UI helpers) and call it inside `init()` (`app.js:3022`):

```javascript
async function initInstanceSwitch() {
    const select = document.getElementById('instance-switch');
    if (!select) return;
    let instances = [];
    try {
        instances = await getInstances();
    } catch {
        instances = [{ name: 'local', display_name: 'Lokal' }];
    }
    if (!Array.isArray(instances) || instances.length <= 1) {
        // Nur eine Instanz -> Umschalter ausblenden (kein Demo-Mehrwert).
        select.hidden = true;
        return;
    }
    const active = getActiveInstance();
    select.innerHTML = '';
    for (const inst of instances) {
        const opt = document.createElement('option');
        opt.value = inst.name;
        opt.textContent = inst.display_name || inst.name;
        if (inst.name === active) opt.selected = true;
        select.appendChild(opt);
    }
    select.hidden = false;
    select.addEventListener('change', () => {
        setActiveInstance(select.value);
        window.location.reload();  // frische Daten aus der gewählten Instanz
    });
}
```

Inside `init()` add the call (after the picker/boot setup):

```javascript
    await initInstanceSwitch();
```

In `app.css` add:

```css
.instance-switch {
    font: inherit;
    padding: 4px 8px;
    border-radius: 8px;
    border: 1px solid var(--border, #d0d5dd);
    background: var(--surface, #fff);
    color: inherit;
    max-width: 9rem;
}
.instance-switch[hidden] { display: none; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `make test-ui` (oder `npx playwright test e2e/instance-switch.spec.js`)
Expected: PASS. Außerdem Regression: `make test-ui` gesamt grün, `make verify-visual-diff` unverändert (Dropdown ist additiv; falls eine Baseline kippt, bewusst via `make test-visual-diff-update` aktualisieren).

- [ ] **Step 5: Commit**

```bash
git add "Mobile Picking und Voice Assistant/pwa/index.html" \
        "Mobile Picking und Voice Assistant/pwa/js/app.js" \
        "Mobile Picking und Voice Assistant/pwa/css/app.css" \
        "Mobile Picking und Voice Assistant/e2e/instance-switch.spec.js"
git commit -m "feat(pwa): Instanz-Umschalter (Dropdown) + e2e"
```

---

## Abschluss (nach Task 7)

- [ ] Voller Lauf: `make verify` (oder einzeln `make test`, `make test-ui`, `make verify-workflows`).
- [ ] Obsidian-Notiz `05 - Future Functions/Odoo-Instanz-Switching (Multi-Mandant).md` auf „implemented" setzen + Funktionsdoku-Seite (Sektion 12) ergänzen (separate Doku-Aufgabe, Traceability-Regel).
- [ ] Memory `project_odoo_switch` + `MEMORY.md` aktualisieren (Feature umgesetzt, Branch, offene n8n-Grenze).
- [ ] Branch `feat/odoo-switch` pushen; Merge nach `main` erst nach Freigabe.
- [ ] `.env`/Demo: `ODOO_INSTANCES_JSON` für die LogILab-Instanz lokal setzen (nicht committen).
