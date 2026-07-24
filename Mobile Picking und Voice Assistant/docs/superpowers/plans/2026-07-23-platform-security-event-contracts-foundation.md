# Platform Security and Event Contracts Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Odoo-19-only security and delivery foundation that authenticates picker sessions, binds every request and callback to one Odoo instance, signs and deduplicates n8n traffic, persists jobs and events in an Odoo outbox, and exposes only the intended HTTPS application surface.

**Architecture:** Odoo remains the system of record: a feature-specific Odoo method commits the business mutation, integration job, immutable v2 envelope, and outbox row in one transaction. FastAPI authenticates browser and internal principals, leases outbox rows per Odoo instance, and transports byte-identical signed bodies; n8n verifies native header credentials and HMAC before any business node and signs every callback or binary request with a local custom node. Caddy is the only warehouse edge, while Odoo, PostgreSQL, n8n, and model services remain on isolated internal networks.

**Tech Stack:** Odoo 19 Community/Python/PostgreSQL 16, FastAPI 0.115/Pydantic 2/httpx 0.28, n8n 2.13.3 with Node.js >=22.16 and TypeScript custom nodes, Caddy 2, vanilla JavaScript PWA, pytest, Node test runner, Docker Compose.

## Global Constraints

- The approved sources of truth are `docs/superpowers/specs/2026-07-23-platform-security-event-contracts-design.md` and `docs/superpowers/specs/2026-07-23-parallel-modernization-program-design.md`.
- `45bad5031ef50185029e4107f81db57d2fe07186` is the immutable approved-spec
  base, not the execution base. After this plan commit, tag that exact commit
  `foundation-plan-approved-2026-07-23`; every branch/worktree resolves the tag's
  commit and records that hash before work, using `superpowers:using-git-worktrees`.
- Worktrees live below `/mnt/c/Users/endri/Desktop/Bachelor-worktrees/`; the repository checkout at `/mnt/c/Users/endri/Desktop/Bachelor` is not a shared feature workspace.
- The integrator keeps one of four active slots. At most three feature agents work concurrently, each in one owned worktree. Docker Compose, Odoo database, n8n live, Playwright, and network gates run serially.
- Before the formal Odoo-19 handoff, Foundation must not edit `docker-compose.yml` or `odoo/addons/picking_assistant_core/**`. New Foundation-only files, including `odoo/addons/picking_assistant_integration/**`, are collision-free but are not activated in production before the Odoo-19 runtime gate.
- Odoo 18 remains legacy v1. Never copy `picking_assistant_integration` into `odoo/addons18/`, and never add a dual Odoo-18 path for sessions, outbox, or v2 callbacks.
- Foundation owns `pwa/js/api.js` exactly once. It does not edit `pwa/js/app.js` or `pwa/index.html`; strict production session mode cannot be activated until the PWA track has integrated the login UI against the adapter delivered here.
- Browser authority comes only from `pwr_session`; `X-Picker-User-Id`, `X-Device-Id`, and `X-Odoo-Instance` are never authoritative in secure mode. `device_id` is audit data, not an authentication factor.
- The session cookie is `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/api`, `Max-Age=28800`. Sessions last at most eight hours; role revalidation is at most every 300 seconds and immediate for supervisor actions.
- CSRF cleartext exists only in the login/rotation response and PWA `sessionStorage`. Every authenticated browser POST except `POST /api/auth/csrf` requires a matching `X-CSRF-Token` and allowed HTTPS `Origin`.
- Login throttling is five failures per normalized login and keyed-HMAC source IP in 15 minutes; rows expire after 24 hours. Only the configured Caddy peer may supply `X-Forwarded-For`.
- Pre-auth public routes are exactly `POST /api/auth/picker-session`, `GET /api/auth/instances`, and `GET /api/health/live`.
- New event and callback bodies use `schema_version="v2"`, reject unknown fields, carry a signed Odoo instance, and never contain base64 images, labels, carrier credentials, session secrets, or processing lease secrets.
- HMAC secrets are separate per direction and decode to at least 32 random bytes. Signature skew is at most 300 seconds; nonce retention is at least 600 seconds; active and previous keys may overlap only during controlled rotation.
- The canonical HMAC bytes are `METHOD + "\n" + TARGET + "\n" + GENERATION + "\n" + TIMESTAMP + "\n" + NONCE + "\n" + SHA256(RAW_BODY)`. v2 signed endpoints reject query strings, fragments, non-canonical generations, and body reserialization.
- An HTTP transport retry preserves event or callback ID, idempotency key, body, generation, attempt, and sequence byte-for-byte. Only timestamp, nonce, and signature change.
- Processing retries increment `delivery_generation` and `attempt`, issue a new processing lease, keep the event body and event ID unchanged, and use new callback IDs with monotonically increasing sequence.
- Job terminal states are `succeeded`, `review_required`, and `failed`; a manual retry creates a new job with `supersedes_job_id`.
- Outbox backoff seconds are exactly `[10, 60, 300, 1800, 7200, 21600, 21600, 21600, 21600, 21600]`; the tenth failure moves the row to `dead`.
- Image inputs are JPEG, PNG, or WebP, at most 15 MiB and 24 megapixels, single-frame, decoder-valid, and non-polyglot. Artifacts are PDF or ZPL, at most 10 MiB; PDF is at most 20 pages and has no JavaScript, launch actions, embedded files, or encryption.
- Production exposes only Caddy HTTP redirect and HTTPS application ports. PostgreSQL, Odoo, n8n, Whisper, Piper, and Ollama have no warehouse-LAN bindings.
- n8n uses its own non-superuser database role and cannot connect to Odoo databases. The existing PostgreSQL `odoo` cluster superuser must be replaced by `pwr_db_admin`, `odoo_app`, and `n8n_app` before isolation can be claimed.
- Production starts fail-closed when secure origins, Odoo service credentials, native n8n header credentials, HMAC keys, callback credentials, or required key lengths are invalid, or when `mobile_header_grace_mode=true`.
- Never stage `graphify/` or `.serena/**`. Use path-exact `git add`; `git add .` and `git add -A` are forbidden.
- After a task's fresh verification passes, mark only that task's five checkboxes
  complete and add this plan file explicitly to the task commit, in addition to the
  task-specific paths shown in Step 5.
- Never log or persist cleartext passwords, session tokens, CSRF tokens, HMAC secrets, processing lease tokens, binary content, label content, or complete address snapshots.

---

## Execution Topology

The user does not need to open extra writer terminals. The integrator creates and assigns these worktrees:

```bash
ROOT="/mnt/c/Users/endri/Desktop/Bachelor"
WT="/mnt/c/Users/endri/Desktop/Bachelor-worktrees"
EXECUTION_TAG="foundation-plan-approved-2026-07-23"
EXECUTION_BASE="$(git -C "$ROOT" rev-parse "${EXECUTION_TAG}^{commit}")"
test "$(git -C "$ROOT" tag --points-at "$EXECUTION_BASE" | \
  grep -Fx "$EXECUTION_TAG")" = "$EXECUTION_TAG"

git -C "$ROOT" branch codex/integration-bachelor-hardening "$EXECUTION_BASE"
git -C "$ROOT" worktree add "$WT/00-integration-bachelor-hardening" codex/integration-bachelor-hardening
git -C "$ROOT" worktree add -b codex/foundation-platform-contracts-security \
  "$WT/01-foundation-platform-contracts-security" "$EXECUTION_BASE"
git -C "$ROOT" worktree add -b codex/odoo19-cutover \
  "$WT/02-odoo19-cutover" "$EXECUTION_BASE"
git -C "$ROOT" worktree add -b codex/n8n-visual-quality \
  "$WT/03-n8n-visual-quality" "$EXECUTION_BASE"
git -C "$ROOT" worktree add -b codex/voice-v2-safe-assistant \
  "$WT/04-voice-v2-safe-assistant" "$EXECUTION_BASE"
```

Expected: the tag resolves to the plan commit, all new branch tips initially equal
`$EXECUTION_BASE`, and five worktrees are listed by
`git -C "$ROOT" worktree list`. If a branch or path already exists, inspect it and
reuse it only when its merge base is this execution commit; do not delete or
force-reset it.

Wave 1 runs in parallel:

| Slot | Worktree | Responsibility |
| --- | --- | --- |
| Integrator | `00-integration-bachelor-hardening` | Reviews, status log, serial live gates, merges |
| Agent A | `01-foundation-platform-contracts-security` | This plan, one reviewed task at a time |
| Agent B | `02-odoo19-cutover` | Odoo-19 cutover plan and runtime fact gate |
| Agent C | `03-n8n-visual-quality` or `04-voice-v2-safe-assistant` | One approved downstream plan at a time |

Tasks 1-4 and the new integration add-on in Task 5 are safe while the Odoo-19
worktree is active. Task 12 and every Compose change wait for this handoff:

```bash
cd "$WT/00-integration-bachelor-hardening"
git merge --no-ff codex/odoo19-cutover -m "merge: establish Odoo 19 foundation base"
git tag -a wave1-odoo19-handoff -m "Odoo 19 runtime and addon handoff"

cd "$WT/01-foundation-platform-contracts-security"
git rebase codex/integration-bachelor-hardening
```

Expected: the Odoo-19 runtime fact gate is attached to the merge review; the Foundation worktree contains that merge before touching Compose or Core.

The integrator records every task commit and gate in `docs/superpowers/parallel/2026-07-23-program-status.md` on the integration branch. Feature agents update only this plan's checkboxes and their task commits.

## File Map

### Backend

- `backend/app/models/auth.py`: login schemas, immutable principal, session token hint.
- `backend/app/models/events.py`: strict v2 event, callback, acceptance, and response schemas.
- `backend/app/models/webhook_security.py`: HMAC keyring and verified-signature value types.
- `backend/app/services/hmac_signing.py`: canonical bytes, signature creation, signature verification.
- `backend/app/services/hmac_keyrings.py`: app-bound active/previous receiver keyring construction.
- `backend/app/services/auth_sessions.py`: login throttle, session creation, role revalidation, CSRF, logout.
- `backend/app/services/signed_webhook_transport.py`: byte-preserving backend-to-n8n delivery.
- `backend/app/services/outbox_dispatcher.py`: per-instance lease loop and watchdog.
- `backend/app/services/binary_validation.py`: image, PDF, ZPL, filename, and hash validation.
- `backend/app/routers/auth.py`: public login/instances and authenticated me/CSRF/logout endpoints.
- `backend/app/routers/n8n_v2.py`: signed acceptance, callback, media, and artifact endpoints.
- `backend/app/config.py`: secure settings and production startup validation.
- `backend/app/dependencies.py`: principal-first Odoo routing and signed internal dependencies.
- `backend/app/main.py`: production route surface and dispatcher lifespan.
- `backend/app/services/odoo_client.py`: independent picker credential authentication.
- `backend/app/services/mobile_workflow.py`: required scoped idempotency and principal adapter.
- Existing browser routers: session, CSRF, roles, and idempotency enforcement only; no unrelated feature refactor.

### Odoo 19

- `odoo/addons/picking_assistant_integration/**`: groups, API guard, sessions, throttle, jobs, outbox, receipts, nonces, attachment bindings, crons, and Odoo tests.
- `odoo/addons/picking_assistant_core/models/idempotency.py`: post-handoff scoped idempotency implementation.
- `odoo/addons/picking_assistant_core/migrations/19.0.2.0.0/pre-migrate.py`: old unique constraint migration.
- `odoo/addons/picking_assistant_core/data/ir_cron.xml`: idempotency cleanup.

### n8n and Infrastructure

- `n8n/workflow-registry.json`: sole workflow, event, path, host, credential, and activation registry.
- `n8n/custom-nodes/n8n-nodes-pwr/**`: local signature gate, signed HTTP node, and credentials.
- `n8n/Dockerfile`: pinned n8n image with custom extension outside the persistent home volume.
- `n8n/scripts/provision-credentials.mjs`: credential definition and rotation logic.
- `infrastructure/scripts/workflow_registry.py`: typed registry loader and CLI.
- `infrastructure/scripts/import-workflows.sh`: registry-driven inactive import and activation.
- `infrastructure/scripts/verify-workflows.py`: registry-driven static security verifier.
- `infrastructure/scripts/provision-n8n-credentials.sh`: container-local credential bootstrap.
- `infrastructure/scripts/init-db-roles.sh`: fresh-volume database bootstrap.
- `infrastructure/scripts/migrate-n8n-db-role.sh`: existing-volume backup/apply/verify/rollback.
- `infrastructure/scripts/verify-db-role-isolation.sh`: negative cross-database probes.
- `docker-compose.yml`, `docker-compose.dev.yml`, `.env.example`, and `infrastructure/caddy/Caddyfile`: post-handoff production network and route surface.

## Task Dependency Graph

```text
1 Config/Auth Types -----+--> 6 Session API --> 7 Principal/PWA Adapter --> 16 Route Cutover
2 HMAC/Event Contracts --+--> 9 Signed Transport/Dispatcher
                         +--> 10 Signed Internal Routes --> 11 Binary Routes
3 Workflow Registry --------> 14 Credentials/Importer/Verifier ---------> 15 Network
4 n8n Custom Nodes ----------> 14 ---------------------------------------> 15
5 Odoo Session/Throttle -----> 6
5 ---------------------------> 8 Jobs/Outbox/Receipts --> 9, 10
Odoo-19 handoff --------------> 12 Core Idempotency, 13 DB Roles, 15 Network
7 ----------------------------> 16 app-bound route construction
all tasks -----------------------------------------------------> 17 live gates
PWA + Voice + Cluster integration gates ----------------------> later production activation
```

### Task 1: Secure Configuration and Auth Value Types

**Files:**
- Create: `backend/app/models/auth.py`
- Create: `backend/tests/test_auth_models.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/config.py` in `Settings` and after `settings = Settings()`
- Modify: `backend/tests/test_instance_registry.py`
- Modify: `.env.example` only after the Odoo-19 handoff when Task 15 owns the final environment surface

**Interfaces:**
- Consumes: existing `OdooProfile` and refactors
  `get_instance_registry(candidate: Settings = settings)` so it never reads a
  different module-global settings object.
- Produces: `Principal`, `SessionTokenHint`, `PickerSessionLoginRequest`, `PrincipalResponse`, `PickerSessionResponse`, `CsrfResponse`, `validate_runtime_security(candidate: Settings) -> None`, `decode_secret_b64(name: str, value: str) -> bytes`.

- [x] **Step 1: Write failing auth-model and production-guard tests**

```python
# backend/tests/test_auth_models.py
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.config import Settings, validate_runtime_security
from app.models.auth import PickerSessionLoginRequest, Principal


def secure_settings(**overrides) -> Settings:
    values = {
        "runtime_profile": "production",
        "pwa_origins": "https://picking.warehouse.test",
        "mobile_header_grace_mode": False,
        "odoo_api_key": "service-key",
        "session_throttle_hmac_secret_b64": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        "pwr_backend_to_n8n_active_key_id": "b2n-2026-07",
        "pwr_backend_to_n8n_active_secret_b64": "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=",
        "pwr_n8n_to_backend_active_key_id": "n2b-2026-07",
        "pwr_n8n_to_backend_active_secret_b64": "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI=",
        "n8n_webhook_secret": "3" * 32,
        "n8n_callback_secret": "4" * 32,
    }
    values.update(overrides)
    return Settings(**values)


def test_login_request_rejects_unknown_fields_and_bad_device_id():
    with pytest.raises(ValidationError):
        PickerSessionLoginRequest(
            login="mina",
            password="secret",
            device_id="not-a-uuid",
            odoo_instance="o19",
            picker_user_id=7,
        )


def test_principal_is_immutable_and_instance_bound():
    principal = Principal(
        picker_user_id=7,
        picker_name="Mina Muster",
        device_id="123e4567-e89b-42d3-a456-426614174000",
        odoo_instance="o19",
        roles=frozenset({"picker"}),
        session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
        expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(AttributeError):
        principal.odoo_instance = "local"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"pwa_origins": "*"}, "Wildcard"),
        ({"pwa_origins": "http://warehouse.test"}, "HTTPS"),
        ({"mobile_header_grace_mode": True}, "grace"),
        ({"pwr_backend_to_n8n_active_secret_b64": "c2hvcnQ="}, "32 bytes"),
        ({"n8n_webhook_secret": ""}, "native"),
        ({"odoo_api_key": "", "odoo_password": ""}, "Odoo service"),
    ],
)
def test_production_security_is_fail_closed(overrides, message):
    with pytest.raises(ValueError, match=message):
        validate_runtime_security(secure_settings(**overrides))


def test_secure_production_settings_pass():
    validate_runtime_security(secure_settings())
```

- [x] **Step 2: Run the focused test and confirm the red state**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_auth_models.py tests/test_instance_registry.py -q
```

Expected: collection fails because `app.models.auth` and `validate_runtime_security` do not exist.

- [x] **Step 3: Add strict auth types and settings validation**

Create these concrete types:

```python
# backend/app/models/auth.py
from dataclasses import dataclass
from datetime import datetime
from typing import FrozenSet
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PickerSessionLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    login: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)
    device_id: UUID
    odoo_instance: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")

    @field_validator("odoo_instance")
    @classmethod
    def normalize_instance(cls, value: str) -> str:
        return value.lower()


@dataclass(frozen=True)
class SessionTokenHint:
    version: str
    odoo_instance: str
    token_hash: str


@dataclass(frozen=True)
class Principal:
    picker_user_id: int
    picker_name: str
    device_id: str
    odoo_instance: str
    roles: FrozenSet[str]
    session_id: str
    expires_at: datetime


class PrincipalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    picker_user_id: int
    picker_name: str
    device_id: str
    odoo_instance: str
    roles: list[str]
    session_id: UUID
    expires_at: datetime

    @classmethod
    def from_principal(cls, principal: Principal) -> "PrincipalResponse":
        return cls(
            picker_user_id=principal.picker_user_id,
            picker_name=principal.picker_name,
            device_id=principal.device_id,
            odoo_instance=principal.odoo_instance,
            roles=sorted(principal.roles),
            session_id=principal.session_id,
            expires_at=principal.expires_at,
        )


class PickerSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal: PrincipalResponse
    csrf_token: str = Field(min_length=43, max_length=128)


class CsrfResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csrf_token: str = Field(min_length=43, max_length=128)
```

Extend `Settings` with these exact names and defaults:

```python
# backend/app/config.py, inside Settings
runtime_profile: str = "development"
pwa_origins: str = "https://localhost"
trusted_caddy_peers: str = "127.0.0.1"
session_cookie_name: str = "pwr_session"
session_max_age_seconds: int = 28800
session_role_revalidate_seconds: int = 300
session_throttle_hmac_secret_b64: str = ""
login_failure_limit: int = 5
login_window_seconds: int = 900
login_throttle_retention_seconds: int = 86400
pwr_hmac_max_skew_seconds: int = 300
pwr_nonce_ttl_seconds: int = 600
pwr_backend_to_n8n_active_key_id: str = ""
pwr_backend_to_n8n_active_secret_b64: str = ""
pwr_backend_to_n8n_previous_key_id: str = ""
pwr_backend_to_n8n_previous_secret_b64: str = ""
pwr_n8n_to_backend_active_key_id: str = ""
pwr_n8n_to_backend_active_secret_b64: str = ""
pwr_n8n_to_backend_previous_key_id: str = ""
pwr_n8n_to_backend_previous_secret_b64: str = ""
workflow_registry_path: str = "../n8n/workflow-registry.json"
dispatcher_enabled: bool = False
dispatcher_poll_seconds: float = 2.0
dispatcher_lease_seconds: int = 60
dispatcher_batch_size: int = 50
```

Add the fail-closed helpers without logging values:

```python
# backend/app/config.py
import base64
import binascii
from urllib.parse import urlparse


def decode_secret_b64(name: str, value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{name} must be valid base64") from exc
    if len(decoded) < 32:
        raise ValueError(f"{name} must decode to at least 32 bytes")
    return decoded


def parse_origins(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def validate_runtime_security(candidate: Settings) -> None:
    if candidate.runtime_profile != "production":
        return

    origins = parse_origins(candidate.pwa_origins)
    if not origins or "*" in origins:
        raise ValueError("Wildcard or empty PWA origins are forbidden in production")
    if any(urlparse(origin).scheme != "https" for origin in origins):
        raise ValueError("Production PWA origins must use HTTPS")
    if candidate.mobile_header_grace_mode:
        raise ValueError("mobile header grace mode is forbidden in production")
    profiles = get_instance_registry(candidate)
    if not profiles or any(
        not (profile.api_key or profile.password) for profile in profiles.values()
    ):
        raise ValueError(
            "Every production Odoo profile requires a service credential"
        )
    if len(candidate.n8n_webhook_secret.encode("utf-8")) < 32:
        raise ValueError("native n8n webhook credential must be at least 32 bytes")
    if len(candidate.n8n_callback_secret.encode("utf-8")) < 32:
        raise ValueError("legacy callback credential must be at least 32 bytes")

    required_b64 = {
        "SESSION_THROTTLE_HMAC_SECRET_B64": candidate.session_throttle_hmac_secret_b64,
        "PWR_BACKEND_TO_N8N_ACTIVE_SECRET_B64": candidate.pwr_backend_to_n8n_active_secret_b64,
        "PWR_N8N_TO_BACKEND_ACTIVE_SECRET_B64": candidate.pwr_n8n_to_backend_active_secret_b64,
    }
    for name, value in required_b64.items():
        decode_secret_b64(name, value)

    if not candidate.pwr_backend_to_n8n_active_key_id:
        raise ValueError("backend-to-n8n active key ID is required")
    if not candidate.pwr_n8n_to_backend_active_key_id:
        raise ValueError("n8n-to-backend active key ID is required")

    previous_pairs = (
        (
            candidate.pwr_backend_to_n8n_previous_key_id,
            candidate.pwr_backend_to_n8n_previous_secret_b64,
            "PWR_BACKEND_TO_N8N_PREVIOUS_SECRET_B64",
        ),
        (
            candidate.pwr_n8n_to_backend_previous_key_id,
            candidate.pwr_n8n_to_backend_previous_secret_b64,
            "PWR_N8N_TO_BACKEND_PREVIOUS_SECRET_B64",
        ),
    )
    for key_id, secret, name in previous_pairs:
        if bool(key_id) != bool(secret):
            raise ValueError(f"{name} and its key ID must be configured together")
        if secret:
            decode_secret_b64(name, secret)
```

Call `validate_runtime_security(settings)` once at the end of `config.py`, after
`settings = Settings()` and the complete `get_instance_registry()` definition, before
`main.py` imports the settings to create the FastAPI app.

Refactor every field read inside `get_instance_registry()` from `settings.*` to
`candidate.*`. In production, a nonempty `odoo_instances_json` is authoritative:
start from an empty registry, accept an explicitly listed `local` key like any other
profile, and do not inject the legacy implicit `local` profile. Development keeps
the current implicit-local compatibility behavior. Production validation builds
the candidate registry and requires at least one profile plus an API key or
password on every profile; checking only the top-level `odoo_*` fields is
insufficient. Add tests with two `Settings` objects containing different local
database names and instance JSON and assert the returned registries do not share
profiles. Add a production case containing only `o19-a`/`o19-b` and require exactly
those names with no implicit `local`.

- [x] **Step 4: Run the focused tests and inspect the diff**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_auth_models.py tests/test_instance_registry.py -q
git diff --check
```

Expected: all selected tests pass; `git diff --check` prints nothing.

- [x] **Step 5: Commit the configuration contract**

```bash
git add \
  backend/app/config.py \
  backend/app/models/__init__.py \
  backend/app/models/auth.py \
  backend/tests/test_auth_models.py \
  backend/tests/test_instance_registry.py
git commit -m "feat(security): define secure runtime and principal contracts"
```

### Task 2: HMAC Primitives and Strict v2 Schemas

**Files:**
- Create: `backend/app/models/webhook_security.py`
- Create: `backend/app/models/events.py`
- Create: `backend/app/services/hmac_signing.py`
- Create: `backend/tests/test_hmac_signing.py`
- Create: `backend/tests/test_event_contracts.py`
- Modify: `backend/app/models/__init__.py`

**Interfaces:**
- Consumes: secret decoding and skew/nonce settings from Task 1.
- Produces: `HmacKey`, `HmacKeyring`, `SignedHeaders`, `VerifiedSignature`, `canonical_signature_input(...) -> bytes`, `sign_request(...) -> SignedHeaders`, `verify_signature(...) -> VerifiedSignature`, `payload_fingerprint(raw_body: bytes) -> str`, `EventEnvelopeV2`, `CallbackEnvelopeV2`, `EventAcceptanceRequest`, `EventAcceptanceResponse`, `CallbackApplyResponse`, `serialize_event_envelope(...) -> bytes`.

- [ ] **Step 1: Write the fixed-vector, negative, and schema tests**

```python
# backend/tests/test_hmac_signing.py
from datetime import datetime, timezone

import pytest

from app.models.webhook_security import HmacKey, HmacKeyring
from app.services.hmac_signing import (
    SignatureError,
    canonical_signature_input,
    payload_fingerprint,
    sign_request,
    verify_signature,
)

BODY = b'{"event_id":"a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32"}'
NONCE = "123e4567-e89b-42d3-a456-426614174000"
NOW = datetime.fromtimestamp(1760000000, tz=timezone.utc)


def test_python_signature_matches_frozen_cross_runtime_vector():
    signed = sign_request(
        method="POST",
        target="/webhook/quality-assessment-v2",
        delivery_generation=1,
        timestamp=1760000000,
        nonce=NONCE,
        raw_body=BODY,
        key=HmacKey("b2n-test", b"0" * 32),
    )
    assert payload_fingerprint(BODY) == (
        "cdc9aeda6396616866f863a30ce8507232b2cecd6cdd68c206c24b8c128751fc"
    )
    assert signed.signature == (
        "v1=6466f16aca767c63504c2d002d729c35fdc12df969060bc4e7e76fd0c69a43d4"
    )


def test_verifier_accepts_previous_rotation_key():
    headers = sign_request(
        method="POST",
        target="/api/internal/n8n/v2/callbacks/status",
        delivery_generation=2,
        timestamp=1760000000,
        nonce=NONCE,
        raw_body=BODY,
        key=HmacKey("previous", b"1" * 32),
    )
    verified = verify_signature(
        actual_method="POST",
        actual_target="/api/internal/n8n/v2/callbacks/status",
        raw_query=b"",
        raw_body=BODY,
        headers=headers.as_http_headers(),
        keyring=HmacKeyring(
            active=HmacKey("active", b"2" * 32),
            previous=HmacKey("previous", b"1" * 32),
        ),
        now=NOW,
        max_skew_seconds=300,
    )
    assert verified.key_id == "previous"
    assert verified.delivery_generation == 2


def test_verifier_accepts_starlette_lowercase_header_mapping():
    signed = sign_request(
        method="POST",
        target="/api/internal/n8n/v2/callbacks/status",
        delivery_generation=1,
        timestamp=1760000000,
        nonce=NONCE,
        raw_body=BODY,
        key=HmacKey("active", b"2" * 32),
    )
    verified = verify_signature(
        actual_method="POST",
        actual_target="/api/internal/n8n/v2/callbacks/status",
        raw_query=b"",
        raw_body=BODY,
        headers={key.lower(): value for key, value in signed.as_http_headers().items()},
        keyring=HmacKeyring(active=HmacKey("active", b"2" * 32)),
        now=NOW,
        max_skew_seconds=300,
    )
    assert verified.key_id == "active"


@pytest.mark.parametrize(
    ("target", "generation", "query"),
    [
        ("/api/internal/n8n/v2/callbacks/status?x=1", "1", b"x=1"),
        ("/api/internal/n8n/v2/callbacks/status", "01", b""),
        ("/api/internal/n8n/v2/callbacks/status", "0", b""),
    ],
)
def test_verifier_rejects_query_and_noncanonical_generation(target, generation, query):
    headers = {
        "X-PWR-Key-Id": "active",
        "X-PWR-Timestamp": "1760000000",
        "X-PWR-Nonce": NONCE,
        "X-PWR-Signed-Method": "POST",
        "X-PWR-Signed-Target": target,
        "X-PWR-Delivery-Generation": generation,
        "X-PWR-Signature": "v1=" + ("0" * 64),
    }
    with pytest.raises(SignatureError):
        verify_signature(
            actual_method="POST",
            actual_target="/api/internal/n8n/v2/callbacks/status",
            raw_query=query,
            raw_body=BODY,
            headers=headers,
            keyring=HmacKeyring(active=HmacKey("active", b"2" * 32)),
            now=NOW,
            max_skew_seconds=300,
        )
```

```python
# backend/tests/test_event_contracts.py
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.models.events import EventEnvelopeV2, serialize_event_envelope


def valid_event() -> dict:
    return {
        "schema_version": "v2",
        "event_name": "quality.assessment.requested.v1",
        "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
        "correlation_id": "0b2f7909-4ad9-44c1-8527-e775fe6d4bec",
        "causation_id": None,
        "occurred_at": datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
        "source": {"service": "picking-assistant-api", "odoo_instance": "o19"},
        "actor": {
            "type": "picker",
            "user_id": 7,
            "name": "Mina Muster",
            "device_id": "device-42",
        },
        "aggregate": {"model": "quality.alert.custom", "id": 42, "revision": 1},
        "payload": {"job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88", "media": []},
    }


def test_event_serialization_is_deterministic_and_contains_no_base64_field():
    event = EventEnvelopeV2.model_validate(valid_event())
    first = serialize_event_envelope(event)
    second = serialize_event_envelope(event)
    assert first == second
    assert b'"schema_version":"v2"' in first
    assert b'"event_id":"a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32"' in first
    assert b"base64" not in first.lower()


def test_event_rejects_unknown_fields_and_naive_time():
    data = valid_event()
    data["source"]["database"] = "must-not-leak"
    data["occurred_at"] = datetime(2026, 7, 23, 12, 0)
    with pytest.raises(ValidationError):
        EventEnvelopeV2.model_validate(data)


def test_event_rejects_unregistered_name():
    data = valid_event()
    data["event_name"] = "pick-confirmed"
    with pytest.raises(ValidationError):
        EventEnvelopeV2.model_validate(data)
```

- [ ] **Step 2: Run both tests and confirm missing contracts**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_hmac_signing.py tests/test_event_contracts.py -q
```

Expected: collection fails for the new modules.

- [ ] **Step 3: Implement the shared signature algorithm and strict schemas**

Use these exact value types:

```python
# backend/app/models/webhook_security.py
from dataclasses import dataclass


@dataclass(frozen=True)
class HmacKey:
    key_id: str
    secret: bytes

    def __post_init__(self) -> None:
        if not self.key_id or len(self.secret) < 32:
            raise ValueError("HMAC keys require an ID and at least 32 secret bytes")


@dataclass(frozen=True)
class HmacKeyring:
    active: HmacKey
    previous: HmacKey | None = None

    def resolve(self, key_id: str) -> HmacKey | None:
        for key in (self.active, self.previous):
            if key is not None and key.key_id == key_id:
                return key
        return None


@dataclass(frozen=True)
class SignedHeaders:
    key_id: str
    timestamp: int
    nonce: str
    signed_method: str
    signed_target: str
    delivery_generation: int
    signature: str

    def as_http_headers(self) -> dict[str, str]:
        return {
            "X-PWR-Key-Id": self.key_id,
            "X-PWR-Timestamp": str(self.timestamp),
            "X-PWR-Nonce": self.nonce,
            "X-PWR-Signed-Method": self.signed_method,
            "X-PWR-Signed-Target": self.signed_target,
            "X-PWR-Delivery-Generation": str(self.delivery_generation),
            "X-PWR-Signature": self.signature,
        }


@dataclass(frozen=True)
class VerifiedSignature:
    key_id: str
    timestamp: int
    nonce: str
    method: str
    target: str
    delivery_generation: int
    fingerprint: str
```

Implement the canonical algorithm without URL normalization:

```python
# backend/app/services/hmac_signing.py
import hashlib
import hmac
import re
from datetime import datetime
from uuid import UUID

from app.models.webhook_security import (
    HmacKey,
    HmacKeyring,
    SignedHeaders,
    VerifiedSignature,
)

_GENERATION = re.compile(r"^[1-9][0-9]*$")
_SIGNATURE = re.compile(r"^v1=([0-9a-f]{64})$")


class SignatureError(ValueError):
    def __init__(self, status_code: int, reason_code: str):
        self.status_code = status_code
        self.reason_code = reason_code
        super().__init__(reason_code)


def payload_fingerprint(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def canonical_signature_input(
    method: str,
    target: str,
    delivery_generation: int | str,
    timestamp: int | str,
    nonce: str,
    raw_body: bytes,
) -> bytes:
    generation = str(delivery_generation)
    if not _GENERATION.fullmatch(generation):
        raise SignatureError(400, "invalid_delivery_generation")
    return "\n".join(
        (
            method,
            target,
            generation,
            str(timestamp),
            nonce,
            payload_fingerprint(raw_body),
        )
    ).encode("utf-8")


def sign_request(
    *,
    method: str,
    target: str,
    delivery_generation: int,
    timestamp: int,
    nonce: str,
    raw_body: bytes,
    key: HmacKey,
) -> SignedHeaders:
    canonical = canonical_signature_input(
        method, target, delivery_generation, timestamp, nonce, raw_body
    )
    digest = hmac.new(key.secret, canonical, hashlib.sha256).hexdigest()
    return SignedHeaders(
        key_id=key.key_id,
        timestamp=timestamp,
        nonce=nonce,
        signed_method=method,
        signed_target=target,
        delivery_generation=delivery_generation,
        signature=f"v1={digest}",
    )


def verify_signature(
    *,
    actual_method: str,
    actual_target: str,
    raw_query: bytes,
    raw_body: bytes,
    headers: dict[str, str],
    keyring: HmacKeyring,
    now: datetime,
    max_skew_seconds: int,
) -> VerifiedSignature:
    if raw_query:
        raise SignatureError(400, "query_not_allowed")
    normalized = {str(name).lower(): value for name, value in headers.items()}
    names = (
        "x-pwr-key-id",
        "x-pwr-timestamp",
        "x-pwr-nonce",
        "x-pwr-signed-method",
        "x-pwr-signed-target",
        "x-pwr-delivery-generation",
        "x-pwr-signature",
    )
    if any(not normalized.get(name) for name in names):
        raise SignatureError(401, "missing_signature_header")

    key = keyring.resolve(normalized["x-pwr-key-id"])
    if key is None:
        raise SignatureError(401, "unknown_key_id")
    try:
        timestamp = int(normalized["x-pwr-timestamp"])
        UUID(normalized["x-pwr-nonce"])
    except (ValueError, TypeError) as exc:
        raise SignatureError(400, "malformed_timestamp_or_nonce") from exc
    if abs(int(now.timestamp()) - timestamp) > max_skew_seconds:
        raise SignatureError(409, "timestamp_outside_window")

    method = normalized["x-pwr-signed-method"]
    target = normalized["x-pwr-signed-target"]
    generation_text = normalized["x-pwr-delivery-generation"]
    if method != actual_method or target != actual_target:
        raise SignatureError(401, "signed_request_mismatch")
    if not _GENERATION.fullmatch(generation_text):
        raise SignatureError(400, "invalid_delivery_generation")
    if not _SIGNATURE.fullmatch(normalized["x-pwr-signature"]):
        raise SignatureError(401, "malformed_signature")

    expected = sign_request(
        method=method,
        target=target,
        delivery_generation=int(generation_text),
        timestamp=timestamp,
        nonce=normalized["x-pwr-nonce"],
        raw_body=raw_body,
        key=key,
    )
    if not hmac.compare_digest(expected.signature, normalized["x-pwr-signature"]):
        raise SignatureError(401, "invalid_signature")
    return VerifiedSignature(
        key_id=key.key_id,
        timestamp=timestamp,
        nonce=normalized["x-pwr-nonce"],
        method=method,
        target=target,
        delivery_generation=int(generation_text),
        fingerprint=payload_fingerprint(raw_body),
    )
```

Define schemas with `ConfigDict(extra="forbid")`, aware UTC datetimes, UUID IDs, positive revisions/sequences/generations, and these frozen registries:

```python
# backend/app/models/events.py
import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

EVENT_NAMES = frozenset(
    {"quality.assessment.requested.v1", "shipment.parcel.ready.v1"}
)
CALLBACK_NAMES = frozenset(
    {"quality.assessment.status.v1", "shipping.label.status.v1"}
)
JOB_STATUSES = frozenset(
    {"queued", "running", "succeeded", "review_required", "retry_scheduled", "failed"}
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


class EventSource(StrictModel):
    service: Literal["picking-assistant-api"]
    odoo_instance: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")


class EventActor(StrictModel):
    type: Literal["picker", "supervisor", "system"]
    user_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, max_length=256)
    device_id: str | None = Field(default=None, max_length=128)


class EventAggregate(StrictModel):
    model: str = Field(min_length=1, max_length=128)
    id: int = Field(ge=1)
    revision: int = Field(ge=1)


class EventEnvelopeV2(StrictModel):
    schema_version: Literal["v2"]
    event_name: str
    event_id: UUID
    correlation_id: UUID
    causation_id: UUID | None
    occurred_at: datetime
    source: EventSource
    actor: EventActor
    aggregate: EventAggregate
    payload: dict[str, Any]

    _validate_time = field_validator("occurred_at")(_aware)

    @field_validator("event_name")
    @classmethod
    def known_event(cls, value: str) -> str:
        if value not in EVENT_NAMES:
            raise ValueError("unregistered event name")
        return value


class CallbackEnvelopeV2(StrictModel):
    schema_version: Literal["v2"]
    callback_name: str
    callback_id: UUID
    source_event_id: UUID
    correlation_id: UUID
    odoo_instance: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    job_id: UUID
    sequence: int = Field(ge=1)
    attempt: int = Field(ge=1)
    delivery_generation: int = Field(ge=1)
    processing_lease_token: str = Field(min_length=32, max_length=256)
    status: str
    execution_id: str = Field(min_length=1, max_length=256)
    occurred_at: datetime
    next_retry_at: datetime | None
    result: dict[str, Any]
    error: dict[str, Any] | None
    metrics: dict[str, Any]

    _validate_time = field_validator("occurred_at")(_aware)

    @field_validator("callback_name")
    @classmethod
    def known_callback(cls, value: str) -> str:
        if value not in CALLBACK_NAMES:
            raise ValueError("unregistered callback name")
        return value

    @field_validator("status")
    @classmethod
    def known_status(cls, value: str) -> str:
        if value not in JOB_STATUSES - {"queued"}:
            raise ValueError("invalid callback status")
        return value


class EventAcceptanceRequest(StrictModel):
    schema_version: Literal["v2"]
    event_id: UUID
    job_id: UUID
    odoo_instance: str
    payload_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    ingress_key_id: str
    ingress_nonce: UUID
    delivery_generation: int = Field(ge=1)


class EventAcceptanceResponse(StrictModel):
    accepted: Literal[True]
    event_id: UUID
    process: bool
    processing_lease_token: str | None = None


class CallbackApplyResponse(StrictModel):
    status: Literal["applied", "replayed", "ignored_stale"]
    job_id: UUID
    sequence: int = Field(ge=0)


def serialize_event_envelope(envelope: EventEnvelopeV2) -> bytes:
    return json.dumps(
        envelope.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
```

- [ ] **Step 4: Run all contract tests**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_hmac_signing.py tests/test_event_contracts.py -q
git diff --check
```

Expected: all tests pass and the frozen signature is exactly `v1=6466f16aca767c63504c2d002d729c35fdc12df969060bc4e7e76fd0c69a43d4`.

- [ ] **Step 5: Commit the protocol primitives**

```bash
git add \
  backend/app/models/__init__.py \
  backend/app/models/events.py \
  backend/app/models/webhook_security.py \
  backend/app/services/hmac_signing.py \
  backend/tests/test_event_contracts.py \
  backend/tests/test_hmac_signing.py
git commit -m "feat(events): freeze v2 envelopes and HMAC contract"
```

### Task 3: Central Workflow Registry

**Files:**
- Create: `n8n/workflow-registry.json`
- Create: `infrastructure/scripts/workflow_registry.py`
- Create: `infrastructure/tests/test_workflow_registry.py`
- Modify: none of the workflow JSON files in this task

**Interfaces:**
- Consumes: the eight existing files under `n8n/workflows/`.
- Produces: `CredentialBinding`, `WorkflowSpec`, `WorkflowRegistry`,
  `load_registry(path: Path) -> WorkflowRegistry`, CLI commands `managed-files`,
  `activation-order`, `test-only-files`, and `credential-bindings`.

- [x] **Step 1: Write failing registry validation tests**

```python
# infrastructure/tests/test_workflow_registry.py
import json
from pathlib import Path

import pytest

from infrastructure.scripts.workflow_registry import load_registry

ROOT = Path(__file__).resolve().parents[2]


def test_repository_registry_has_every_workflow_once():
    registry = load_registry(ROOT / "n8n/workflow-registry.json")
    disk = {path.name for path in (ROOT / "n8n/workflows").glob("*.json")}
    assert {item.file for item in registry.workflows} == disk
    assert registry.managed_files() == (
        "error-trigger.json",
        "voice-exception-query.json",
        "quality-alert-created.json",
        "shortage-reported.json",
    )


def test_duplicate_path_and_unknown_credential_fail(tmp_path):
    source = json.loads((ROOT / "n8n/workflow-registry.json").read_text())
    source["workflows"][1]["webhook_paths"] = source["workflows"][0]["webhook_paths"]
    source["workflows"][1]["credential_bindings"] = [
        {
            "node": "Gate",
            "credential_type": "pwrInboundHmac",
            "logical_name": "missing.logical.name",
        }
    ]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate webhook path|unknown logical credential"):
        load_registry(path, workflow_root=ROOT / "n8n/workflows")


def test_v2_requires_native_header_and_hmac_gate(tmp_path):
    source = json.loads((ROOT / "n8n/workflow-registry.json").read_text())
    source["workflows"][0]["generation"] = "v2"
    source["workflows"][0]["authentication"] = "legacy_v1"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="native_header_hmac"):
        load_registry(path, workflow_root=ROOT / "n8n/workflows")
```

- [x] **Step 2: Run the test and confirm the registry is absent**

Run:

```bash
PYTHONPATH=. python3 -m pytest infrastructure/tests/test_workflow_registry.py -q
```

Expected: collection fails because `workflow_registry.py` does not exist.

- [x] **Step 3: Create the sole registry and strict loader**

Use this top-level schema and list all eight existing workflow files exactly once:

```json
{
  "schema_version": "v1",
  "credentials": {
    "pwr.v2.inbound-header": {"type": "httpHeaderAuth"},
    "pwr.v2.backend-to-n8n-hmac": {"type": "pwrInboundHmac"},
    "pwr.v2.n8n-to-backend-hmac": {"type": "pwrOutboundHmac"}
  },
  "workflows": [
    {
      "file": "batch-confirmed.json",
      "name": "Batch Confirmed",
      "generation": "v1",
      "event_names": ["batch-confirmed"],
      "webhook_paths": ["batch-confirmed"],
      "callback_paths": [],
      "authentication": "legacy_v1",
      "managed": false,
      "production_activation": false,
      "activation_order": null,
      "allowed_target_hosts": [],
      "credential_bindings": []
    },
    {
      "file": "daily-report.json",
      "name": "Daily Picking Report",
      "generation": "v1",
      "event_names": [],
      "webhook_paths": [],
      "callback_paths": [],
      "authentication": "scheduled_v1",
      "managed": false,
      "production_activation": false,
      "activation_order": null,
      "allowed_target_hosts": [],
      "credential_bindings": []
    },
    {
      "file": "error-trigger.json",
      "name": "Error Trigger",
      "generation": "v1",
      "event_names": [],
      "webhook_paths": [],
      "callback_paths": ["/api/integration/log"],
      "authentication": "error_trigger_v1",
      "managed": true,
      "production_activation": true,
      "activation_order": 10,
      "allowed_target_hosts": ["backend"],
      "credential_bindings": []
    },
    {
      "file": "pick-confirmed.json",
      "name": "Pick Confirmed",
      "generation": "v1",
      "event_names": ["pick-confirmed"],
      "webhook_paths": ["pick-confirmed"],
      "callback_paths": [],
      "authentication": "legacy_v1",
      "managed": false,
      "production_activation": false,
      "activation_order": null,
      "allowed_target_hosts": [],
      "credential_bindings": []
    },
    {
      "file": "quality-alert-ai-evaluation.json",
      "name": "Quality Alert AI Evaluation",
      "generation": "v1",
      "event_names": [],
      "webhook_paths": [],
      "callback_paths": ["/api/internal/n8n/quality-assessment-ai"],
      "authentication": "subworkflow_v1",
      "managed": false,
      "production_activation": false,
      "activation_order": null,
      "allowed_target_hosts": ["backend"],
      "credential_bindings": []
    },
    {
      "file": "quality-alert-created.json",
      "name": "Quality Alert Created",
      "generation": "v1",
      "event_names": ["quality-alert-created"],
      "webhook_paths": ["quality-alert-created"],
      "callback_paths": ["/api/internal/n8n/quality-assessment"],
      "authentication": "legacy_v1",
      "managed": true,
      "production_activation": true,
      "activation_order": 30,
      "allowed_target_hosts": ["backend"],
      "credential_bindings": []
    },
    {
      "file": "shortage-reported.json",
      "name": "Shortage Reported",
      "generation": "v1",
      "event_names": ["shortage-reported"],
      "webhook_paths": ["shortage-reported"],
      "callback_paths": ["/api/internal/n8n/replenishment-action"],
      "authentication": "legacy_v1",
      "managed": true,
      "production_activation": true,
      "activation_order": 40,
      "allowed_target_hosts": ["backend"],
      "credential_bindings": []
    },
    {
      "file": "voice-exception-query.json",
      "name": "Voice Exception Query",
      "generation": "v1",
      "event_names": ["voice-exception-query"],
      "webhook_paths": ["voice-exception-query"],
      "callback_paths": ["/api/internal/n8n/manual-review-activity"],
      "authentication": "legacy_v1",
      "managed": true,
      "production_activation": true,
      "activation_order": 20,
      "allowed_target_hosts": ["backend"],
      "credential_bindings": []
    }
  ]
}
```

The loader must:

```python
# infrastructure/scripts/workflow_registry.py
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CredentialBinding:
    node: str
    credential_type: str
    logical_name: str


@dataclass(frozen=True)
class WorkflowSpec:
    file: str
    name: str
    generation: str
    event_names: tuple[str, ...]
    webhook_paths: tuple[str, ...]
    callback_paths: tuple[str, ...]
    authentication: str
    managed: bool
    production_activation: bool
    test_only: bool
    activation_order: int | None
    allowed_target_hosts: tuple[str, ...]
    credential_bindings: tuple[CredentialBinding, ...]


@dataclass(frozen=True)
class WorkflowRegistry:
    credentials: dict[str, str]
    workflows: tuple[WorkflowSpec, ...]

    def by_file(self, name: str) -> WorkflowSpec:
        matches = [item for item in self.workflows if item.file == name]
        if len(matches) != 1:
            raise KeyError(name)
        return matches[0]

    def managed_files(self) -> tuple[str, ...]:
        return tuple(
            item.file
            for item in sorted(
                (item for item in self.workflows if item.managed),
                key=lambda item: item.activation_order or 10_000,
            )
        )

    def activation_order(self) -> tuple[str, ...]:
        return tuple(
            item.file
            for item in sorted(
                (
                    item
                    for item in self.workflows
                    if item.managed and item.production_activation
                ),
                key=lambda item: item.activation_order or 10_000,
            )
        )

    def test_only_files(self) -> tuple[str, ...]:
        return tuple(
            item.file for item in self.workflows if item.managed and item.test_only
        )

    def required_credentials(self, file_name: str) -> tuple[CredentialBinding, ...]:
        return self.by_file(file_name).credential_bindings


def load_registry(
    path: Path,
    *,
    workflow_root: Path | None = None,
) -> WorkflowRegistry:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "v1":
        raise ValueError("unsupported workflow registry schema")
    credential_types = {
        name: spec["type"] for name, spec in (raw.get("credentials") or {}).items()
    }
    workflows: list[WorkflowSpec] = []
    for value in raw.get("workflows") or []:
        bindings = tuple(
            CredentialBinding(
                node=item["node"],
                credential_type=item["credential_type"],
                logical_name=item["logical_name"],
            )
            for item in value.get("credential_bindings") or []
        )
        workflows.append(
            WorkflowSpec(
                file=value["file"],
                name=value["name"],
                generation=value["generation"],
                event_names=tuple(value.get("event_names") or []),
                webhook_paths=tuple(value.get("webhook_paths") or []),
                callback_paths=tuple(value.get("callback_paths") or []),
                authentication=value["authentication"],
                managed=bool(value["managed"]),
                production_activation=bool(value["production_activation"]),
                test_only=bool(value.get("test_only", False)),
                activation_order=value.get("activation_order"),
                allowed_target_hosts=tuple(value.get("allowed_target_hosts") or []),
                credential_bindings=bindings,
            )
        )

    files = [item.file for item in workflows]
    names = [item.name for item in workflows]
    paths = [path for item in workflows for path in item.webhook_paths]
    orders = [
        item.activation_order
        for item in workflows
        if item.production_activation and item.activation_order is not None
    ]
    for label, values in (
        ("file", files),
        ("name", names),
        ("webhook path", paths),
        ("activation order", orders),
    ):
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {label}")
    for workflow in workflows:
        if workflow.generation == "v2" and workflow.authentication != "native_header_hmac":
            raise ValueError(f"{workflow.file}: v2 requires native_header_hmac")
        if workflow.test_only and (
            not workflow.managed
            or workflow.production_activation
            or workflow.generation != "v2"
        ):
            raise ValueError(
                f"{workflow.file}: test_only requires managed non-production v2"
            )
        for binding in workflow.credential_bindings:
            expected_type = credential_types.get(binding.logical_name)
            if expected_type is None:
                raise ValueError(
                    f"{workflow.file}: unknown logical credential {binding.logical_name}"
                )
            if expected_type != binding.credential_type:
                raise ValueError(f"{workflow.file}: credential type mismatch")

    root = workflow_root or path.parent / "workflows"
    disk = {item.name for item in root.glob("*.json")}
    if set(files) != disk:
        raise ValueError(
            f"registry/disk mismatch: missing={sorted(disk - set(files))}, "
            f"unknown={sorted(set(files) - disk)}"
        )
    return WorkflowRegistry(credentials=credential_types, workflows=tuple(workflows))
```

Add a CLI that prints JSON arrays for the four specified commands and exits nonzero
on validation failure. The importer will call the CLI instead of maintaining its own
file list.

- [x] **Step 4: Run loader tests and current workflow verification**

Run:

```bash
PYTHONPATH=. python3 -m pytest infrastructure/tests/test_workflow_registry.py -q
python3 infrastructure/scripts/workflow_registry.py managed-files --json
python3 infrastructure/scripts/verify-workflows.py
```

Expected: tests pass; CLI prints the four managed files in activation order; the existing v1 verifier still passes.

- [x] **Step 5: Commit the central registry**

```bash
git add \
  n8n/workflow-registry.json \
  infrastructure/scripts/workflow_registry.py \
  infrastructure/tests/test_workflow_registry.py
git commit -m "feat(n8n): add central workflow contract registry"
```

### Task 4: Local n8n Signature Nodes

**Files:**
- Create: `n8n/custom-nodes/n8n-nodes-pwr/package.json`
- Create mechanically: `n8n/custom-nodes/n8n-nodes-pwr/package-lock.json`
- Create: `n8n/custom-nodes/n8n-nodes-pwr/tsconfig.json`
- Create: `n8n/custom-nodes/n8n-nodes-pwr/src/security/pwrSignature.ts`
- Create: `n8n/custom-nodes/n8n-nodes-pwr/src/security/signedRequest.ts`
- Create: `n8n/custom-nodes/n8n-nodes-pwr/src/credentials/PwrInboundHmac.credentials.ts`
- Create: `n8n/custom-nodes/n8n-nodes-pwr/src/credentials/PwrOutboundHmac.credentials.ts`
- Create: `n8n/custom-nodes/n8n-nodes-pwr/src/nodes/PwrSignatureGate/PwrSignatureGate.node.ts`
- Create: `n8n/custom-nodes/n8n-nodes-pwr/src/nodes/PwrSignedHttpRequest/PwrSignedHttpRequest.node.ts`
- Create: `n8n/custom-nodes/n8n-nodes-pwr/test/pwrSignature.test.ts`
- Create: `n8n/custom-nodes/n8n-nodes-pwr/test/signedRequest.test.ts`

**Interfaces:**
- Consumes: the frozen Task 2 signature vector and n8n Webhook `rawBody` binary property `data`.
- Produces: credential types `pwrInboundHmac` and `pwrOutboundHmac`, node types `pwrSignatureGate` and `pwrSignedHttpRequest`, `verifyInbound(input) -> VerifiedInbound`, and `buildSignedRequest(input) -> PreparedSignedRequest`.

- [ ] **Step 1: Create the package manifest and failing cross-runtime tests**

```json
{
  "name": "n8n-nodes-pwr",
  "version": "0.1.0",
  "description": "Private signed transport nodes for Picking Warehouse Runtime",
  "license": "UNLICENSED",
  "private": true,
  "main": "dist/src/index.js",
  "files": ["dist"],
  "engines": {"node": ">=22.16"},
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "npm run build && node --test dist/test/*.test.js"
  },
  "keywords": ["n8n-community-node-package"],
  "n8n": {
    "n8nNodesApiVersion": 1,
    "credentials": [
      "dist/src/credentials/PwrInboundHmac.credentials.js",
      "dist/src/credentials/PwrOutboundHmac.credentials.js"
    ],
    "nodes": [
      "dist/src/nodes/PwrSignatureGate/PwrSignatureGate.node.js",
      "dist/src/nodes/PwrSignedHttpRequest/PwrSignedHttpRequest.node.js"
    ]
  },
  "peerDependencies": {
    "n8n-workflow": "2.13.1"
  },
  "devDependencies": {
    "@types/node": "22.15.30",
    "n8n-workflow": "2.13.1",
    "typescript": "5.8.3"
  }
}
```

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "CommonJS",
    "moduleResolution": "Node",
    "rootDir": ".",
    "outDir": "dist",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "declaration": true
  },
  "include": ["src/**/*.ts", "test/**/*.ts"]
}
```

```typescript
// n8n/custom-nodes/n8n-nodes-pwr/test/pwrSignature.test.ts
import assert from "node:assert/strict";
import test from "node:test";
import {
  buildSigningBytes,
  sha256Hex,
  signHmac,
  verifyInbound,
} from "../src/security/pwrSignature";

const body = Buffer.from(
  '{"event_id":"a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32"}',
  "utf8",
);

test("matches the frozen Python HMAC vector", () => {
  assert.equal(
    sha256Hex(body),
    "cdc9aeda6396616866f863a30ce8507232b2cecd6cdd68c206c24b8c128751fc",
  );
  const signingBytes = buildSigningBytes({
    method: "POST",
    target: "/webhook/quality-assessment-v2",
    deliveryGeneration: "1",
    timestamp: "1760000000",
    nonce: "123e4567-e89b-42d3-a456-426614174000",
    bodySha256: sha256Hex(body),
  });
  assert.equal(
    signHmac(Buffer.from("0".repeat(32), "utf8"), signingBytes),
    "v1=6466f16aca767c63504c2d002d729c35fdc12df969060bc4e7e76fd0c69a43d4",
  );
});

test("accepts previous key and rejects a query", () => {
  const input = {
    expectedMethod: "POST",
    expectedTarget: "/webhook/quality-assessment-v2",
    query: {},
    rawBody: body,
    nowSeconds: 1760000000,
    maxSkewSeconds: 300,
    headers: {
      "x-pwr-key-id": "previous",
      "x-pwr-timestamp": "1760000000",
      "x-pwr-nonce": "123e4567-e89b-42d3-a456-426614174000",
      "x-pwr-signed-method": "POST",
      "x-pwr-signed-target": "/webhook/quality-assessment-v2",
      "x-pwr-delivery-generation": "1",
      "x-pwr-signature":
        "v1=6466f16aca767c63504c2d002d729c35fdc12df969060bc4e7e76fd0c69a43d4",
    },
    keys: {
      active: {keyId: "active", secret: Buffer.from("1".repeat(32))},
      previous: {keyId: "previous", secret: Buffer.from("0".repeat(32))},
    },
  };
  assert.equal(verifyInbound(input).keyId, "previous");
  assert.throws(
    () => verifyInbound({...input, query: {debug: "1"}}),
    /query_not_allowed/,
  );
});
```

```typescript
// n8n/custom-nodes/n8n-nodes-pwr/test/signedRequest.test.ts
import assert from "node:assert/strict";
import test from "node:test";
import {buildSignedRequest} from "../src/security/signedRequest";

test("signs the same JSON bytes that the sender receives", () => {
  const prepared = buildSignedRequest({
    baseUrl: "http://backend:8000",
    method: "POST",
    target: "/api/internal/n8n/v2/events/accept",
    body: Buffer.from('{"event_id":"event-1"}', "utf8"),
    contentType: "application/json",
    deliveryGeneration: 3,
    idempotencyKey: "callback-1",
    timestamp: 1760000000,
    nonce: "123e4567-e89b-42d3-a456-426614174000",
    keyId: "n2b-test",
    secret: Buffer.from("2".repeat(32)),
  });
  assert.equal(prepared.url, "http://backend:8000/api/internal/n8n/v2/events/accept");
  assert.equal(prepared.body.toString("utf8"), '{"event_id":"event-1"}');
  assert.equal(prepared.headers["X-PWR-Delivery-Generation"], "3");
  assert.equal(prepared.headers["Idempotency-Key"], "callback-1");
});

test("rejects absolute, redirected, queried, and cross-host targets", () => {
  const common = {
    baseUrl: "http://backend:8000",
    method: "POST",
    body: Buffer.alloc(0),
    contentType: "application/octet-stream",
    deliveryGeneration: 1,
    idempotencyKey: "id-1",
    timestamp: 1760000000,
    nonce: "123e4567-e89b-42d3-a456-426614174000",
    keyId: "n2b-test",
    secret: Buffer.from("2".repeat(32)),
  };
  for (const target of [
    "http://attacker.invalid/x",
    "//attacker.invalid/x",
    "/safe?redirect=http://attacker.invalid",
    "/safe#fragment",
  ]) {
    assert.throws(() => buildSignedRequest({...common, target}), /invalid_target/);
  }
});
```

- [ ] **Step 2: Generate the lock file and confirm tests fail**

Run:

```bash
cd n8n/custom-nodes/n8n-nodes-pwr
npm install --package-lock-only --ignore-scripts
npm ci
npm test
```

Expected: TypeScript compilation fails because the two security modules do not
exist. Keep the generated lock file and include it in this task's Step 5 commit; do
not hand-edit it.

- [ ] **Step 3: Implement pure cryptography, credentials, and both nodes**

Use this complete signature core:

```typescript
// src/security/pwrSignature.ts
import {
  createHash,
  createHmac,
  timingSafeEqual,
} from "node:crypto";

export type HmacKey = {keyId: string; secret: Buffer};
export type HmacKeys = {active: HmacKey; previous?: HmacKey};

export type SigningFields = {
  method: string;
  target: string;
  deliveryGeneration: string;
  timestamp: string;
  nonce: string;
  bodySha256: string;
};

export type VerifyInput = {
  expectedMethod: string;
  expectedTarget: string;
  headers: Record<string, unknown>;
  query: Record<string, unknown>;
  rawBody: Buffer;
  keys: HmacKeys;
  nowSeconds: number;
  maxSkewSeconds: number;
};

export type VerifiedInbound = {
  keyId: string;
  timestamp: number;
  nonce: string;
  signedMethod: string;
  signedTarget: string;
  deliveryGeneration: number;
  bodySha256: string;
};

export class PwrSignatureError extends Error {
  constructor(
    public readonly statusCode: number,
    public readonly reasonCode: string,
  ) {
    super(reasonCode);
  }
}

const generationPattern = /^[1-9][0-9]*$/;
const noncePattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const signaturePattern = /^v1=[0-9a-f]{64}$/;

export function decodeBase64Secret(name: string, encoded: string): Buffer {
  const secret = Buffer.from(encoded, "base64");
  if (
    secret.length < 32 ||
    secret.toString("base64").replace(/=+$/, "") !== encoded.replace(/=+$/, "")
  ) {
    throw new Error(`${name}_must_be_valid_base64_with_32_bytes`);
  }
  return secret;
}

export function sha256Hex(body: Buffer): string {
  return createHash("sha256").update(body).digest("hex");
}

export function buildSigningBytes(fields: SigningFields): Buffer {
  if (!generationPattern.test(fields.deliveryGeneration)) {
    throw new PwrSignatureError(400, "invalid_delivery_generation");
  }
  return Buffer.from(
    [
      fields.method,
      fields.target,
      fields.deliveryGeneration,
      fields.timestamp,
      fields.nonce,
      fields.bodySha256,
    ].join("\n"),
    "utf8",
  );
}

export function signHmac(secret: Buffer, signingBytes: Buffer): string {
  return `v1=${createHmac("sha256", secret).update(signingBytes).digest("hex")}`;
}

function header(headers: Record<string, unknown>, name: string): string {
  const value = headers[name] ?? headers[name.toLowerCase()];
  if (typeof value !== "string" || value.length === 0) {
    throw new PwrSignatureError(401, "missing_signature_header");
  }
  return value;
}

export function verifyInbound(input: VerifyInput): VerifiedInbound {
  if (Object.keys(input.query).length !== 0) {
    throw new PwrSignatureError(400, "query_not_allowed");
  }
  const keyId = header(input.headers, "x-pwr-key-id");
  const timestampText = header(input.headers, "x-pwr-timestamp");
  const nonce = header(input.headers, "x-pwr-nonce");
  const method = header(input.headers, "x-pwr-signed-method");
  const target = header(input.headers, "x-pwr-signed-target");
  const generation = header(input.headers, "x-pwr-delivery-generation");
  const supplied = header(input.headers, "x-pwr-signature");
  const key = [input.keys.active, input.keys.previous].find(
    (candidate) => candidate?.keyId === keyId,
  );
  if (!key) {
    throw new PwrSignatureError(401, "unknown_key_id");
  }
  if (
    !/^[0-9]+$/.test(timestampText) ||
    !noncePattern.test(nonce) ||
    !generationPattern.test(generation)
  ) {
    throw new PwrSignatureError(400, "malformed_signature_metadata");
  }
  const timestamp = Number(timestampText);
  if (
    !Number.isSafeInteger(timestamp) ||
    Math.abs(input.nowSeconds - timestamp) > input.maxSkewSeconds
  ) {
    throw new PwrSignatureError(409, "timestamp_outside_window");
  }
  if (method !== input.expectedMethod || target !== input.expectedTarget) {
    throw new PwrSignatureError(401, "signed_request_mismatch");
  }
  if (!signaturePattern.test(supplied)) {
    throw new PwrSignatureError(401, "malformed_signature");
  }
  const bodySha256 = sha256Hex(input.rawBody);
  const expected = signHmac(
    key.secret,
    buildSigningBytes({
      method,
      target,
      deliveryGeneration: generation,
      timestamp: timestampText,
      nonce,
      bodySha256,
    }),
  );
  const suppliedBytes = Buffer.from(supplied, "utf8");
  const expectedBytes = Buffer.from(expected, "utf8");
  if (
    suppliedBytes.length !== expectedBytes.length ||
    !timingSafeEqual(suppliedBytes, expectedBytes)
  ) {
    throw new PwrSignatureError(401, "invalid_signature");
  }
  return {
    keyId,
    timestamp,
    nonce,
    signedMethod: method,
    signedTarget: target,
    deliveryGeneration: Number(generation),
    bodySha256,
  };
}
```

Use this byte-preserving outbound builder:

```typescript
// src/security/signedRequest.ts
import {buildSigningBytes, sha256Hex, signHmac} from "./pwrSignature";

export type SignedRequestInput = {
  baseUrl: string;
  method: string;
  target: string;
  body: Buffer;
  contentType: string;
  deliveryGeneration: number;
  idempotencyKey: string;
  timestamp: number;
  nonce: string;
  keyId: string;
  secret: Buffer;
  legacyCallbackSecret?: string;
};

export type PreparedSignedRequest = {
  url: string;
  headers: Record<string, string>;
  body: Buffer;
};

export function buildSignedRequest(input: SignedRequestInput): PreparedSignedRequest {
  if (
    !input.target.startsWith("/") ||
    input.target.startsWith("//") ||
    input.target.includes("?") ||
    input.target.includes("#") ||
    input.target.includes("://")
  ) {
    throw new Error("invalid_target");
  }
  const base = new URL(input.baseUrl);
  if (base.pathname !== "/" || base.search || base.hash) {
    throw new Error("invalid_base_url");
  }
  const url = new URL(input.target, base);
  if (url.origin !== base.origin || `${url.pathname}` !== input.target) {
    throw new Error("invalid_target");
  }
  const deliveryGeneration = String(input.deliveryGeneration);
  const signature = signHmac(
    input.secret,
    buildSigningBytes({
      method: input.method,
      target: input.target,
      deliveryGeneration,
      timestamp: String(input.timestamp),
      nonce: input.nonce,
      bodySha256: sha256Hex(input.body),
    }),
  );
  const headers: Record<string, string> = {
    "Content-Type": input.contentType,
    "Idempotency-Key": input.idempotencyKey,
    "X-PWR-Key-Id": input.keyId,
    "X-PWR-Timestamp": String(input.timestamp),
    "X-PWR-Nonce": input.nonce,
    "X-PWR-Signed-Method": input.method,
    "X-PWR-Signed-Target": input.target,
    "X-PWR-Delivery-Generation": deliveryGeneration,
    "X-PWR-Signature": signature,
  };
  if (input.legacyCallbackSecret) {
    headers["X-N8N-Callback-Secret"] = input.legacyCallbackSecret;
  }
  return {url: url.toString(), headers, body: input.body};
}
```

Credential classes expose only these password-backed fields:

```typescript
// src/credentials/PwrInboundHmac.credentials.ts
import type {ICredentialType, INodeProperties} from "n8n-workflow";

export class PwrInboundHmac implements ICredentialType {
  name = "pwrInboundHmac";
  displayName = "PWR Inbound HMAC";
  properties: INodeProperties[] = [
    {displayName: "Active Key ID", name: "activeKeyId", type: "string", default: "", required: true},
    {displayName: "Active Secret Base64", name: "activeSecretBase64", type: "string", typeOptions: {password: true}, default: "", required: true},
    {displayName: "Previous Key ID", name: "previousKeyId", type: "string", default: ""},
    {displayName: "Previous Secret Base64", name: "previousSecretBase64", type: "string", typeOptions: {password: true}, default: ""},
  ];
}
```

```typescript
// src/credentials/PwrOutboundHmac.credentials.ts
import type {ICredentialType, INodeProperties} from "n8n-workflow";

export class PwrOutboundHmac implements ICredentialType {
  name = "pwrOutboundHmac";
  displayName = "PWR Outbound HMAC";
  properties: INodeProperties[] = [
    {displayName: "Base URL", name: "baseUrl", type: "string", default: "http://backend:8000", required: true},
    {displayName: "Active Key ID", name: "activeKeyId", type: "string", default: "", required: true},
    {displayName: "Active Secret Base64", name: "activeSecretBase64", type: "string", typeOptions: {password: true}, default: "", required: true},
    {displayName: "Legacy Callback Secret", name: "legacyCallbackSecret", type: "string", typeOptions: {password: true}, default: ""},
  ];
}
```

`PWR Signature Gate` must call `await this.helpers.getBinaryDataBuffer(i, "data")`, pass `item.json.headers` and `item.json.query` into `verifyInbound`, and return exactly two outputs:

```typescript
const verifiedItem = {
  ...item,
  json: {
    ...item.json,
    pwr: {
      verified: true,
      key_id: verified.keyId,
      timestamp: verified.timestamp,
      nonce: verified.nonce,
      signed_method: verified.signedMethod,
      signed_target: verified.signedTarget,
      delivery_generation: verified.deliveryGeneration,
      body_sha256: verified.bodySha256,
    },
  },
};
```

Output 0 contains verified items and preserves their binary data. Output 1 contains only:

```typescript
{
  json: {
    pwr: {
      verified: false,
      status_code: error.statusCode,
      reason_code: error.reasonCode,
    },
  },
}
```

It must not put the raw body, supplied signature, or any credential field on the rejection output. Node parameters are `expectedMethod` and `expectedTarget`; both are fixed in workflow JSON and cannot be derived from request data. `maxSkewSeconds` is hard-coded to `300`.

`PWR Signed HTTP Request` must:

1. accept `method`, relative `target`, `bodyMode` (`none`, `json`, `binary`,
   `literalUtf8`), `jsonProperty`, `binaryProperty`, `literalBody`,
   `contentType`, `deliveryGenerationProperty`, `idempotencyKeyProperty`,
   `responseMode`, and `timeoutMs` capped at `30000`;
2. use `JSON.stringify(value)` once for JSON,
   `await this.helpers.getBinaryDataBuffer(i, property)` for binary, or
   `Buffer.from(literalBody, "utf8")` for the verifier-restricted synthetic
   test mode; never place the selected request bytes on the output item;
3. call `buildSignedRequest()` with `randomUUID()` and current Unix seconds;
4. call `this.helpers.httpRequest()` with the prepared `Buffer`, `json: false`, redirects disabled, and the credential-derived host;
5. reject any response redirect instead of following it;
6. return parsed JSON only when `responseMode=json`, otherwise return n8n binary data created from the exact response bytes.

No node may read `process.env`, accept a caller-supplied host, or expose a key through its output.
Unit tests assert the exact bytes and SHA-256 for all four body modes, including the
synthetic ZPL fixture, and prove that neither a successful nor failed request output
contains `literalBody`, binary data, or base64 request content. Task 14 enforces
that committed workflows may use `literalUtf8` only under a reviewed
`test_only=true` registry entry.

- [ ] **Step 4: Build and run both node test suites**

Run:

```bash
cd n8n/custom-nodes/n8n-nodes-pwr
npm ci
npm run build
npm test
npm pack --dry-run
```

Expected: TypeScript has zero errors, both test files pass, and the dry-run package contains only `dist`, manifest, readme/license metadata, and no source credentials or local secret files.

- [ ] **Step 5: Commit the custom node package**

```bash
git add n8n/custom-nodes/n8n-nodes-pwr
git commit -m "feat(n8n): add signed inbound and outbound custom nodes"
```

### Task 5: Odoo 19 Integration Add-on, Groups, Sessions, and Throttle

**Files:**
- Create: `odoo/addons/picking_assistant_integration/__init__.py`
- Create: `odoo/addons/picking_assistant_integration/__manifest__.py`
- Create: `odoo/addons/picking_assistant_integration/models/__init__.py`
- Create: `odoo/addons/picking_assistant_integration/models/api_security.py`
- Create: `odoo/addons/picking_assistant_integration/models/session.py`
- Create: `odoo/addons/picking_assistant_integration/models/auth_throttle.py`
- Create: `odoo/addons/picking_assistant_integration/security/integration_security.xml`
- Create: `odoo/addons/picking_assistant_integration/security/ir.model.access.csv`
- Create: `odoo/addons/picking_assistant_integration/data/ir_cron.xml`
- Create: `odoo/addons/picking_assistant_integration/tests/__init__.py`
- Create: `odoo/addons/picking_assistant_integration/tests/common.py`
- Create: `odoo/addons/picking_assistant_integration/tests/test_security.py`
- Create: `odoo/addons/picking_assistant_integration/tests/test_session_throttle.py`

**Interfaces:**
- Consumes: Odoo 19 only; the API service account is a member of `picking_assistant_integration.group_api_service`.
- Produces: groups `group_picker`, `group_supervisor`, `group_api_service`; `_require_api_service() -> None`; `res.users.api_get_picker_principal(user_id) -> dict`; session and throttle RPCs listed below.

- [ ] **Step 1: Write failing Odoo security and session tests**

```python
# odoo/addons/picking_assistant_integration/tests/common.py
from odoo.tests.common import TransactionCase, new_test_user


class IntegrationCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.api_user = new_test_user(
            cls.env,
            login="pwr_api",
            groups="base.group_user,picking_assistant_integration.group_api_service",
        )
        cls.picker = new_test_user(
            cls.env,
            login="mina",
            groups="base.group_user,picking_assistant_integration.group_picker",
        )
        cls.supervisor = new_test_user(
            cls.env,
            login="supervisor",
            groups="base.group_user,picking_assistant_integration.group_supervisor",
        )
```

```python
# odoo/addons/picking_assistant_integration/tests/test_security.py
from odoo.exceptions import AccessError

from .common import IntegrationCase


class TestIntegrationSecurity(IntegrationCase):
    def test_picker_cannot_call_session_rpc_or_raw_crud(self):
        sessions = self.env["picking.assistant.session"].with_user(self.picker)
        with self.assertRaises(AccessError):
            sessions.api_get_session("0" * 64)
        with self.assertRaises(AccessError):
            sessions.create(
                {
                    "session_id": "session",
                    "token_hash": "0" * 64,
                    "csrf_hash": "1" * 64,
                    "user_id": self.picker.id,
                    "device_id": "device",
                    "roles_json": '["picker"]',
                    "expires_at": "2026-07-24 00:00:00",
                }
            )

    def test_api_user_can_call_rpc_but_cannot_raw_write(self):
        users = self.env["res.users"].with_user(self.api_user)
        principal = users.api_get_picker_principal(self.picker.id)
        self.assertEqual(principal["roles"], ["picker"])
        with self.assertRaises(AccessError):
            self.env["picking.assistant.session"].with_user(self.api_user).create({})
```

```python
# odoo/addons/picking_assistant_integration/tests/test_session_throttle.py
from datetime import timedelta

from odoo import fields

from .common import IntegrationCase


class TestSessionAndThrottle(IntegrationCase):
    def test_session_stores_hashes_and_returns_sanitized_principal(self):
        model = self.env["picking.assistant.session"].with_user(self.api_user)
        expires_at = fields.Datetime.now() + timedelta(hours=8)
        model.api_create_session(
            "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
            "0" * 64,
            "1" * 64,
            self.picker.id,
            "device-42",
            ["picker"],
            fields.Datetime.to_string(expires_at),
        )
        result = model.api_get_session("0" * 64, touch=True)
        self.assertEqual(result["picker_user_id"], self.picker.id)
        self.assertNotIn("token_hash", result)
        self.assertNotIn("csrf_hash", result)

    def test_fifth_failure_locks_for_window_and_success_clears(self):
        throttle = self.env["picking.assistant.auth.throttle"].with_user(self.api_user)
        for _index in range(5):
            state = throttle.api_record_login_result("mina", "a" * 64, False)
        self.assertFalse(state["allowed"])
        self.assertTrue(state["locked_until"])
        state = throttle.api_record_login_result("mina", "a" * 64, True)
        self.assertTrue(state["allowed"])
        self.assertEqual(state["failure_count"], 0)
```

- [ ] **Step 2: Run the Odoo test tag and confirm the add-on is missing**

Run on a Docker-capable host; in this WSL environment the executable is also available at `/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe`:

```bash
docker compose --profile odoo19-trial run --rm --no-deps odoo19-trial \
  --database masterfischer_o19_foundation_test \
  --db-filter '^masterfischer_o19_foundation_test$' \
  --workers=0 --max-cron-threads=0 --without-demo=all \
  --init picking_assistant_integration \
  --test-tags /picking_assistant_integration \
  --stop-after-init
```

Expected: module loading fails because `picking_assistant_integration` does not exist.

- [ ] **Step 3: Create the protected Odoo 19 add-on**

Use this manifest and import order:

```python
# __manifest__.py
{
    "name": "Picking Assistant Integration",
    "version": "19.0.1.0.0",
    "author": "Mobile Picking Assistant",
    "category": "Inventory/Technical",
    "summary": "Secure sessions and durable integration primitives",
    "depends": ["base"],
    "data": [
        "security/integration_security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
```

Define the API guard and picker role lookup:

```python
# models/api_security.py
from odoo import api, models
from odoo.exceptions import AccessError


class PickingAssistantApiMixin(models.AbstractModel):
    _name = "picking.assistant.api.mixin"
    _description = "Picking Assistant API Guard"

    def _require_api_service(self):
        if not self.env.user.has_group(
            "picking_assistant_integration.group_api_service"
        ):
            raise AccessError("Integration API group required.")


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def api_get_picker_principal(self, user_id):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        user = self.sudo().browse(int(user_id)).exists()
        if not user or not user.active or user.share:
            return {"allowed": False}
        roles = []
        if user.has_group("picking_assistant_integration.group_picker"):
            roles.append("picker")
        if user.has_group("picking_assistant_integration.group_supervisor"):
            roles.append("supervisor")
        return {
            "allowed": bool(roles),
            "picker_user_id": user.id,
            "picker_name": user.name,
            "roles": roles,
        }
```

The session model has unique Odoo-19 constraints and never returns hashes:

```python
# models/session.py
import json

from odoo import api, fields, models


class PickingAssistantSession(models.Model):
    _name = "picking.assistant.session"
    _description = "Picking Assistant Session"
    _order = "create_date desc"

    session_id = fields.Char(required=True, index=True, readonly=True)
    token_hash = fields.Char(required=True, index=True, readonly=True)
    csrf_hash = fields.Char(required=True, readonly=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    device_id = fields.Char(required=True, readonly=True)
    roles_json = fields.Text(required=True, readonly=True)
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    expires_at = fields.Datetime(required=True, index=True, readonly=True)
    revoked_at = fields.Datetime(index=True, readonly=True)
    last_seen_at = fields.Datetime(readonly=True)
    roles_checked_at = fields.Datetime(required=True, default=fields.Datetime.now)

    _session_id_unique = models.Constraint(
        "UNIQUE(session_id)", "Session ID must be unique."
    )
    _token_hash_unique = models.Constraint(
        "UNIQUE(token_hash)", "Session token hash must be unique."
    )

    def _api_payload(self):
        self.ensure_one()
        return {
            "session_id": self.session_id,
            "picker_user_id": self.user_id.id,
            "picker_name": self.user_id.name,
            "device_id": self.device_id,
            "roles": json.loads(self.roles_json),
            "expires_at": fields.Datetime.to_string(self.expires_at),
            "revoked_at": fields.Datetime.to_string(self.revoked_at)
            if self.revoked_at
            else False,
            "last_seen_at": fields.Datetime.to_string(self.last_seen_at)
            if self.last_seen_at
            else False,
            "roles_checked_at": fields.Datetime.to_string(self.roles_checked_at),
        }

    @api.model
    def api_create_session(
        self,
        session_id,
        token_hash,
        csrf_hash,
        user_id,
        device_id,
        roles,
        expires_at,
    ):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        session = self.sudo().create(
            {
                "session_id": session_id,
                "token_hash": token_hash,
                "csrf_hash": csrf_hash,
                "user_id": int(user_id),
                "device_id": device_id,
                "roles_json": json.dumps(sorted(set(roles))),
                "expires_at": expires_at,
            }
        )
        return session._api_payload()

    @api.model
    def api_get_session(self, token_hash, touch=False):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        session = self.sudo().search([("token_hash", "=", token_hash)], limit=1)
        now = fields.Datetime.now()
        if (
            not session
            or session.revoked_at
            or not session.expires_at
            or session.expires_at <= now
        ):
            return False
        if touch:
            session.last_seen_at = now
        return session._api_payload()

    @api.model
    def api_rotate_csrf(self, session_id, csrf_hash):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        session = self.sudo().search(
            [("session_id", "=", session_id), ("revoked_at", "=", False)],
            limit=1,
        )
        if not session or session.expires_at <= fields.Datetime.now():
            return False
        session.write({"csrf_hash": csrf_hash, "last_seen_at": fields.Datetime.now()})
        return True

    @api.model
    def api_mark_roles_checked(self, session_id, roles):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        session = self.sudo().search([("session_id", "=", session_id)], limit=1)
        if not session:
            return False
        session.write(
            {
                "roles_json": json.dumps(sorted(set(roles))),
                "roles_checked_at": fields.Datetime.now(),
            }
        )
        return session._api_payload()

    @api.model
    def api_revoke_session(self, session_id):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        sessions = self.sudo().search(
            [("session_id", "=", session_id), ("revoked_at", "=", False)]
        )
        sessions.write({"revoked_at": fields.Datetime.now()})
        return bool(sessions)

    @api.model
    def api_revoke_user_sessions(self, user_id):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        sessions = self.sudo().search(
            [("user_id", "=", int(user_id)), ("revoked_at", "=", False)]
        )
        sessions.write({"revoked_at": fields.Datetime.now()})
        return len(sessions)
```

The throttle model uses a unique `(login_key, source_ip_hmac)` constraint. `api_record_login_result()` locks the existing row with `SELECT ... FOR UPDATE`; creation races are contained by `with self.env.cr.savepoint():` and `IntegrityError` is caught outside that savepoint. It implements:

```python
api_check_login(login_key: str, source_ip_hmac: str) -> {
    "allowed": bool,
    "failure_count": int,
    "locked_until": str | False,
}

api_record_login_result(
    login_key: str,
    source_ip_hmac: str,
    succeeded: bool,
) -> {
    "allowed": bool,
    "failure_count": int,
    "locked_until": str | False,
}
```

On failure 1, it starts a 15-minute window; failure 5 sets `locked_until` to the window end. A success sets count to zero and clears the lock. Rows set `expires_at=now+24 hours`. No code in this add-on calls `env.cr.rollback()`.

Define `group_supervisor` with `group_picker` as an implied group. Define `group_api_service` independently. `base.group_system` gets full CRUD on integration models; `group_api_service` gets read-only ACL and mutates only through guarded public methods. Picker and supervisor groups get no model ACL.

Add a ten-minute cron that deletes throttle rows past `expires_at`, and a daily cron that deletes sessions only seven days after expiry/revocation. Cron methods process bounded batches and call `self.env["ir.cron"]._commit_progress(processed, remaining=remaining)`.

- [ ] **Step 4: Run real Odoo 19 tests and static import checks**

Run:

```bash
python3 -m compileall -q odoo/addons/picking_assistant_integration
docker compose --profile odoo19-trial run --rm --no-deps odoo19-trial \
  --database masterfischer_o19_foundation_test \
  --db-filter '^masterfischer_o19_foundation_test$' \
  --workers=0 --max-cron-threads=0 --without-demo=all \
  --init picking_assistant_integration \
  --test-tags /picking_assistant_integration \
  --stop-after-init
```

Expected: compile succeeds; Odoo reports zero failed tests. If the Odoo-19 runtime fact gate has changed privilege XML or RPC facts, update only the integration add-on to the verified Odoo-19 form and attach that fact to the task review.

- [ ] **Step 5: Commit the session persistence**

```bash
git add odoo/addons/picking_assistant_integration
git commit -m "feat(odoo): add protected picker sessions and login throttle"
```

### Task 6: Picker Session Service and Auth Router

**Files:**
- Create: `backend/app/services/auth_sessions.py`
- Create: `backend/app/routers/auth.py`
- Create: `backend/tests/test_auth_sessions.py`
- Create: `backend/tests/test_auth_routes.py`
- Modify: `backend/app/services/odoo_client.py` in `OdooClient`
- Modify: `backend/app/dependencies.py` to provide the session service and principal
- Modify: `backend/app/main.py` to include the auth router
- Modify: `odoo/addons/picking_assistant_integration/models/session.py` to validate CSRF hashes server-side
- Modify: `odoo/addons/picking_assistant_integration/tests/test_session_throttle.py`

**Interfaces:**
- Consumes: `Principal` and settings from Task 1; Odoo session/throttle RPCs from Task 5.
- Produces: `AuthenticationFailed`, `SessionService`, `CreatedSession`, `parse_session_token(token: str) -> SessionTokenHint`, `source_ip_hmac(request: Request, secret: bytes, trusted_peers: set[str]) -> str`, `get_session_service()`, and `get_current_principal(request: Request) -> Principal`.

- [ ] **Step 1: Write failing service and HTTP contract tests**

```python
# backend/tests/test_auth_sessions.py
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.models.auth import PickerSessionLoginRequest
from app.services.auth_sessions import (
    AuthenticationFailed,
    SessionService,
    parse_session_token,
)


class FakeOdoo:
    def __init__(self, *, instance="o19", uid=7, allowed=True):
        self.instance = instance
        self.uid = uid
        self.allowed = allowed
        self.calls = []
        self.session = None

    async def authenticate_credentials(self, login, password):
        self.calls.append(("authenticate_credentials", login, password))
        return self.uid if password == "correct" else None

    async def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method, args))
        if method == "api_check_login":
            return {"allowed": True, "failure_count": 0, "locked_until": False}
        if method == "api_get_picker_principal":
            return {
                "allowed": self.allowed,
                "picker_user_id": self.uid,
                "picker_name": "Mina Muster",
                "roles": ["picker"],
            }
        if method == "api_record_login_result":
            return {"allowed": True, "failure_count": 0, "locked_until": False}
        if method == "api_create_session":
            self.session = {
                "session_id": args[0],
                "picker_user_id": self.uid,
                "picker_name": "Mina Muster",
                "device_id": args[4],
                "roles": ["picker"],
                "expires_at": args[6],
                "revoked_at": False,
                "roles_checked_at": "2026-07-23 12:00:00",
            }
            return self.session
        if method == "api_get_session":
            return self.session
        raise AssertionError((model, method, args))


@pytest.mark.asyncio
async def test_create_session_stores_only_hashes_and_binds_instance():
    odoo = FakeOdoo()
    service = SessionService(
        client_factory=lambda name: odoo if name == "o19" else None,
        instance_names={"o19"},
        throttle_secret=b"t" * 32,
        allowed_origins={"https://picking.test"},
        now=lambda: datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
    )
    created = await service.create_session(
        PickerSessionLoginRequest(
            login="mina",
            password="correct",
            device_id="123e4567-e89b-42d3-a456-426614174000",
            odoo_instance="o19",
        ),
        source_ip="192.0.2.10",
        origin="https://picking.test",
    )
    hint = parse_session_token(created.cookie_token)
    assert hint.odoo_instance == "o19"
    assert created.cookie_token.startswith("v1.o19.")
    create_call = next(call for call in odoo.calls if call[1] == "api_create_session")
    assert created.cookie_token not in create_call[2]
    assert created.csrf_token not in create_call[2]
    assert create_call[2][6] == "2026-07-23 20:00:00"
    resolved = await service.resolve_principal(created.cookie_token)
    assert resolved.expires_at.tzinfo is timezone.utc


@pytest.mark.asyncio
async def test_bad_password_and_disallowed_user_have_same_public_error():
    for uid, allowed, password in ((None, True, "bad"), (7, False, "correct")):
        service = SessionService(
            client_factory=lambda _name, uid=uid, allowed=allowed: FakeOdoo(
                uid=uid, allowed=allowed
            ),
            instance_names={"o19"},
            throttle_secret=b"t" * 32,
            allowed_origins={"https://picking.test"},
        )
        with pytest.raises(AuthenticationFailed, match="Anmeldung fehlgeschlagen"):
            await service.create_session(
                PickerSessionLoginRequest(
                    login="mina",
                    password=password,
                    device_id="123e4567-e89b-42d3-a456-426614174000",
                    odoo_instance="o19",
                ),
                source_ip="192.0.2.10",
                origin="https://picking.test",
            )


@pytest.mark.asyncio
async def test_manipulated_instance_hint_never_falls_back():
    clients = {"o19": FakeOdoo(instance="o19")}
    service = SessionService(
        client_factory=lambda name: clients[name],
        instance_names={"o19"},
        throttle_secret=b"t" * 32,
        allowed_origins={"https://picking.test"},
    )
    with pytest.raises(AuthenticationFailed):
        await service.resolve_principal("v1.local." + ("a" * 43))
    assert clients["o19"].calls == []
```

```python
# backend/tests/test_auth_routes.py
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.dependencies import get_session_service
from app.main import app
from app.models.auth import Principal
from app.services.auth_sessions import CreatedSession


class StubSessions:
    async def create_session(self, body, source_ip, origin):
        return CreatedSession(
            cookie_token="v1.o19." + ("a" * 43),
            csrf_token="b" * 43,
            principal=Principal(
                picker_user_id=7,
                picker_name="Mina Muster",
                device_id=str(body.device_id),
                odoo_instance="o19",
                roles=frozenset({"picker"}),
                session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
                expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
            ),
        )


def test_login_sets_exact_cookie_contract():
    app.dependency_overrides[get_session_service] = lambda: StubSessions()
    try:
        client = TestClient(app, base_url="https://picking.test")
        response = client.post(
            "/api/auth/picker-session",
            headers={"Origin": "https://picking.test"},
            json={
                "login": "mina",
                "password": "correct",
                "device_id": "123e4567-e89b-42d3-a456-426614174000",
                "odoo_instance": "o19",
            },
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "pwr_session=" in cookie
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=strict" in cookie
        assert "Path=/api" in cookie
        assert "Max-Age=28800" in cookie
    finally:
        app.dependency_overrides.clear()
```

Extend the Odoo test with:

```python
def test_csrf_hash_is_compared_inside_odoo(self):
    model = self.env["picking.assistant.session"].with_user(self.api_user)
    # Create the same session fixture as the first test.
    self.assertTrue(
        model.api_validate_csrf(
            "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88", "1" * 64
        )
    )
    self.assertFalse(
        model.api_validate_csrf(
            "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88", "2" * 64
        )
    )
```

- [ ] **Step 2: Run backend tests and confirm missing service/router**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_auth_sessions.py tests/test_auth_routes.py -q
```

Expected: collection fails for `auth_sessions`, `auth` router, or `get_session_service`.

- [ ] **Step 3: Implement credential auth, session lifecycle, and routes**

Add a credential check that never mutates the cached service identity:

```python
# backend/app/services/odoo_client.py, inside OdooClient
async def authenticate_credentials(self, login: str, password: str) -> int | None:
    uid = await self._json_rpc(
        "common",
        "authenticate",
        [self._db, login, password, {"interactive": True}],
    )
    return int(uid) if uid else None
```

Use this token and source identity logic:

```python
# backend/app/services/auth_sessions.py
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4

from fastapi import Request

from app.models.auth import (
    PickerSessionLoginRequest,
    Principal,
    SessionTokenHint,
)

_TOKEN_SECRET = re.compile(r"^[A-Za-z0-9_-]{43}$")
_INSTANCE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class AuthenticationFailed(Exception):
    pass


class CsrfFailed(Exception):
    pass


@dataclass(frozen=True)
class CreatedSession:
    cookie_token: str
    csrf_token: str
    principal: Principal


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def to_odoo_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Odoo datetime input must be timezone-aware")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def from_odoo_datetime(value: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return parsed.replace(tzinfo=timezone.utc)


def parse_session_token(token: str) -> SessionTokenHint:
    parts = token.split(".")
    if (
        len(parts) != 3
        or parts[0] != "v1"
        or not _INSTANCE.fullmatch(parts[1])
        or not _TOKEN_SECRET.fullmatch(parts[2])
    ):
        raise AuthenticationFailed("Ungueltige oder abgelaufene Sitzung.")
    return SessionTokenHint(
        version="v1",
        odoo_instance=parts[1],
        token_hash=_sha256(token),
    )


def request_source_ip(request: Request, trusted_peers: set[str]) -> str:
    if request.client is None:
        raise AuthenticationFailed("Anmeldung fehlgeschlagen.")
    peer = str(ipaddress.ip_address(request.client.host))
    if peer not in trusted_peers:
        return peer
    forwarded = request.headers.get("X-Forwarded-For", "")
    first = forwarded.split(",", 1)[0].strip()
    return str(ipaddress.ip_address(first)) if first else peer


def source_ip_key(source_ip: str, secret: bytes) -> str:
    packed = ipaddress.ip_address(source_ip).packed
    return hmac.new(secret, packed, hashlib.sha256).hexdigest()
```

`SessionService` uses an injected `client_factory(instance_name)` and `instance_names` set. Its concrete flow is:

```python
class SessionService:
    def __init__(
        self,
        *,
        client_factory,
        instance_names: set[str],
        throttle_secret: bytes,
        allowed_origins: set[str],
        now: Callable[[], datetime] = _utcnow,
        session_seconds: int = 28800,
        revalidate_seconds: int = 300,
    ):
        self._client_factory = client_factory
        self._instance_names = instance_names
        self._throttle_secret = throttle_secret
        self._allowed_origins = allowed_origins
        self._now = now
        self._session_seconds = session_seconds
        self._revalidate_seconds = revalidate_seconds

    def _require_origin(self, origin: str | None) -> None:
        if origin not in self._allowed_origins:
            raise CsrfFailed("Origin ist nicht erlaubt.")

    async def create_session(
        self,
        body: PickerSessionLoginRequest,
        *,
        source_ip: str,
        origin: str | None,
    ) -> CreatedSession:
        self._require_origin(origin)
        if body.odoo_instance not in self._instance_names:
            raise AuthenticationFailed("Anmeldung fehlgeschlagen.")
        odoo = self._client_factory(body.odoo_instance)
        login_key = body.login.casefold()
        ip_key = source_ip_key(source_ip, self._throttle_secret)
        throttle = await odoo.execute_kw(
            "picking.assistant.auth.throttle",
            "api_check_login",
            [login_key, ip_key],
        )
        if not throttle.get("allowed"):
            raise AuthenticationFailed("Anmeldung fehlgeschlagen.")

        uid = await odoo.authenticate_credentials(body.login, body.password)
        identity = (
            await odoo.execute_kw(
                "res.users", "api_get_picker_principal", [uid]
            )
            if uid
            else {"allowed": False}
        )
        if not uid or not identity.get("allowed"):
            await odoo.execute_kw(
                "picking.assistant.auth.throttle",
                "api_record_login_result",
                [login_key, ip_key, False],
            )
            raise AuthenticationFailed("Anmeldung fehlgeschlagen.")

        await odoo.execute_kw(
            "picking.assistant.auth.throttle",
            "api_record_login_result",
            [login_key, ip_key, True],
        )
        session_id = str(uuid4())
        cookie_token = f"v1.{body.odoo_instance}.{secrets.token_urlsafe(32)}"
        csrf_token = secrets.token_urlsafe(32)
        expires_at = self._now() + timedelta(seconds=self._session_seconds)
        stored = await odoo.execute_kw(
            "picking.assistant.session",
            "api_create_session",
            [
                session_id,
                _sha256(cookie_token),
                _sha256(csrf_token),
                uid,
                str(body.device_id),
                identity["roles"],
                to_odoo_datetime(expires_at),
            ],
        )
        principal = self._principal(body.odoo_instance, stored)
        return CreatedSession(
            cookie_token=cookie_token,
            csrf_token=csrf_token,
            principal=principal,
        )

    async def resolve_principal(
        self,
        token: str,
        *,
        force_revalidate: bool = False,
    ) -> Principal:
        hint = parse_session_token(token)
        if hint.odoo_instance not in self._instance_names:
            raise AuthenticationFailed("Ungueltige oder abgelaufene Sitzung.")
        odoo = self._client_factory(hint.odoo_instance)
        stored = await odoo.execute_kw(
            "picking.assistant.session",
            "api_get_session",
            [hint.token_hash, True],
        )
        if not stored:
            raise AuthenticationFailed("Ungueltige oder abgelaufene Sitzung.")
        principal = self._principal(hint.odoo_instance, stored)
        checked = from_odoo_datetime(stored["roles_checked_at"])
        needs_check = force_revalidate or (
            self._now() - checked
        ).total_seconds() >= self._revalidate_seconds
        if needs_check:
            identity = await odoo.execute_kw(
                "res.users",
                "api_get_picker_principal",
                [principal.picker_user_id],
            )
            if not identity.get("allowed"):
                await odoo.execute_kw(
                    "picking.assistant.session",
                    "api_revoke_user_sessions",
                    [principal.picker_user_id],
                )
                raise AuthenticationFailed("Ungueltige oder abgelaufene Sitzung.")
            stored = await odoo.execute_kw(
                "picking.assistant.session",
                "api_mark_roles_checked",
                [principal.session_id, identity["roles"]],
            )
            principal = self._principal(hint.odoo_instance, stored)
        return principal

    async def rotate_csrf(self, principal: Principal, origin: str | None) -> str:
        self._require_origin(origin)
        token = secrets.token_urlsafe(32)
        odoo = self._client_factory(principal.odoo_instance)
        rotated = await odoo.execute_kw(
            "picking.assistant.session",
            "api_rotate_csrf",
            [principal.session_id, _sha256(token)],
        )
        if not rotated:
            raise AuthenticationFailed("Ungueltige oder abgelaufene Sitzung.")
        return token

    async def validate_csrf(
        self,
        principal: Principal,
        token: str | None,
        origin: str | None,
    ) -> None:
        self._require_origin(origin)
        if not token:
            raise CsrfFailed("CSRF-Token fehlt.")
        odoo = self._client_factory(principal.odoo_instance)
        valid = await odoo.execute_kw(
            "picking.assistant.session",
            "api_validate_csrf",
            [principal.session_id, _sha256(token)],
        )
        if not valid:
            raise CsrfFailed("CSRF-Token ist ungueltig.")

    async def revoke(self, principal: Principal) -> None:
        await self._client_factory(principal.odoo_instance).execute_kw(
            "picking.assistant.session",
            "api_revoke_session",
            [principal.session_id],
        )

    @staticmethod
    def _principal(instance: str, stored: dict) -> Principal:
        return Principal(
            picker_user_id=int(stored["picker_user_id"]),
            picker_name=str(stored["picker_name"]),
            device_id=str(stored["device_id"]),
            odoo_instance=instance,
            roles=frozenset(stored["roles"]),
            session_id=str(stored["session_id"]),
            expires_at=from_odoo_datetime(stored["expires_at"]),
        )
```

Add this Odoo method so FastAPI never reads the stored CSRF hash:

```python
@api.model
def api_validate_csrf(self, session_id, candidate_hash):
    import secrets

    self.env["picking.assistant.api.mixin"]._require_api_service()
    session = self.sudo().search(
        [("session_id", "=", session_id), ("revoked_at", "=", False)],
        limit=1,
    )
    return bool(
        session
        and session.expires_at > fields.Datetime.now()
        and secrets.compare_digest(session.csrf_hash, candidate_hash)
    )
```

In `backend/app/dependencies.py`, construct one cached `SessionService` using `_get_cached_client`, the registry names, decoded throttle secret, configured origins, and trusted peers. `get_current_principal()` reads only `request.cookies[settings.session_cookie_name]`; it never reads identity/instance headers. Map `AuthenticationFailed` to `401` and clear no state server-side on a malformed token.

The auth router is:

```python
# backend/app/routers/auth.py
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from app.config import get_instance_registry, settings
from app.dependencies import get_current_principal, get_session_service
from app.models.auth import (
    CsrfResponse,
    PickerSessionLoginRequest,
    PickerSessionResponse,
    Principal,
    PrincipalResponse,
)
from app.services.auth_sessions import (
    AuthenticationFailed,
    CsrfFailed,
    SessionService,
    request_source_ip,
)

router = APIRouter(prefix="/auth")


@router.get("/instances")
def list_auth_instances() -> list[dict[str, str]]:
    return [
        {"name": profile.name, "display_name": profile.display_name}
        for profile in get_instance_registry().values()
    ]


@router.post("/picker-session", response_model=PickerSessionResponse)
async def create_picker_session(
    body: PickerSessionLoginRequest,
    request: Request,
    response: Response,
    service: SessionService = Depends(get_session_service),
):
    try:
        created = await service.create_session(
            body,
            source_ip=request_source_ip(
                request,
                {item.strip() for item in settings.trusted_caddy_peers.split(",")},
            ),
            origin=request.headers.get("Origin"),
        )
    except (AuthenticationFailed, CsrfFailed) as exc:
        raise HTTPException(status_code=401, detail="Anmeldung fehlgeschlagen.") from exc
    response.set_cookie(
        key=settings.session_cookie_name,
        value=created.cookie_token,
        max_age=settings.session_max_age_seconds,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/api",
    )
    return PickerSessionResponse(
        principal=PrincipalResponse.from_principal(created.principal),
        csrf_token=created.csrf_token,
    )


@router.get("/me", response_model=PrincipalResponse)
def get_me(principal: Principal = Depends(get_current_principal)):
    return PrincipalResponse.from_principal(principal)


@router.post("/csrf", response_model=CsrfResponse)
async def rotate_csrf(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    service: SessionService = Depends(get_session_service),
):
    try:
        return CsrfResponse(
            csrf_token=await service.rotate_csrf(
                principal, request.headers.get("Origin")
            )
        )
    except (AuthenticationFailed, CsrfFailed) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    principal: Principal = Depends(get_current_principal),
    service: SessionService = Depends(get_session_service),
):
    try:
        await service.validate_csrf(
            principal, x_csrf_token, request.headers.get("Origin")
        )
    except CsrfFailed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await service.revoke(principal)
    response.delete_cookie(settings.session_cookie_name, path="/api")
```

Include this router under `/api` before any authenticated application router. Do not
remove the old instance route until Task 16 establishes the complete route surface.

- [ ] **Step 4: Run backend and Odoo auth tests**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_auth_models.py \
  tests/test_auth_sessions.py \
  tests/test_auth_routes.py \
  tests/test_odoo_client.py \
  -q

cd ..
docker compose --profile odoo19-trial run --rm --no-deps odoo19-trial \
  --database masterfischer_o19_foundation_test \
  --db-filter '^masterfischer_o19_foundation_test$' \
  --workers=0 --max-cron-threads=0 --without-demo=all \
  --update picking_assistant_integration \
  --test-tags /picking_assistant_integration \
  --stop-after-init
```

Expected: all focused backend tests pass; Odoo reports zero failed integration tests.

- [ ] **Step 5: Commit the authenticated session API**

```bash
git add \
  backend/app/dependencies.py \
  backend/app/main.py \
  backend/app/routers/auth.py \
  backend/app/services/auth_sessions.py \
  backend/app/services/odoo_client.py \
  backend/tests/test_auth_routes.py \
  backend/tests/test_auth_sessions.py \
  odoo/addons/picking_assistant_integration/models/session.py \
  odoo/addons/picking_assistant_integration/tests/test_session_throttle.py
git commit -m "feat(auth): add instance-bound picker sessions and csrf"
```

### Task 7: Principal-First Dependencies and PWA Session Adapter

**Files:**
- Create: `backend/tests/test_auth_dependencies.py`
- Modify: `backend/app/dependencies.py`
- Modify: `backend/app/services/mobile_workflow.py`
- Modify: `backend/app/routers/n8n_internal.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_dependencies_instance.py`
- Modify: `backend/tests/test_instance_routing.py`
- Modify: `backend/tests/test_n8n_internal_routes.py`
- Modify: `pwa/js/api.js`
- Modify: `pwa/js/tests/api.test.mjs`

**Interfaces:**
- Consumes: `get_current_principal()` and `SessionService` from Task 6.
- Produces: `get_request_odoo_client(principal)`, `get_required_picker_identity(principal)`, `require_browser_csrf(...)`, browser-only `get_write_request_context(...)`, service-only `get_legacy_n8n_write_context(...)`, `require_roles(*roles)`, PWA `loginPickerSession`, `getCurrentSession`, `rotateCsrfToken`, `logoutPickerSession`, `getCsrfToken`, and `setCsrfToken`.

- [ ] **Step 1: Write failing dependency and PWA authority tests**

```python
# backend/tests/test_auth_dependencies.py
from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.dependencies import (
    get_current_principal,
    get_request_odoo_client,
    get_required_picker_identity,
    require_roles,
)
from app.models.auth import Principal


PRINCIPAL = Principal(
    picker_user_id=7,
    picker_name="Mina Muster",
    device_id="device-42",
    odoo_instance="o19",
    roles=frozenset({"picker"}),
    session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
)


def test_spoofed_headers_do_not_change_identity_or_instance(monkeypatch):
    app = FastAPI()
    sentinel = object()
    app.dependency_overrides[get_current_principal] = lambda: PRINCIPAL
    monkeypatch.setattr(
        "app.dependencies._get_cached_client",
        lambda name: sentinel if name == "o19" else (_ for _ in ()).throw(AssertionError(name)),
    )

    @app.get("/probe")
    async def probe(
        identity=Depends(get_required_picker_identity),
        odoo=Depends(get_request_odoo_client),
    ):
        return {
            "user_id": identity.user_id,
            "device_id": identity.device_id,
            "instance": identity.odoo_instance,
            "client": odoo is sentinel,
        }

    response = TestClient(app).get(
        "/probe",
        headers={
            "X-Picker-User-Id": "999",
            "X-Device-Id": "attacker",
            "X-Odoo-Instance": "local",
        },
    )
    assert response.json() == {
        "user_id": 7,
        "device_id": "device-42",
        "instance": "o19",
        "client": True,
    }


def test_picker_cannot_enter_supervisor_dependency():
    app = FastAPI()
    app.dependency_overrides[get_current_principal] = lambda: PRINCIPAL

    @app.post("/supervisor")
    async def supervisor(_principal=Depends(require_roles("supervisor"))):
        return {"ok": True}

    assert TestClient(app).post("/supervisor").status_code == 403
```

Replace the old PWA header assertions with:

```javascript
test('authenticated reads send cookie credentials and no authority headers', async () => {
    const originalFetch = global.fetch;
    let captured = null;
    global.fetch = async (_url, options) => {
        captured = options;
        return {ok: true, status: 200, json: async () => []};
    };
    try {
        setActivePicker({id: 18, name: 'Max Picker'});
        setActiveInstance('logilab');
        await getPickings();
        assert.equal(captured.credentials, 'same-origin');
        assert.equal(captured.headers['X-Picker-User-Id'], undefined);
        assert.equal(captured.headers['X-Device-Id'], undefined);
        assert.equal(captured.headers['X-Odoo-Instance'], undefined);
    } finally {
        clearActivePicker();
        setActiveInstance('local');
        global.fetch = originalFetch;
    }
});

test('mutation uses csrf from sessionStorage and stable idempotency only', async () => {
    const originalFetch = global.fetch;
    const originalSessionStorage = global.sessionStorage;
    const store = new Map([['picking-assistant-csrf', 'csrf-1']]);
    global.sessionStorage = {
        getItem: key => store.get(key) ?? null,
        setItem: (key, value) => store.set(key, value),
        removeItem: key => store.delete(key),
    };
    let captured = null;
    global.fetch = async (_url, options) => {
        captured = options;
        return {ok: true, status: 200, json: async () => ({success: true})};
    };
    try {
        await confirmLine(4, {move_line_id: 9, quantity: 1}, {
            idempotencyKey: 'confirm:4:9',
        });
        assert.equal(captured.headers['X-CSRF-Token'], 'csrf-1');
        assert.equal(captured.headers['Idempotency-Key'], 'confirm:4:9');
        assert.equal(captured.headers['X-Device-Id'], undefined);
    } finally {
        global.fetch = originalFetch;
        global.sessionStorage = originalSessionStorage;
    }
});

test('login sends device and selected instance then stores csrf in sessionStorage', async () => {
    const originalFetch = global.fetch;
    const originalSessionStorage = global.sessionStorage;
    const store = new Map();
    global.sessionStorage = {
        getItem: key => store.get(key) ?? null,
        setItem: (key, value) => store.set(key, value),
        removeItem: key => store.delete(key),
    };
    let requestBody;
    global.fetch = async (_url, options) => {
        requestBody = JSON.parse(options.body);
        return {
            ok: true,
            status: 200,
            json: async () => ({
                principal: {
                    picker_user_id: 7,
                    picker_name: 'Mina Muster',
                    device_id: requestBody.device_id,
                    odoo_instance: 'o19',
                    roles: ['picker'],
                    session_id: '4ddb2442-e58a-47fe-9a6f-1ec1d779ef88',
                    expires_at: '2026-07-23T20:00:00Z',
                },
                csrf_token: 'csrf-login',
            }),
        };
    };
    try {
        const session = await loginPickerSession({
            login: 'mina',
            password: 'secret',
            odoo_instance: 'o19',
        });
        assert.equal(requestBody.login, 'mina');
        assert.equal(requestBody.odoo_instance, 'o19');
        assert.ok(requestBody.device_id);
        assert.equal(requestBody.picker_user_id, undefined);
        assert.equal(store.get('picking-assistant-csrf'), 'csrf-login');
        assert.equal(session.principal.picker_user_id, 7);
    } finally {
        global.fetch = originalFetch;
        global.sessionStorage = originalSessionStorage;
    }
});
```

- [ ] **Step 2: Run the focused backend and PWA tests**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_auth_dependencies.py \
  tests/test_dependencies_instance.py \
  tests/test_instance_routing.py \
  -q

cd ..
node --test pwa/js/tests/api.test.mjs
```

Expected: backend tests fail because the old dependencies still trust headers; PWA tests fail because requests still send those headers and lack credentials/CSRF.

- [ ] **Step 3: Invert backend routing and cut the PWA API client to sessions**

Replace secure dependency behavior with:

```python
# backend/app/dependencies.py
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, Request

from app.models.auth import Principal


def get_request_odoo_client(
    principal: Principal = Depends(get_current_principal),
) -> OdooClient:
    return _get_cached_client(principal.odoo_instance)


def get_required_picker_identity(
    principal: Principal = Depends(get_current_principal),
) -> PickerIdentity:
    return PickerIdentity(
        user_id=principal.picker_user_id,
        device_id=principal.device_id,
        picker_name=principal.picker_name,
        odoo_instance=principal.odoo_instance,
        roles=principal.roles,
    )


async def require_browser_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    principal: Principal = Depends(get_current_principal),
    sessions: SessionService = Depends(get_session_service),
) -> None:
    try:
        await sessions.validate_csrf(
            principal,
            x_csrf_token,
            request.headers.get("Origin"),
        )
    except CsrfFailed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


async def get_write_request_context(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(get_current_principal),
    _csrf: None = Depends(require_browser_csrf),
) -> WriteRequestContext:
    return WriteRequestContext(
        idempotency_key=idempotency_key,
        identity=PickerIdentity(
            user_id=principal.picker_user_id,
            device_id=principal.device_id,
            picker_name=principal.picker_name,
            odoo_instance=principal.odoo_instance,
            roles=principal.roles,
        ),
        principal_scope=f"user:{principal.picker_user_id}",
    )


def get_legacy_n8n_write_context(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> WriteRequestContext:
    return WriteRequestContext(
        idempotency_key=idempotency_key,
        identity=PickerIdentity(),
        principal_scope="service:n8n-v1",
    )


def require_roles(*required: str) -> Callable:
    required_roles = frozenset(required)

    async def dependency(
        request: Request,
        sessions: SessionService = Depends(get_session_service),
    ) -> Principal:
        token = request.cookies.get(settings.session_cookie_name, "")
        try:
            principal = await sessions.resolve_principal(
                token,
                force_revalidate="supervisor" in required_roles,
            )
        except AuthenticationFailed as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        if not required_roles.issubset(principal.roles):
            raise HTTPException(status_code=403, detail="Rolle nicht erlaubt.")
        return principal

    return dependency
```

Keep legacy header parsing in one explicitly named `resolve_legacy_header_identity()` function. It may run only when `runtime_profile != "production"` and `mobile_header_grace_mode=true`, logs one warning per request without header values, and is not a dependency of any secure route.

Replace only the five `Depends(get_write_request_context)` occurrences in
`n8n_internal.py` with `Depends(get_legacy_n8n_write_context)`. Those routes keep
their existing `require_n8n_callback_secret` guard and never gain browser cookies,
Origin, or CSRF. Each of the five handlers passes the injected context through
unchanged. If an existing handler must add identity fields, it uses
`dataclasses.replace(context, identity=...)`; it must not reconstruct
`WriteRequestContext` without `principal_scope=context.principal_scope`. Extend
`test_n8n_internal_routes.py` with one positive request for every legacy handler
that has the callback secret and idempotency key but no cookie/Origin/CSRF, plus a
negative request without the callback secret. Every positive fake-service call
must receive `principal_scope == "service:n8n-v1"`; every negative request returns
`403` before any service call.

Extend existing workflow values without changing their current consumers:

```python
# backend/app/services/mobile_workflow.py
@dataclass(frozen=True)
class PickerIdentity:
    user_id: int | None = None
    device_id: str | None = None
    picker_name: str | None = None
    odoo_instance: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class WriteRequestContext:
    idempotency_key: str | None = None
    identity: PickerIdentity = field(default_factory=PickerIdentity)
    principal_scope: str | None = None
```

In `backend/tests/conftest.py`, add a `sample_principal` fixture with the exact Task 7 principal and a helper fixture that overrides `get_current_principal`. Existing route tests opt into that fixture instead of sending authority headers.

In `pwa/js/api.js`, retain `getActiveInstance()` and `setActiveInstance()` only as a pre-login selection preference. Remove instance injection from `request()` and replace the session-related core with:

```javascript
const CSRF_STORAGE_KEY = 'picking-assistant-csrf';

export function getCsrfToken() {
    try {
        return globalThis.sessionStorage?.getItem(CSRF_STORAGE_KEY) ?? null;
    } catch {
        return null;
    }
}

export function setCsrfToken(token) {
    try {
        if (token) {
            globalThis.sessionStorage?.setItem(CSRF_STORAGE_KEY, token);
        } else {
            globalThis.sessionStorage?.removeItem(CSRF_STORAGE_KEY);
        }
    } catch {
        // Session remains server-authoritative when storage is unavailable.
    }
}

function clearSessionClientState() {
    setCsrfToken(null);
    clearActivePicker();
}

function getReadHeaders() {
    return {};
}

function getWriteHeaders(idempotencyKey) {
    const headers = {};
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
    const csrfToken = getCsrfToken();
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
    return headers;
}

async function request(method, path, body = null, options = {}) {
    const headers = {...(options.headers || {})};
    const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
    if (body && !isFormData) headers['Content-Type'] = 'application/json';

    const opts = {
        method,
        headers,
        credentials: 'same-origin',
        cache: options.cache || 'no-store',
        keepalive: options.keepalive || false,
        signal: options.signal,
    };
    if (body) opts.body = isFormData ? body : JSON.stringify(body);

    const resp = await fetch(`${API_BASE}${path}`, opts);
    if (!resp.ok) {
        if (resp.status === 401) clearSessionClientState();
        const err = await resp.json().catch(() => ({detail: resp.statusText}));
        throw new ApiError(resp.status, err.detail ?? err);
    }
    if (resp.status === 204) return null;
    return resp.json();
}

export async function loginPickerSession({login, password, odoo_instance}, options = {}) {
    const result = await request('POST', '/auth/picker-session', {
        login,
        password,
        device_id: getDeviceId(),
        odoo_instance: normalizeInstanceName(odoo_instance),
    }, {signal: options.signal});
    setCsrfToken(result.csrf_token);
    setActivePicker({
        id: result.principal.picker_user_id,
        name: result.principal.picker_name,
    });
    setActiveInstance(result.principal.odoo_instance);
    return result;
}

export async function getCurrentSession(options = {}) {
    const principal = await request('GET', '/auth/me', null, {
        signal: options.signal,
    });
    setActivePicker({
        id: principal.picker_user_id,
        name: principal.picker_name,
    });
    setActiveInstance(principal.odoo_instance);
    return principal;
}

export async function rotateCsrfToken(options = {}) {
    const result = await request('POST', '/auth/csrf', null, {
        signal: options.signal,
    });
    setCsrfToken(result.csrf_token);
    return result.csrf_token;
}

export async function logoutPickerSession(options = {}) {
    try {
        return await request('POST', '/auth/logout', null, {
            headers: getWriteHeaders(),
            keepalive: options.keepalive || false,
            signal: options.signal,
        });
    } finally {
        clearSessionClientState();
    }
}
```

Every existing read function uses empty `getReadHeaders()`. Every authenticated POST uses `getWriteHeaders()` even when it is exempt from idempotency. Domain mutations additionally pass their stable `Idempotency-Key`. `recognizeVoice`, read-only `assistVoice`, TTS, heartbeat, login, CSRF rotation, and logout do not invent idempotency keys.

- [ ] **Step 4: Run dependency, route, and PWA API tests**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_auth_dependencies.py \
  tests/test_dependencies_instance.py \
  tests/test_instance_routing.py \
  tests/test_auth_routes.py \
  tests/test_n8n_internal_routes.py \
  -q

cd ..
node --test pwa/js/tests/api.test.mjs
git diff --check
```

Expected: spoofed headers have no effect; all selected backend and PWA tests pass; no authority header assertion remains.

- [ ] **Step 5: Commit the principal-first adapter**

```bash
git add \
  backend/app/dependencies.py \
  backend/app/routers/n8n_internal.py \
  backend/app/services/mobile_workflow.py \
  backend/tests/conftest.py \
  backend/tests/test_auth_dependencies.py \
  backend/tests/test_dependencies_instance.py \
  backend/tests/test_instance_routing.py \
  backend/tests/test_n8n_internal_routes.py \
  pwa/js/api.js \
  pwa/js/tests/api.test.mjs
git commit -m "feat(pwa): use session principal and csrf transport"
```

Record this handoff explicitly: the PWA track must replace the anonymous picker
catalogue screen in `pwa/js/app.js` and `pwa/index.html` with
login/password/instance UI using these four adapter calls. Until that PWA task is
merged and its mobile tests pass, Task 16 keeps the dispatcher and strict production
rollout disabled.

### Task 8: Atomic Odoo Jobs, Outbox, Receipts, and Leases

**Files:**
- Create: `odoo/addons/picking_assistant_integration/models/integration_job.py`
- Create: `odoo/addons/picking_assistant_integration/models/outbox.py`
- Create: `odoo/addons/picking_assistant_integration/models/receipts.py`
- Create: `odoo/addons/picking_assistant_integration/tests/test_job_outbox_transaction.py`
- Create: `odoo/addons/picking_assistant_integration/tests/test_receipts_callbacks.py`
- Create: `odoo/addons/picking_assistant_integration/tests/test_crons_retention.py`
- Modify: `odoo/addons/picking_assistant_integration/models/__init__.py`
- Modify: `odoo/addons/picking_assistant_integration/security/ir.model.access.csv`
- Modify: `odoo/addons/picking_assistant_integration/data/ir_cron.xml`

**Interfaces:**
- Consumes: `_require_api_service()` and Odoo groups from Task 5.
- Produces: private `_enqueue_job_event(...) -> tuple[job, outbox]`; public `api_get_job`, `api_lease_due`, `api_ack_delivery`, `api_nack_delivery`, `api_requeue_dead`, `api_accept_event`, `api_apply_callback`, `api_reserve_request_nonce`, watchdog, and retention crons.

- [ ] **Step 1: Write failing transaction, lease, replay, and retention tests**

```python
# odoo/addons/picking_assistant_integration/tests/test_job_outbox_transaction.py
from datetime import timedelta

from odoo import fields

from .common import IntegrationCase


class TestJobOutboxTransaction(IntegrationCase):
    def _enqueue(self, suffix="1", envelope='{"schema_version":"v2","text":"Gruss"}'):
        return self.env["picking.assistant.integration.job"]._enqueue_job_event(
            job_type="quality_assessment",
            aggregate_model="res.partner",
            aggregate_res_id=self.picker.partner_id.id,
            aggregate_revision=1,
            event_id=f"a4ff5ca2-4546-4ea4-8e6c-b75bc003ca3{suffix}",
            event_name="quality.assessment.requested.v1",
            envelope_text=envelope,
            payload_fingerprint="a" * 64,
            correlation_id=f"0b2f7909-4ad9-44c1-8527-e775fe6d4be{suffix}",
        )

    def test_business_write_job_and_outbox_rollback_together(self):
        marker = "PWR atomic rollback marker"
        with self.assertRaisesRegex(RuntimeError, "force rollback"):
            with self.env.cr.savepoint():
                self.env["res.partner"].create({"name": marker})
                self._enqueue()
                raise RuntimeError("force rollback")
        self.env.invalidate_all()
        self.assertFalse(self.env["res.partner"].search([("name", "=", marker)]))
        self.assertFalse(self.env["picking.assistant.integration.job"].search([]))
        self.assertFalse(self.env["picking.assistant.outbox"].search([]))

    def test_success_keeps_exact_envelope_text(self):
        envelope = '{"schema_version":"v2","message":"Gruess dich"}'
        job, outbox = self._enqueue(envelope=envelope)
        self.assertEqual(job.state, "queued")
        self.assertEqual(outbox.envelope_text, envelope)
        self.assertEqual(outbox.event_id, "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca31")

    def test_two_leases_are_disjoint_and_nack_uses_frozen_backoff(self):
        self._enqueue("1")
        self._enqueue("2")
        model = self.env["picking.assistant.outbox"].with_user(self.api_user)
        first = model.api_lease_due("worker-a", limit=1, lease_seconds=60)
        second = model.api_lease_due("worker-b", limit=1, lease_seconds=60)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first[0]["event_id"], second[0]["event_id"])
        failed = model.api_nack_delivery(
            first[0]["event_id"], "worker-a", "timeout", "n8n timeout"
        )
        self.assertEqual(failed["attempt_count"], 1)
        self.assertEqual(failed["retry_after_seconds"], 10)
```

```python
# odoo/addons/picking_assistant_integration/tests/test_receipts_callbacks.py
from odoo.exceptions import ValidationError

from .common import IntegrationCase


class TestReceiptsAndCallbacks(IntegrationCase):
    def setUp(self):
        super().setUp()
        self.job, self.outbox = self.env[
            "picking.assistant.integration.job"
        ]._enqueue_job_event(
            job_type="quality_assessment",
            aggregate_model="res.partner",
            aggregate_res_id=self.picker.partner_id.id,
            aggregate_revision=1,
            event_id="a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
            event_name="quality.assessment.requested.v1",
            envelope_text='{"schema_version":"v2"}',
            payload_fingerprint="a" * 64,
            correlation_id="0b2f7909-4ad9-44c1-8527-e775fe6d4bec",
            job_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
        )

    def test_acceptance_returns_one_processing_lease_then_deduplicates(self):
        receipts = self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        )
        first = receipts.api_accept_event(
            self.outbox.event_id,
            self.job.job_id,
            "a" * 64,
            "b2n-test",
            "123e4567-e89b-42d3-a456-426614174000",
            1,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174001",
        )
        second = receipts.api_accept_event(
            self.outbox.event_id,
            self.job.job_id,
            "a" * 64,
            "b2n-test",
            "123e4567-e89b-42d3-a456-426614174003",
            1,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174002",
        )
        self.assertTrue(first["process"])
        self.assertTrue(first["processing_lease_token"])
        self.assertFalse(second["process"])
        self.assertEqual(
            self.env["picking.assistant.event.receipt"].search_count([]), 1
        )

    def test_reused_ingress_nonce_is_rejected_even_for_same_event(self):
        receipts = self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        )
        args = [
            self.outbox.event_id,
            self.job.job_id,
            "a" * 64,
            "b2n-test",
            "123e4567-e89b-42d3-a456-426614174000",
            1,
            "n2b-test",
        ]
        receipts.api_accept_event(
            *args, "123e4567-e89b-42d3-a456-426614174001"
        )
        with self.assertRaises(ValidationError):
            receipts.api_accept_event(
                *args, "123e4567-e89b-42d3-a456-426614174002"
            )
        self.assertEqual(receipts.search_count([]), 1)

    def test_wrong_job_id_causes_no_nonce_or_receipt_write(self):
        receipts = self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        )
        with self.assertRaises(ValidationError):
            receipts.api_accept_event(
                self.outbox.event_id,
                "00000000-0000-4000-8000-000000000099",
                "a" * 64,
                "b2n-test",
                "123e4567-e89b-42d3-a456-426614174010",
                1,
                "n2b-test",
                "123e4567-e89b-42d3-a456-426614174011",
            )
        self.assertFalse(receipts.search_count([]))
        self.assertFalse(
            self.env["picking.assistant.webhook.nonce"].search_count([])
        )

    def test_callback_replay_and_stale_sequence_have_no_second_effect(self):
        receipts = self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        )
        accepted = receipts.api_accept_event(
            self.outbox.event_id,
            self.job.job_id,
            "a" * 64,
            "b2n-test",
            "123e4567-e89b-42d3-a456-426614174000",
            1,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174001",
        )
        callback = {
            "callback_id": "cbdc037f-8458-4be0-938a-4bc8242116af",
            "source_event_id": self.outbox.event_id,
            "job_id": self.job.job_id,
            "sequence": 1,
            "attempt": 1,
            "delivery_generation": 1,
            "processing_lease_token": accepted["processing_lease_token"],
            "status": "running",
            "result": {},
            "error": False,
            "metrics": {},
        }
        model = self.env["picking.assistant.callback.receipt"].with_user(
            self.api_user
        )
        first = model.api_apply_callback(
            callback,
            "b" * 64,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174003",
        )
        replay = model.api_apply_callback(
            callback,
            "b" * 64,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174004",
        )
        self.assertEqual(first["status"], "applied")
        self.assertEqual(replay, first)
        self.assertEqual(self.job.state, "running")
        self.assertEqual(self.job.sequence, 1)
```

```python
# odoo/addons/picking_assistant_integration/tests/test_crons_retention.py
from datetime import timedelta

from odoo import fields

from .common import IntegrationCase


class TestRetention(IntegrationCase):
    def test_legal_hold_blocks_job_and_audit_cleanup(self):
        job, outbox = self.env[
            "picking.assistant.integration.job"
        ]._enqueue_job_event(
            job_type="shipping_label",
            aggregate_model="res.partner",
            aggregate_res_id=self.picker.partner_id.id,
            aggregate_revision=1,
            event_id="a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
            event_name="shipment.parcel.ready.v1",
            envelope_text='{"schema_version":"v2"}',
            payload_fingerprint="a" * 64,
            correlation_id="0b2f7909-4ad9-44c1-8527-e775fe6d4bec",
        )
        old = fields.Datetime.now() - timedelta(days=100)
        job.write({"state": "failed", "completed_at": old, "legal_hold": True})
        outbox.write({"state": "dead", "write_date": old})
        self.env["picking.assistant.integration.job"]._cron_cleanup_audit(limit=100)
        self.assertTrue(job.exists())
        self.assertTrue(outbox.exists())
```

- [ ] **Step 2: Run the Odoo tag and confirm the new models are missing**

Run:

```bash
docker compose --profile odoo19-trial run --rm --no-deps odoo19-trial \
  --database masterfischer_o19_foundation_test \
  --db-filter '^masterfischer_o19_foundation_test$' \
  --workers=0 --max-cron-threads=0 --without-demo=all \
  --update picking_assistant_integration \
  --test-tags /picking_assistant_integration \
  --stop-after-init
```

Expected: tests fail because job, outbox, and receipt models are not registered.

- [ ] **Step 3: Add the atomic state machine and persistence APIs**

Define the job fields and private enqueue contract:

```python
# models/integration_job.py
import json
from datetime import timedelta
from uuid import uuid4

from odoo import api, fields, models
from odoo.exceptions import ValidationError

JOB_STATES = [
    ("queued", "Queued"),
    ("running", "Running"),
    ("succeeded", "Succeeded"),
    ("review_required", "Review Required"),
    ("retry_scheduled", "Retry Scheduled"),
    ("failed", "Failed"),
]
TERMINAL_STATES = {"succeeded", "review_required", "failed"}
TRANSITIONS = {
    "queued": {"running"},
    "running": {"succeeded", "review_required", "retry_scheduled", "failed"},
    "retry_scheduled": {"running"},
}


class PickingAssistantIntegrationJob(models.Model):
    _name = "picking.assistant.integration.job"
    _description = "Picking Assistant Integration Job"
    _order = "create_date desc"

    job_id = fields.Char(required=True, index=True, readonly=True)
    job_type = fields.Char(required=True, index=True, readonly=True)
    aggregate_model = fields.Char(required=True, readonly=True)
    aggregate_res_id = fields.Integer(required=True, readonly=True)
    aggregate_revision = fields.Integer(required=True, readonly=True)
    state = fields.Selection(JOB_STATES, required=True, default="queued", index=True)
    sequence = fields.Integer(required=True, default=0)
    attempt = fields.Integer(required=True, default=1)
    delivery_generation = fields.Integer(required=True, default=1)
    processing_lease_token = fields.Char(readonly=True)
    processing_lease_expires_at = fields.Datetime(index=True, readonly=True)
    supersedes_job_record_id = fields.Many2one(
        "picking.assistant.integration.job", ondelete="restrict", readonly=True
    )
    correlation_id = fields.Char(required=True, index=True, readonly=True)
    causation_id = fields.Char(index=True, readonly=True)
    result_json = fields.Text(readonly=True)
    error_json = fields.Text(readonly=True)
    metrics_json = fields.Text(readonly=True)
    started_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(index=True, readonly=True)
    legal_hold = fields.Boolean(default=False, index=True)

    _job_id_unique = models.Constraint("UNIQUE(job_id)", "Job ID must be unique.")
    _revision_positive = models.Constraint(
        "CHECK(aggregate_revision >= 1)", "Aggregate revision must be positive."
    )
    _generation_positive = models.Constraint(
        "CHECK(delivery_generation >= 1)", "Delivery generation must be positive."
    )
    _sequence_nonnegative = models.Constraint(
        "CHECK(sequence >= 0)", "Sequence must be nonnegative."
    )

    @api.model
    def _enqueue_job_event(
        self,
        *,
        job_type,
        aggregate_model,
        aggregate_res_id,
        aggregate_revision,
        event_id,
        event_name,
        envelope_text,
        payload_fingerprint,
        correlation_id,
        causation_id=False,
        job_id=False,
        supersedes_job_id=False,
    ):
        if not isinstance(envelope_text, str):
            raise ValidationError("Envelope must be lossless UTF-8 text.")
        supersedes = False
        if supersedes_job_id:
            supersedes = self.search(
                [("job_id", "=", supersedes_job_id)], limit=1
            )
            if not supersedes or supersedes.state not in TERMINAL_STATES:
                raise ValidationError("Superseded job must be terminal.")
        job = self.create(
            {
                "job_id": job_id or str(uuid4()),
                "job_type": job_type,
                "aggregate_model": aggregate_model,
                "aggregate_res_id": int(aggregate_res_id),
                "aggregate_revision": int(aggregate_revision),
                "correlation_id": correlation_id,
                "causation_id": causation_id or False,
                "supersedes_job_record_id": supersedes.id if supersedes else False,
            }
        )
        outbox = self.env["picking.assistant.outbox"].create(
            {
                "event_id": event_id,
                "job_record_id": job.id,
                "event_name": event_name,
                "envelope_text": envelope_text,
                "payload_fingerprint": payload_fingerprint,
                "state": "pending",
                "next_attempt_at": fields.Datetime.now(),
            }
        )
        return job, outbox

    def _api_payload(self):
        self.ensure_one()
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "state": self.state,
            "aggregate_model": self.aggregate_model,
            "aggregate_res_id": self.aggregate_res_id,
            "aggregate_revision": self.aggregate_revision,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id or None,
            "attempt": self.attempt,
            "delivery_generation": self.delivery_generation,
            "sequence": self.sequence,
            "result": json.loads(self.result_json or "{}"),
            "error": json.loads(self.error_json or "{}"),
            "metrics": json.loads(self.metrics_json or "{}"),
            "created_at": fields.Datetime.to_string(self.create_date),
            "started_at": fields.Datetime.to_string(self.started_at)
            if self.started_at
            else None,
            "completed_at": fields.Datetime.to_string(self.completed_at)
            if self.completed_at
            else None,
        }

    @api.model
    def api_get_job(self, job_id):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        job = self.sudo().search([("job_id", "=", job_id)], limit=1)
        return job._api_payload() if job else False

    def _transition(self, target, *, sequence, result=None, error=None, metrics=None):
        self.ensure_one()
        if target not in TRANSITIONS.get(self.state, set()):
            raise ValidationError(f"Illegal job transition {self.state} -> {target}.")
        now = fields.Datetime.now()
        values = {
            "state": target,
            "sequence": int(sequence),
            "result_json": json.dumps(result or {}, sort_keys=True),
            "error_json": json.dumps(error or {}, sort_keys=True),
            "metrics_json": json.dumps(metrics or {}, sort_keys=True),
        }
        if target == "running" and not self.started_at:
            values["started_at"] = now
        if target in TERMINAL_STATES:
            values["completed_at"] = now
            values["processing_lease_expires_at"] = False
        self.write(values)
```

The outbox model must use the exact retry schedule and return stored text unchanged:

```python
# models/outbox.py
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL

BACKOFF_SECONDS = (10, 60, 300, 1800, 7200, 21600, 21600, 21600, 21600, 21600)


class PickingAssistantOutbox(models.Model):
    _name = "picking.assistant.outbox"
    _description = "Picking Assistant Outbox"
    _order = "next_attempt_at, id"

    event_id = fields.Char(required=True, index=True, readonly=True)
    job_record_id = fields.Many2one(
        "picking.assistant.integration.job",
        required=True,
        ondelete="cascade",
        index=True,
        readonly=True,
    )
    job_id = fields.Char(related="job_record_id.job_id", store=True, index=True)
    event_name = fields.Char(required=True, readonly=True)
    envelope_text = fields.Text(required=True, readonly=True)
    payload_fingerprint = fields.Char(required=True, readonly=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("leased", "Leased"),
            ("delivered", "Delivered"),
            ("dead", "Dead"),
        ],
        required=True,
        default="pending",
        index=True,
    )
    attempt_count = fields.Integer(required=True, default=0)
    next_attempt_at = fields.Datetime(required=True, index=True)
    lease_owner = fields.Char(index=True)
    lease_expires_at = fields.Datetime(index=True)
    last_error_code = fields.Char()
    last_error_message = fields.Char()
    delivered_at = fields.Datetime(index=True)

    _event_id_unique = models.Constraint(
        "UNIQUE(event_id)", "Event ID must be unique."
    )

    @api.model
    def api_lease_due(self, worker_id, limit=50, lease_seconds=60):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        size = max(1, min(int(limit), 200))
        now = fields.Datetime.now()
        self.env.cr.execute(
            SQL(
                """
                SELECT id
                  FROM picking_assistant_outbox
                 WHERE (
                       (state = 'pending' AND next_attempt_at <= %(now)s)
                    OR (state = 'leased' AND lease_expires_at <= %(now)s)
                 )
                 ORDER BY next_attempt_at, id
                 FOR UPDATE SKIP LOCKED
                 LIMIT %(limit)s
                """,
                now=now,
                limit=size,
            )
        )
        ids = [row[0] for row in self.env.cr.fetchall()]
        records = self.sudo().browse(ids)
        for record in records:
            record.write(
                {
                    "state": "leased",
                    "attempt_count": record.attempt_count + 1,
                    "lease_owner": worker_id,
                    "lease_expires_at": now + timedelta(seconds=int(lease_seconds)),
                }
            )
        return [
            {
                "event_id": record.event_id,
                "job_id": record.job_id,
                "event_name": record.event_name,
                "envelope_text": record.envelope_text,
                "payload_fingerprint": record.payload_fingerprint,
                "delivery_generation": record.job_record_id.delivery_generation,
                "attempt_count": record.attempt_count,
            }
            for record in records
        ]

    def _owned_lease(self, event_id, worker_id):
        record = self.sudo().search([("event_id", "=", event_id)], limit=1)
        if (
            not record
            or record.state != "leased"
            or record.lease_owner != worker_id
        ):
            raise ValidationError("Outbox lease is not owned by this worker.")
        return record

    @api.model
    def api_ack_delivery(self, event_id, worker_id, accepted_event_id):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        record = self._owned_lease(event_id, worker_id)
        if accepted_event_id != record.event_id:
            raise ValidationError("Acceptance event ID mismatch.")
        record.write(
            {
                "state": "delivered",
                "delivered_at": fields.Datetime.now(),
                "lease_owner": False,
                "lease_expires_at": False,
                "last_error_code": False,
                "last_error_message": False,
            }
        )
        return {"state": "delivered", "event_id": record.event_id}

    @api.model
    def api_nack_delivery(self, event_id, worker_id, error_code, error_message):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        record = self._owned_lease(event_id, worker_id)
        attempt = record.attempt_count
        dead = attempt >= len(BACKOFF_SECONDS)
        retry_after = BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)]
        record.write(
            {
                "state": "dead" if dead else "pending",
                "next_attempt_at": fields.Datetime.now()
                + timedelta(seconds=retry_after),
                "lease_owner": False,
                "lease_expires_at": False,
                "last_error_code": str(error_code)[:64],
                "last_error_message": str(error_message)[:500],
            }
        )
        return {
            "state": record.state,
            "event_id": record.event_id,
            "attempt_count": attempt,
            "retry_after_seconds": retry_after,
        }

    @api.model
    def api_requeue_dead(self, event_id, supervisor_user_id, reason):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        supervisor = self.env["res.users"].sudo().browse(
            int(supervisor_user_id)
        ).exists()
        if not supervisor or not supervisor.has_group(
            "picking_assistant_integration.group_supervisor"
        ):
            raise AccessError("Supervisor role required.")
        record = self.sudo().search(
            [("event_id", "=", event_id), ("state", "=", "dead")], limit=1
        )
        if not record:
            raise ValidationError("Dead outbox event not found.")
        record.write(
            {
                "state": "pending",
                "attempt_count": 0,
                "next_attempt_at": fields.Datetime.now(),
                "last_error_code": "manual_requeue",
                "last_error_message": str(reason)[:500],
            }
        )
        return {"state": "pending", "event_id": record.event_id}
```

`receipts.py` defines:

```python
class PickingAssistantWebhookNonce(models.Model):
    _name = "picking.assistant.webhook.nonce"

    direction = fields.Selection(
        [("backend_to_n8n", "Backend to n8n"), ("n8n_to_backend", "n8n to Backend")],
        required=True,
        index=True,
    )
    key_id = fields.Char(required=True, index=True)
    nonce = fields.Char(required=True, index=True)
    event_id = fields.Char(index=True)
    received_at = fields.Datetime(required=True, default=fields.Datetime.now)
    expires_at = fields.Datetime(required=True, index=True)

    _nonce_unique = models.Constraint(
        "UNIQUE(direction, key_id, nonce)", "Webhook nonce must be unique."
    )
```

```python
class PickingAssistantEventReceipt(models.Model):
    _name = "picking.assistant.event.receipt"

    event_id = fields.Char(required=True, index=True)
    job_record_id = fields.Many2one(
        "picking.assistant.integration.job", required=True, ondelete="cascade"
    )
    payload_fingerprint = fields.Char(required=True)
    delivery_generation = fields.Integer(required=True)
    state = fields.Selection(
        [
            ("accepted", "Accepted"),
            ("processing", "Processing"),
            ("completed", "Completed"),
            ("retryable", "Retryable"),
        ],
        required=True,
    )
    processing_lease_token = fields.Char()
    processing_lease_expires_at = fields.Datetime(index=True)
    first_received_at = fields.Datetime(required=True, default=fields.Datetime.now)
    last_received_at = fields.Datetime(required=True, default=fields.Datetime.now)

    _event_receipt_unique = models.Constraint(
        "UNIQUE(event_id)", "Event receipt must be unique."
    )
```

```python
class PickingAssistantCallbackReceipt(models.Model):
    _name = "picking.assistant.callback.receipt"

    callback_id = fields.Char(required=True, index=True)
    source_event_id = fields.Char(required=True, index=True)
    job_record_id = fields.Many2one(
        "picking.assistant.integration.job", required=True, ondelete="cascade"
    )
    sequence = fields.Integer(required=True)
    fingerprint = fields.Char(required=True)
    response_status = fields.Integer(required=True)
    response_body = fields.Text(required=True)
    received_at = fields.Datetime(required=True, default=fields.Datetime.now)

    _callback_id_unique = models.Constraint(
        "UNIQUE(callback_id)", "Callback ID must be unique."
    )
    _job_sequence_unique = models.Constraint(
        "UNIQUE(job_record_id, sequence)", "Job callback sequence must be unique."
    )
```

Implement all unique races inside `with self.env.cr.savepoint():`; catch `psycopg2.IntegrityError` outside that block and re-read the winning row. Never call `env.cr.rollback()`.
For a nonce uniqueness collision, re-read only to classify the conflict and then
raise `ValidationError("Webhook nonce replay.")`; unlike an event or callback ID,
a nonce collision never returns a deduplicated success.

`api_accept_event(...)` performs one transaction in this order:

1. check `group_api_service`;
2. load and lock the outbox/job using `SELECT ... FOR UPDATE`;
3. compare the supplied `job_id`, fingerprint, and delivery generation with the
   locked records and reject before any create/write when one differs;
4. reserve the `n8n_to_backend` acceptance nonce;
5. reserve the `backend_to_n8n` ingress nonce; every reused
   `(direction, key_id, nonce)` is rejected even for the same event;
6. create or lock the event receipt;
7. return `process=false` for an active `processing` lease or completed receipt;
8. for a new/retryable receipt, generate `secrets.token_urlsafe(32)`, set a five-minute lease, increment job `attempt` only when generation is greater than one, and return `process=true`.

The exact signature is:

```python
api_accept_event(
    event_id: str,
    job_id: str,
    payload_fingerprint: str,
    ingress_key_id: str,
    ingress_nonce: str,
    delivery_generation: int,
    acceptance_key_id: str,
    acceptance_nonce: str,
) -> {
    "accepted": True,
    "event_id": str,
    "job_id": str,
    "process": bool,
    "processing_lease_token": str | False,
}
```

`api_apply_callback(callback, callback_fingerprint, key_id, nonce)` reserves the callback nonce, locks job and event receipt, and applies all these checks before a write:

- same callback ID and fingerprint returns stored status/body;
- same callback ID with a different fingerprint raises conflict;
- lower sequence returns and stores `ignored_stale` without changing the job;
- equal sequence with different callback ID raises conflict;
- generation and lease token must match the locked job/receipt;
- `running` extends the lease by five minutes and moves `queued` or `retry_scheduled` to `running`;
- a process over three minutes can send new `running` callbacks at sequence increments of at least one; the server does not accept sequence reuse;
- terminal status completes the event receipt and cannot reopen;
- `retry_scheduled` clears the old lease, increments generation, marks the event receipt retryable, and returns the same outbox event to pending with unchanged `envelope_text`.

The stored response is a deterministic JSON string and is created in the same transaction as the job change. Lease token comparison uses `secrets.compare_digest`.

Add `_cron_recover_stalled_jobs(limit=200)` every minute. It locks expired processing receipts with `FOR UPDATE SKIP LOCKED`, sets receipt `retryable`, job `retry_scheduled`, increments `delivery_generation`, clears the processing token, and returns the same outbox row to `pending`.

Add `_cron_cleanup_ephemeral(limit=1000)` every ten minutes for expired nonces, throttles, and sessions outside their retention. Add `_cron_cleanup_audit(limit=1000)` daily in callback receipt, event receipt, outbox, then job order. It enforces delivered outbox 30 days, dead outbox 90 days, event receipts 90 days after terminal job, callbacks 90 days, jobs 90 days, and skips every record linked to `legal_hold=True`. Each cron calls `_commit_progress`.

Update ACL rows for all seven models: System gets CRUD; API Service gets read-only; no picker/supervisor row exists.

- [ ] **Step 4: Run all Odoo integration tests twice**

Run:

```bash
python3 -m compileall -q odoo/addons/picking_assistant_integration
docker compose --profile odoo19-trial run --rm --no-deps odoo19-trial \
  --database masterfischer_o19_foundation_test \
  --db-filter '^masterfischer_o19_foundation_test$' \
  --workers=0 --max-cron-threads=0 --without-demo=all \
  --update picking_assistant_integration \
  --test-tags /picking_assistant_integration \
  --stop-after-init

docker compose --profile odoo19-trial run --rm --no-deps odoo19-trial \
  --database masterfischer_o19_foundation_test \
  --db-filter '^masterfischer_o19_foundation_test$' \
  --workers=0 --max-cron-threads=0 --without-demo=all \
  --update picking_assistant_integration \
  --test-tags /picking_assistant_integration \
  --stop-after-init
```

Expected: both runs report zero failed tests; the second update proves constraints and cron data are idempotent.

- [ ] **Step 5: Commit the durable Odoo integration state**

```bash
git add odoo/addons/picking_assistant_integration
git commit -m "feat(odoo): add atomic jobs outbox and replay receipts"
```

### Task 9: Signed Event Transport, Dispatcher, and Lifespan

**Files:**
- Create: `backend/app/services/signed_webhook_transport.py`
- Create: `backend/app/services/outbox_dispatcher.py`
- Create: `backend/app/services/workflow_targets.py`
- Create: `backend/tests/test_signed_webhook_transport.py`
- Create: `backend/tests/test_outbox_dispatcher.py`
- Create: `backend/tests/test_workflow_targets.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/dependencies.py` to construct transport/dispatcher
- Modify: `odoo/addons/picking_assistant_integration/models/integration_job.py` to expose the guarded watchdog batch
- Modify: `odoo/addons/picking_assistant_integration/tests/test_receipts_callbacks.py`
- Preserve: `backend/app/services/n8n_webhook.py` as legacy v1 transport

**Interfaces:**
- Consumes: HMAC Task 2, Odoo lease APIs Task 8, instance registry Task 1.
- Produces: `WebhookAcceptanceResult`, `SignedWebhookTransport.deliver_event(...)`,
  `load_event_targets(registry_path)`, `DispatchStats`,
  `OutboxDispatcher.run_once(instance)`, `OutboxDispatcher.run(stop_event)`,
  `IntegrationWatchdog.run_once(instance)`,
  `build_outbox_dispatcher(candidate, client_factory, targets)`,
  `build_integration_watchdog(candidate, client_factory)`, and FastAPI lifespan
  startup/shutdown.

- [ ] **Step 1: Write failing byte-identity and restart tests**

```python
# backend/tests/test_signed_webhook_transport.py
import json

import httpx
import pytest

from app.models.webhook_security import HmacKey
from app.services.signed_webhook_transport import SignedWebhookTransport


@pytest.mark.asyncio
async def test_transport_hashes_and_sends_exact_stored_bytes():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
            },
        )

    raw = b'{"message":"Gr\\xc3\\xbcss dich","schema_version":"v2"}'
    transport = SignedWebhookTransport(
        base_url="http://n8n:5678",
        native_header_secret="native-secret-" + ("x" * 32),
        signing_key=HmacKey("b2n-test", b"0" * 32),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        now_seconds=lambda: 1760000000,
        nonce_factory=lambda: "123e4567-e89b-42d3-a456-426614174000",
    )
    result = await transport.deliver_event(
        target="/webhook/quality-assessment-v2",
        event_id="a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
        delivery_generation=1,
        raw_body=raw,
    )
    assert result.accepted
    assert captured["body"] == raw
    assert captured["headers"]["idempotency-key"] == result.event_id
    assert captured["headers"]["x-pwr-signed-target"] == (
        "/webhook/quality-assessment-v2"
    )


@pytest.mark.asyncio
async def test_acceptance_must_echo_the_same_event_id():
    transport = SignedWebhookTransport(
        base_url="http://n8n:5678",
        native_header_secret="native-secret-" + ("x" * 32),
        signing_key=HmacKey("b2n-test", b"0" * 32),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200, json={"accepted": True, "event_id": "wrong"}
                )
            )
        ),
    )
    result = await transport.deliver_event(
        target="/webhook/quality-assessment-v2",
        event_id="a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
        delivery_generation=1,
        raw_body=b"{}",
    )
    assert not result.accepted
    assert result.error_code == "ambiguous_acceptance"
```

```python
# backend/tests/test_outbox_dispatcher.py
import asyncio

import pytest

from app.services.outbox_dispatcher import OutboxDispatcher
from app.services.signed_webhook_transport import WebhookAcceptanceResult

EVENT = {
    "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
    "job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    "event_name": "quality.assessment.requested.v1",
    "envelope_text": '{"schema_version":"v2","message":"Gruess dich"}',
    "payload_fingerprint": "a" * 64,
    "delivery_generation": 1,
    "attempt_count": 1,
}


class FakeOdoo:
    def __init__(self):
        self.pending = [dict(EVENT)]
        self.acked = []
        self.nacked = []

    async def execute_kw(self, model, method, args, kwargs=None):
        if method == "api_lease_due":
            return [self.pending.pop(0)] if self.pending else []
        if method == "api_ack_delivery":
            self.acked.append(tuple(args))
            return {"state": "delivered"}
        if method == "api_nack_delivery":
            self.nacked.append(tuple(args))
            return {"state": "pending"}
        raise AssertionError((model, method, args))


class FakeTransport:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.calls = []

    async def deliver_event(self, **kwargs):
        self.calls.append(kwargs)
        return WebhookAcceptanceResult(
            accepted=self.accepted,
            event_id=kwargs["event_id"],
            status_code=200 if self.accepted else None,
            error_code=None if self.accepted else "transport_error",
            error_message=None if self.accepted else "connection failed",
        )


@pytest.mark.asyncio
async def test_dispatcher_acks_only_matching_acceptance_and_keeps_raw_body():
    odoo = FakeOdoo()
    transport = FakeTransport()
    dispatcher = OutboxDispatcher(
        client_factory=lambda name: odoo,
        instance_names=("o19",),
        transport=transport,
        targets={
            "quality.assessment.requested.v1":
                "/webhook/quality-assessment-v2"
        },
        worker_id="worker-a",
    )
    stats = await dispatcher.run_once("o19")
    assert stats.delivered == 1
    assert odoo.acked[0][0] == EVENT["event_id"]
    assert transport.calls[0]["raw_body"] == EVENT["envelope_text"].encode("utf-8")


@pytest.mark.asyncio
async def test_new_dispatcher_instance_resumes_persistent_pending_event():
    odoo = FakeOdoo()
    first = OutboxDispatcher(
        client_factory=lambda _name: odoo,
        instance_names=("o19",),
        transport=FakeTransport(accepted=False),
        targets={"quality.assessment.requested.v1": "/webhook/quality-assessment-v2"},
        worker_id="worker-before-restart",
    )
    await first.run_once("o19")
    assert odoo.nacked
    odoo.pending = [dict(EVENT, attempt_count=2)]
    second_transport = FakeTransport(accepted=True)
    second = OutboxDispatcher(
        client_factory=lambda _name: odoo,
        instance_names=("o19",),
        transport=second_transport,
        targets={"quality.assessment.requested.v1": "/webhook/quality-assessment-v2"},
        worker_id="worker-after-restart",
    )
    assert (await second.run_once("o19")).delivered == 1
```

- [ ] **Step 2: Run focused transport/dispatcher tests**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_signed_webhook_transport.py \
  tests/test_outbox_dispatcher.py \
  tests/test_workflow_targets.py \
  tests/test_n8n_webhook.py \
  -q
```

Expected: the two new modules are missing; existing legacy n8n tests remain green.

- [ ] **Step 3: Implement one-attempt transport and lease-driven loops**

The transport signs and sends one attempt; retry timing belongs only to Odoo:

```python
# backend/app/services/signed_webhook_transport.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

import httpx

from app.models.webhook_security import HmacKey
from app.services.hmac_signing import sign_request


@dataclass(frozen=True)
class WebhookAcceptanceResult:
    accepted: bool
    event_id: str
    status_code: int | None
    error_code: str | None
    error_message: str | None


class SignedWebhookTransport:
    def __init__(
        self,
        *,
        base_url: str,
        native_header_secret: str,
        signing_key: HmacKey,
        client: httpx.AsyncClient | None = None,
        now_seconds: Callable[[], int] = lambda: int(time.time()),
        nonce_factory: Callable[[], str] = lambda: str(uuid4()),
    ):
        self._base_url = base_url.rstrip("/")
        self._native_secret = native_header_secret
        self._key = signing_key
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=1.0, read=10.0, write=10.0, pool=5.0)
        )
        self._now_seconds = now_seconds
        self._nonce_factory = nonce_factory

    async def deliver_event(
        self,
        *,
        target: str,
        event_id: str,
        delivery_generation: int,
        raw_body: bytes,
    ) -> WebhookAcceptanceResult:
        if (
            not target.startswith("/webhook/")
            or "?" in target
            or "#" in target
            or "://" in target
        ):
            return WebhookAcceptanceResult(
                False, event_id, None, "invalid_target", "Target is not registered."
            )
        signed = sign_request(
            method="POST",
            target=target,
            delivery_generation=delivery_generation,
            timestamp=self._now_seconds(),
            nonce=self._nonce_factory(),
            raw_body=raw_body,
            key=self._key,
        )
        headers = {
            **signed.as_http_headers(),
            "Content-Type": "application/json",
            "Idempotency-Key": event_id,
            "X-PWR-Webhook-Secret": self._native_secret,
        }
        try:
            response = await self._client.post(
                f"{self._base_url}{target}",
                content=raw_body,
                headers=headers,
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            status = exc.response.status_code if isinstance(
                exc, httpx.HTTPStatusError
            ) else None
            return WebhookAcceptanceResult(
                False,
                event_id,
                status,
                "transport_error",
                type(exc).__name__,
            )
        if payload != {"accepted": True, "event_id": event_id}:
            return WebhookAcceptanceResult(
                False,
                event_id,
                response.status_code,
                "ambiguous_acceptance",
                "Acceptance body did not echo the event ID.",
            )
        return WebhookAcceptanceResult(
            True, event_id, response.status_code, None, None
        )
```

The dispatcher never builds or reserializes an envelope:

```python
# backend/app/services/outbox_dispatcher.py
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DispatchStats:
    leased: int = 0
    delivered: int = 0
    deferred: int = 0


@dataclass(frozen=True)
class WatchdogStats:
    recovered: int = 0


class OutboxDispatcher:
    def __init__(
        self,
        *,
        client_factory,
        instance_names: tuple[str, ...],
        transport,
        targets: dict[str, str],
        worker_id: str,
        poll_seconds: float = 2.0,
        lease_seconds: int = 60,
        batch_size: int = 50,
    ):
        self._client_factory = client_factory
        self._instances = instance_names
        self._transport = transport
        self._targets = targets
        self._worker_id = worker_id
        self._poll_seconds = poll_seconds
        self._lease_seconds = lease_seconds
        self._batch_size = batch_size

    async def run_once(self, instance: str) -> DispatchStats:
        odoo = self._client_factory(instance)
        rows = await odoo.execute_kw(
            "picking.assistant.outbox",
            "api_lease_due",
            [self._worker_id, self._batch_size, self._lease_seconds],
        )
        delivered = 0
        deferred = 0
        for row in rows:
            target = self._targets.get(row["event_name"])
            if target is None:
                result_code = "unregistered_event"
                result_message = "No v2 target is registered."
                accepted = False
            else:
                result = await self._transport.deliver_event(
                    target=target,
                    event_id=row["event_id"],
                    delivery_generation=int(row["delivery_generation"]),
                    raw_body=row["envelope_text"].encode("utf-8"),
                )
                accepted = result.accepted
                result_code = result.error_code or ""
                result_message = result.error_message or ""
            if accepted:
                await odoo.execute_kw(
                    "picking.assistant.outbox",
                    "api_ack_delivery",
                    [row["event_id"], self._worker_id, row["event_id"]],
                )
                delivered += 1
            else:
                await odoo.execute_kw(
                    "picking.assistant.outbox",
                    "api_nack_delivery",
                    [
                        row["event_id"],
                        self._worker_id,
                        result_code,
                        result_message,
                    ],
                )
                deferred += 1
        return DispatchStats(
            leased=len(rows), delivered=delivered, deferred=deferred
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            for instance in self._instances:
                try:
                    await self.run_once(instance)
                except Exception:
                    logger.exception("Outbox cycle failed for instance %s", instance)
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._poll_seconds
                )
            except TimeoutError:
                pass


class IntegrationWatchdog:
    def __init__(self, *, client_factory, instance_names: tuple[str, ...]):
        self._client_factory = client_factory
        self._instances = instance_names

    async def run_once(self, instance: str) -> WatchdogStats:
        result = await self._client_factory(instance).execute_kw(
            "picking.assistant.integration.job",
            "api_recover_stalled_jobs",
            [200],
        )
        return WatchdogStats(recovered=int(result.get("recovered", 0)))
```

Add guarded `api_recover_stalled_jobs(limit=200)` to Odoo. It invokes the same locked batch helper as the minute cron and returns only counts, not lease tokens.

Load transport targets from the sole reviewed registry:

```python
# backend/app/services/workflow_targets.py
import json
from pathlib import Path

from app.models.events import EVENT_NAMES


def load_event_targets(registry_path: Path) -> dict[str, str]:
    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "v1":
        raise ValueError("unsupported workflow registry schema")
    targets: dict[str, str] = {}
    for workflow in raw.get("workflows") or []:
        if workflow.get("generation") != "v2":
            continue
        paths = workflow.get("webhook_paths") or []
        events = workflow.get("event_names") or []
        if len(paths) != 1:
            raise ValueError(f"{workflow.get('file')}: v2 requires one webhook path")
        target = f"/webhook/{paths[0]}"
        for event_name in events:
            if event_name in targets:
                raise ValueError(f"duplicate v2 event target: {event_name}")
            targets[event_name] = target
    unknown = set(targets) - EVENT_NAMES
    if unknown:
        raise ValueError(f"unknown v2 event target: {sorted(unknown)}")
    return targets
```

`test_workflow_targets.py` writes a temporary registry with the frozen Quality v2
event, asserts its exact path, then tests duplicate event names, missing paths, and
an unknown event. An approved event may remain without a target until its feature
workflow lands; the dispatcher leaves such outbox rows pending with
`unregistered_event_target`. In `dependencies.py`, call
`load_event_targets(Path(settings.workflow_registry_path))` when constructing the
dispatcher. No Python constant repeats the event-to-path mapping.

Construct the active backend-to-n8n key from Task 1 settings. Do not pass the
previous key to the sender; senders always use the active key, while receivers
accept active and previous. Put the pure construction functions beside the
dispatcher so Task 16 can build one graph per app:

```python
# backend/app/services/outbox_dispatcher.py
import os
import socket

from app.config import Settings, decode_secret_b64, get_instance_registry
from app.models.webhook_security import HmacKey
from app.services.signed_webhook_transport import SignedWebhookTransport


def build_outbox_dispatcher(
    candidate: Settings,
    client_factory,
    targets: dict[str, str],
) -> OutboxDispatcher:
    signing_key = HmacKey(
        candidate.pwr_backend_to_n8n_active_key_id,
        decode_secret_b64(
            "PWR_BACKEND_TO_N8N_ACTIVE_SECRET_B64",
            candidate.pwr_backend_to_n8n_active_secret_b64,
        ),
    )
    transport = SignedWebhookTransport(
        base_url=candidate.n8n_webhook_base.removesuffix("/webhook"),
        native_header_secret=candidate.n8n_webhook_secret,
        signing_key=signing_key,
    )
    instances = tuple(get_instance_registry(candidate))
    return OutboxDispatcher(
        client_factory=client_factory,
        instance_names=instances,
        transport=transport,
        targets=targets,
        worker_id=f"{socket.gethostname()}:{os.getpid()}",
        poll_seconds=candidate.dispatcher_poll_seconds,
        lease_seconds=candidate.dispatcher_lease_seconds,
        batch_size=candidate.dispatcher_batch_size,
    )


def build_integration_watchdog(
    candidate: Settings,
    client_factory,
) -> IntegrationWatchdog:
    return IntegrationWatchdog(
        client_factory=client_factory,
        instance_names=tuple(get_instance_registry(candidate)),
    )
```

Task 15 changes only secret acquisition in this factory from the direct setting to
`read_secret(direct, file_path)`; its signature and return type remain stable.
Factory tests pass a candidate `Settings` object and assert that no module-global
settings object is read.

Add a settings-bound lifespan to the current FastAPI construction:

```python
# backend/app/main.py
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI


def build_lifespan(candidate_settings: Settings):
    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        stop_event = asyncio.Event()
        tasks: list[asyncio.Task] = []
        if candidate_settings.dispatcher_enabled:
            dispatcher = get_outbox_dispatcher(candidate_settings)
            watchdog = get_integration_watchdog(candidate_settings)
            tasks.append(asyncio.create_task(dispatcher.run(stop_event)))

            async def watchdog_loop():
                while not stop_event.is_set():
                    for instance in get_instance_registry():
                        try:
                            await watchdog.run_once(instance)
                        except Exception:
                            logger.exception(
                                "Watchdog cycle failed for instance %s", instance
                            )
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=60)
                    except TimeoutError:
                        pass

            tasks.append(asyncio.create_task(watchdog_loop()))
        try:
            yield
        finally:
            stop_event.set()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    return app_lifespan
```

In this task, pass `lifespan=build_lifespan(settings)` to the existing `FastAPI`
construction. Task 16 extracts the complete application factory and changes that
argument to `build_lifespan(candidate_settings)`. Tests use
`dispatcher_enabled=false` unless they explicitly inject a dispatcher.

- [ ] **Step 4: Run transport, dispatcher, lifespan, and Odoo watchdog tests**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_signed_webhook_transport.py \
  tests/test_outbox_dispatcher.py \
  tests/test_n8n_webhook.py \
  tests/test_auth_routes.py \
  -q

cd ..
docker compose --profile odoo19-trial run --rm --no-deps odoo19-trial \
  --database masterfischer_o19_foundation_test \
  --db-filter '^masterfischer_o19_foundation_test$' \
  --workers=0 --max-cron-threads=0 --without-demo=all \
  --update picking_assistant_integration \
  --test-tags /picking_assistant_integration \
  --stop-after-init
```

Expected: focused Backend tests pass; legacy v1 transport tests remain unchanged; Odoo watchdog tests pass.

- [ ] **Step 5: Commit durable delivery**

```bash
git add \
  backend/app/dependencies.py \
  backend/app/main.py \
  backend/app/services/outbox_dispatcher.py \
  backend/app/services/signed_webhook_transport.py \
  backend/app/services/workflow_targets.py \
  backend/tests/test_outbox_dispatcher.py \
  backend/tests/test_signed_webhook_transport.py \
  backend/tests/test_workflow_targets.py \
  odoo/addons/picking_assistant_integration/models/integration_job.py \
  odoo/addons/picking_assistant_integration/tests/test_receipts_callbacks.py
git commit -m "feat(events): dispatch durable outbox events with signed bytes"
```

### Task 10: Signed Acceptance and Callback Routes

**Files:**
- Create: `backend/app/routers/n8n_v2.py`
- Create: `backend/tests/test_n8n_v2_routes.py`
- Modify: `backend/app/dependencies.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/models/events.py` only if test-driven response fields require alignment
- Preserve: `backend/app/routers/n8n_internal.py` as explicitly legacy v1

**Interfaces:**
- Consumes: `verify_signature()` from Task 2 and receipt RPCs from Task 8.
- Produces: `VerifiedInternalRequest`,
  `build_n8n_to_backend_keyring(candidate_settings)`,
  `verify_n8n_to_backend_request(request)`,
  `get_callback_odoo_client(odoo_instance)`,
  `POST /api/internal/n8n/v2/events/accept`, and
  `POST /api/internal/n8n/v2/callbacks/status`.

- [ ] **Step 1: Write failing fail-before-Odoo and instance-routing tests**

```python
# backend/tests/test_n8n_v2_routes.py
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_n8n_to_backend_keyring, get_signature_now
from app.main import app
from app.models.webhook_security import HmacKey, HmacKeyring
from app.services.hmac_signing import sign_request

TARGET = "/api/internal/n8n/v2/callbacks/status"
CALLBACK = {
    "schema_version": "v2",
    "callback_name": "quality.assessment.status.v1",
    "callback_id": "cbdc037f-8458-4be0-938a-4bc8242116af",
    "source_event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
    "correlation_id": "0b2f7909-4ad9-44c1-8527-e775fe6d4bec",
    "odoo_instance": "o19-a",
    "job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    "sequence": 1,
    "attempt": 1,
    "delivery_generation": 1,
    "processing_lease_token": "lease-" + ("x" * 40),
    "status": "running",
    "execution_id": "execution-1",
    "occurred_at": "2026-07-23T12:00:04Z",
    "next_retry_at": None,
    "result": {},
    "error": None,
    "metrics": {},
}


@pytest.fixture(autouse=True)
def fixed_signature_clock():
    app.dependency_overrides[get_signature_now] = lambda: datetime.fromtimestamp(
        1760000000, tz=timezone.utc
    )
    yield
    app.dependency_overrides.clear()


def signed_headers(body: bytes, target=TARGET, generation=1):
    signed = sign_request(
        method="POST",
        target=target,
        delivery_generation=generation,
        timestamp=1760000000,
        nonce="123e4567-e89b-42d3-a456-426614174000",
        raw_body=body,
        key=HmacKey("n2b-test", b"2" * 32),
    )
    return {
        **signed.as_http_headers(),
        "Idempotency-Key": CALLBACK["callback_id"],
        "Content-Type": "application/json",
    }


class FakeOdoo:
    def __init__(self, name):
        self.name = name
        self.calls = []

    async def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method, args))
        return {
            "status": "applied",
            "job_id": CALLBACK["job_id"],
            "sequence": 1,
        }


def test_invalid_signature_causes_no_odoo_call(monkeypatch):
    clients = {"o19-a": FakeOdoo("a")}
    monkeypatch.setattr("app.dependencies._get_cached_client", clients.__getitem__)
    app.dependency_overrides[get_n8n_to_backend_keyring] = lambda: HmacKeyring(
        active=HmacKey("n2b-test", b"2" * 32)
    )
    try:
        body = json.dumps(CALLBACK, separators=(",", ":")).encode()
        headers = signed_headers(body)
        headers["X-PWR-Signature"] = "v1=" + ("0" * 64)
        response = TestClient(app).post(TARGET, content=body, headers=headers)
        assert response.status_code == 401
        assert clients["o19-a"].calls == []
    finally:
        app.dependency_overrides.clear()


def test_signed_callback_writes_only_named_instance(monkeypatch):
    clients = {"o19-a": FakeOdoo("a"), "o19-b": FakeOdoo("b")}
    monkeypatch.setattr("app.dependencies._get_cached_client", clients.__getitem__)
    app.dependency_overrides[get_n8n_to_backend_keyring] = lambda: HmacKeyring(
        active=HmacKey("n2b-test", b"2" * 32)
    )
    try:
        body = json.dumps(CALLBACK, separators=(",", ":")).encode()
        with TestClient(app) as client:
            response = client.post(TARGET, content=body, headers=signed_headers(body))
        assert response.status_code == 200
        assert len(clients["o19-a"].calls) == 1
        assert clients["o19-b"].calls == []
    finally:
        app.dependency_overrides.clear()


def test_header_generation_must_equal_signed_body(monkeypatch):
    clients = {"o19-a": FakeOdoo("a")}
    monkeypatch.setattr("app.dependencies._get_cached_client", clients.__getitem__)
    app.dependency_overrides[get_n8n_to_backend_keyring] = lambda: HmacKeyring(
        active=HmacKey("n2b-test", b"2" * 32)
    )
    try:
        body = json.dumps(CALLBACK, separators=(",", ":")).encode()
        response = TestClient(app).post(
            TARGET, content=body, headers=signed_headers(body, generation=2)
        )
        assert response.status_code == 409
        assert clients["o19-a"].calls == []
    finally:
        app.dependency_overrides.clear()
```

Add acceptance cases for valid `process=true`, replay `process=false`, event ID/idempotency mismatch, unknown instance `403`, query `400`, and malformed schema `422`. Assert every rejection before schema/instance validation leaves all fake Odoo call lists empty.

- [ ] **Step 2: Run the route tests and confirm the v2 router is absent**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_n8n_v2_routes.py \
  tests/test_n8n_internal_routes.py \
  -q
```

Expected: v2 route tests fail with `404` or missing dependency; legacy callback tests remain green.

- [ ] **Step 3: Verify raw HTTP first, then parse and route**

Add a value object and dependency:

```python
# backend/app/dependencies.py
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Request

from app.config import Settings, decode_secret_b64, settings
from app.models.webhook_security import HmacKey, HmacKeyring, VerifiedSignature
from app.services.hmac_signing import SignatureError, verify_signature


@dataclass(frozen=True)
class VerifiedInternalRequest:
    signature: VerifiedSignature
    raw_body: bytes


def get_signature_now() -> datetime:
    return datetime.now(timezone.utc)


def build_n8n_to_backend_keyring(candidate: Settings) -> HmacKeyring:
    active = HmacKey(
        candidate.pwr_n8n_to_backend_active_key_id,
        decode_secret_b64(
            "PWR_N8N_TO_BACKEND_ACTIVE_SECRET_B64",
            candidate.pwr_n8n_to_backend_active_secret_b64,
        ),
    )
    previous = None
    if candidate.pwr_n8n_to_backend_previous_key_id:
        previous = HmacKey(
            candidate.pwr_n8n_to_backend_previous_key_id,
            decode_secret_b64(
                "PWR_N8N_TO_BACKEND_PREVIOUS_SECRET_B64",
                candidate.pwr_n8n_to_backend_previous_secret_b64,
            ),
        )
    return HmacKeyring(active=active, previous=previous)


def get_n8n_to_backend_keyring() -> HmacKeyring:
    # Transitional dependency until Task 16 binds the keyring to app.state.runtime.
    return build_n8n_to_backend_keyring(settings)


async def verify_n8n_to_backend_request(
    request: Request,
    keyring: HmacKeyring = Depends(get_n8n_to_backend_keyring),
    now: datetime = Depends(get_signature_now),
) -> VerifiedInternalRequest:
    raw_body = await request.body()
    raw_path = request.scope.get("raw_path", request.url.path.encode("ascii"))
    try:
        signature = verify_signature(
            actual_method=request.method,
            actual_target=raw_path.decode("ascii"),
            raw_query=request.scope.get("query_string", b""),
            raw_body=raw_body,
            headers=dict(request.headers),
            keyring=keyring,
            now=now,
            max_skew_seconds=settings.pwr_hmac_max_skew_seconds,
        )
    except SignatureError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"reason_code": exc.reason_code},
        ) from exc
    return VerifiedInternalRequest(signature=signature, raw_body=raw_body)


def get_callback_odoo_client(odoo_instance: str) -> OdooClient:
    registry = get_instance_registry()
    if odoo_instance not in registry:
        raise HTTPException(status_code=403, detail="Unbekannte Callback-Instanz.")
    return _get_cached_client(odoo_instance)
```

The autouse fixture makes stale-signature behavior deterministic instead of
depending on the wall clock.

Create the router with no browser or legacy dependencies:

```python
# backend/app/routers/n8n_v2.py
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import ValidationError

from app.dependencies import (
    VerifiedInternalRequest,
    get_callback_odoo_client,
    verify_n8n_to_backend_request,
)
from app.models.events import (
    CallbackApplyResponse,
    CallbackEnvelopeV2,
    EventAcceptanceRequest,
    EventAcceptanceResponse,
)
from app.services.odoo_client import OdooAPIError

router = APIRouter(prefix="/internal/n8n/v2")


def _parse(model, raw_body: bytes):
    try:
        return model.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


@router.post("/events/accept", response_model=EventAcceptanceResponse)
async def accept_event(
    verified: VerifiedInternalRequest = Depends(verify_n8n_to_backend_request),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    body = _parse(EventAcceptanceRequest, verified.raw_body)
    if idempotency_key != str(body.event_id):
        raise HTTPException(status_code=409, detail="Event idempotency mismatch.")
    if verified.signature.delivery_generation != body.delivery_generation:
        raise HTTPException(status_code=409, detail="Delivery generation mismatch.")
    odoo = get_callback_odoo_client(body.odoo_instance)
    try:
        result = await odoo.execute_kw(
            "picking.assistant.event.receipt",
            "api_accept_event",
            [
                str(body.event_id),
                str(body.job_id),
                body.payload_fingerprint,
                body.ingress_key_id,
                str(body.ingress_nonce),
                body.delivery_generation,
                verified.signature.key_id,
                verified.signature.nonce,
            ],
        )
    except OdooAPIError as exc:
        raise HTTPException(status_code=409, detail="Event acceptance conflict.") from exc
    if str(result["job_id"]) != str(body.job_id):
        raise HTTPException(status_code=409, detail="Event job mismatch.")
    return EventAcceptanceResponse(
        accepted=True,
        event_id=body.event_id,
        process=bool(result["process"]),
        processing_lease_token=result.get("processing_lease_token") or None,
    )


@router.post("/callbacks/status", response_model=CallbackApplyResponse)
async def apply_callback(
    verified: VerifiedInternalRequest = Depends(verify_n8n_to_backend_request),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    body = _parse(CallbackEnvelopeV2, verified.raw_body)
    if idempotency_key != str(body.callback_id):
        raise HTTPException(status_code=409, detail="Callback idempotency mismatch.")
    if verified.signature.delivery_generation != body.delivery_generation:
        raise HTTPException(status_code=409, detail="Delivery generation mismatch.")
    odoo = get_callback_odoo_client(body.odoo_instance)
    try:
        result = await odoo.execute_kw(
            "picking.assistant.callback.receipt",
            "api_apply_callback",
            [
                body.model_dump(mode="json"),
                verified.signature.fingerprint,
                verified.signature.key_id,
                verified.signature.nonce,
            ],
        )
    except OdooAPIError as exc:
        raise HTTPException(status_code=409, detail="Callback state conflict.") from exc
    if str(result["job_id"]) != str(body.job_id):
        raise HTTPException(status_code=409, detail="Callback job mismatch.")
    return CallbackApplyResponse.model_validate(result)
```

Register the router under `/api`. Do not add `get_odoo_client`, `WriteRequestContext`, `X-N8N-Callback-Secret`, or a `local` fallback to either route. The legacy router stays reachable only on the internal network until its workflows are migrated.

- [ ] **Step 4: Run v2 and legacy callback suites**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_hmac_signing.py \
  tests/test_n8n_v2_routes.py \
  tests/test_n8n_internal_routes.py \
  -q
```

Expected: every negative signature/instance/generation case returns its specified status with zero Odoo calls; v2 and legacy suites pass.

- [ ] **Step 5: Commit signed internal status routes**

```bash
git add \
  backend/app/dependencies.py \
  backend/app/main.py \
  backend/app/models/events.py \
  backend/app/routers/n8n_v2.py \
  backend/tests/test_n8n_v2_routes.py
git commit -m "feat(callbacks): bind signed v2 status to source instance"
```

### Task 11: Job-Bound Media and Artifact Contracts

**Files:**
- Create: `backend/app/services/binary_validation.py`
- Create: `backend/tests/test_binary_validation.py`
- Create: `backend/tests/test_n8n_v2_binary_routes.py`
- Create: `odoo/addons/picking_assistant_integration/models/resources.py`
- Create: `odoo/addons/picking_assistant_integration/tests/test_resources.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/app/routers/n8n_v2.py`
- Modify: `odoo/addons/picking_assistant_integration/models/__init__.py`
- Modify: `odoo/addons/picking_assistant_integration/data/ir_cron.xml`

**Interfaces:**
- Consumes: signed request dependency Task 10 and current processing generation Task 8.
- Produces: `ValidatedBinary`, `validate_image`, `validate_pdf`, `validate_zpl`, `sanitize_filename`; Odoo attachment bindings; signed media GET and artifact POST.

- [ ] **Step 1: Write failing malicious-binary and route tests**

```python
# backend/tests/test_binary_validation.py
from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfWriter

from app.services.binary_validation import (
    BinaryValidationError,
    validate_image,
    validate_pdf,
    validate_zpl,
)


def png_bytes(size=(32, 32)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, "white").save(stream, format="PNG")
    return stream.getvalue()


def test_valid_single_frame_png_passes():
    result = validate_image(png_bytes(), declared_mime="image/png")
    assert result.mime_type == "image/png"
    assert result.size > 0
    assert len(result.sha256) == 64


def test_image_polyglot_and_more_than_24_megapixels_fail():
    with pytest.raises(BinaryValidationError, match="polyglot"):
        validate_image(png_bytes() + b"%PDF-1.7", declared_mime="image/png")
    with pytest.raises(BinaryValidationError, match="24 megapixels"):
        validate_image(
            png_bytes((5000, 5000)),
            declared_mime="image/png",
        )


def test_pdf_javascript_and_embedded_file_fail():
    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_js("app.alert('x')")
    writer.write(stream)
    with pytest.raises(BinaryValidationError, match="JavaScript"):
        validate_pdf(stream.getvalue())

    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_attachment("secret.txt", b"secret")
    writer.write(stream)
    with pytest.raises(BinaryValidationError, match="embedded"):
        validate_pdf(stream.getvalue())


def test_zpl_allows_layout_but_rejects_config_and_tilde_commands():
    assert validate_zpl(b"^XA^FO20,20^FDParcel 42^FS^XZ").mime_type == (
        "application/zpl"
    )
    for body in (b"^XA^JUS^XZ", b"~JA", b"^XA^DFE:FORMAT.ZPL^XZ"):
        with pytest.raises(BinaryValidationError):
            validate_zpl(body)
```

```python
# backend/tests/test_n8n_v2_binary_routes.py
from datetime import datetime, timezone
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.dependencies import (
    get_n8n_to_backend_keyring,
    get_signature_now,
)
from app.main import app
from app.models.webhook_security import HmacKey, HmacKeyring
from app.services.hmac_signing import sign_request


class FakeOdoo:
    def __init__(self):
        self.calls = []

    async def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method, args))
        if method == "api_reserve_request_nonce":
            return True
        if method == "api_store_job_artifact":
            return {"artifact_ref": "artifact-1", "replayed": False}
        raise AssertionError((model, method, args))


@pytest.fixture
def fake_odoo(monkeypatch):
    fake = FakeOdoo()
    monkeypatch.setattr(
        "app.dependencies._get_cached_client",
        lambda name: fake if name == "o19" else (_ for _ in ()).throw(KeyError(name)),
    )
    return fake


@pytest.fixture
def client():
    app.dependency_overrides[get_signature_now] = lambda: datetime.fromtimestamp(
        1760000000, tz=timezone.utc
    )
    app.dependency_overrides[get_n8n_to_backend_keyring] = lambda: HmacKeyring(
        active=HmacKey("n2b-test", b"2" * 32)
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def signed_request_headers():
    def build(path: str, body: bytes, *, generation: int):
        signed = sign_request(
            method="POST",
            target=path,
            delivery_generation=generation,
            timestamp=1760000000,
            nonce="123e4567-e89b-42d3-a456-426614174050",
            raw_body=body,
            key=HmacKey("n2b-test", b"2" * 32),
        )
        return {
            **signed.as_http_headers(),
            "Idempotency-Key": "artifact-request-1",
            "Content-Type": "application/pdf",
        }

    return build


@pytest.fixture
def minimal_pdf():
    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(stream)
    return stream.getvalue()


def test_media_bad_signature_never_reads_odoo(client, fake_odoo):
    response = client.get(
        "/api/internal/instances/o19/jobs/"
        "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88/media/media-1",
        headers={"X-PWR-Signature": "v1=" + ("0" * 64)},
    )
    assert response.status_code == 401
    assert fake_odoo.calls == []


def test_artifact_pdf_is_raw_and_job_bound(
    signed_request_headers, client, fake_odoo, minimal_pdf
):
    path = (
        "/api/internal/instances/o19/jobs/"
        "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88/events/"
        "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32/artifacts/pdf"
    )
    response = client.post(
        path,
        content=minimal_pdf,
        headers=signed_request_headers(path, minimal_pdf, generation=1),
    )
    assert response.status_code == 201
    call = fake_odoo.calls[-1]
    assert call[1] == "api_store_job_artifact"
    assert call[2][0] == "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88"
    assert call[2][2] == "pdf"
```

The route fixture must also test wrong instance, wrong job, wrong source event, stale generation, replay nonce, 15 MiB/10 MiB limits, false MIME, animated WebP/GIF rejection, encrypted PDF, 21 pages, and prohibited ZPL commands.

In `test_resources.py`, add a real Odoo transaction test that creates two expired
attachments, places `legal_hold=True` on one owning job, runs
`_cron_cleanup_job_resources(limit=1000)`, and asserts that only the non-held
attachment is removed. Add a second test proving an attachment with no explicit
retention deadline is never selected by the cron.

- [ ] **Step 2: Add parser dependencies and confirm the tests are red**

Append:

```text
Pillow==11.*
pypdf==5.*
```

Run:

```bash
cd backend
python3 -m pip install --target .deps -r requirements.txt
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_binary_validation.py \
  tests/test_n8n_v2_binary_routes.py \
  -q
```

Expected: imports resolve, then tests fail because validators and binary routes do not exist.

- [ ] **Step 3: Validate formats before Odoo persistence**

Create immutable results and fail-closed validators:

```python
# backend/app/services/binary_validation.py
from __future__ import annotations

import hashlib
import re
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from typing import Callable

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.generic import DictionaryObject, IndirectObject


class BinaryValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedBinary:
    mime_type: str
    size: int
    sha256: str
    extension: str


def _result(body: bytes, mime_type: str, extension: str) -> ValidatedBinary:
    return ValidatedBinary(
        mime_type=mime_type,
        size=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        extension=extension,
    )


def sanitize_filename(value: str) -> str:
    leaf = PurePath(value.replace("\\", "/")).name
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", leaf).strip("._")
    return (clean[:120] or "upload")


def _strict_image_container(body: bytes, image_format: str) -> None:
    if image_format == "JPEG":
        if not body.startswith(b"\xff\xd8\xff") or not body.endswith(b"\xff\xd9"):
            raise BinaryValidationError("JPEG is malformed or polyglot")
    elif image_format == "PNG":
        if not body.startswith(b"\x89PNG\r\n\x1a\n") or not body.endswith(
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        ):
            raise BinaryValidationError("PNG is malformed or polyglot")
    elif image_format == "WEBP":
        if (
            len(body) < 12
            or body[:4] != b"RIFF"
            or body[8:12] != b"WEBP"
            or int.from_bytes(body[4:8], "little") + 8 != len(body)
        ):
            raise BinaryValidationError("WebP is malformed or polyglot")


def validate_image(body: bytes, *, declared_mime: str) -> ValidatedBinary:
    if len(body) > 15 * 1024 * 1024:
        raise BinaryValidationError("Image exceeds 15 MiB")
    allowed = {
        "JPEG": ("image/jpeg", "jpg"),
        "PNG": ("image/png", "png"),
        "WEBP": ("image/webp", "webp"),
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(body)) as image:
                image_format = str(image.format)
                width, height = image.size
                frames = int(getattr(image, "n_frames", 1))
                image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombWarning) as exc:
        raise BinaryValidationError("Image decoder rejected input") from exc
    if image_format not in allowed:
        raise BinaryValidationError("Only JPEG, PNG, and WebP are allowed")
    expected_mime, extension = allowed[image_format]
    if declared_mime != expected_mime:
        raise BinaryValidationError("Declared MIME does not match image")
    if width * height > 24_000_000:
        raise BinaryValidationError("Image exceeds 24 megapixels")
    if frames != 1:
        raise BinaryValidationError("Animated or multi-frame image is forbidden")
    _strict_image_container(body, image_format)
    return _result(body, expected_mime, extension)


def _walk_pdf(value, seen: set[int]) -> None:
    if isinstance(value, IndirectObject):
        identity = value.idnum
        if identity in seen:
            return
        seen.add(identity)
        value = value.get_object()
    if isinstance(value, DictionaryObject):
        action = str(value.get("/S", ""))
        if action == "/JavaScript" or "/JS" in value:
            raise BinaryValidationError("PDF JavaScript is forbidden")
        if action == "/Launch":
            raise BinaryValidationError("PDF launch actions are forbidden")
        if "/EmbeddedFiles" in value or "/EmbeddedFile" in value:
            raise BinaryValidationError("PDF embedded files are forbidden")
        for child in value.values():
            _walk_pdf(child, seen)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _walk_pdf(child, seen)


def validate_pdf(body: bytes) -> ValidatedBinary:
    if len(body) > 10 * 1024 * 1024:
        raise BinaryValidationError("PDF exceeds 10 MiB")
    if not body.startswith(b"%PDF-"):
        raise BinaryValidationError("PDF magic is invalid")
    try:
        reader = PdfReader(BytesIO(body), strict=True)
    except Exception as exc:
        raise BinaryValidationError("PDF parser rejected input") from exc
    if reader.is_encrypted:
        raise BinaryValidationError("Encrypted PDF is forbidden")
    if len(reader.pages) > 20:
        raise BinaryValidationError("PDF exceeds 20 pages")
    _walk_pdf(reader.trailer["/Root"], set())
    return _result(body, "application/pdf", "pdf")


_ZPL_COMMAND = re.compile(r"[\^~][A-Z@][A-Z0-9@]?", re.ASCII)
_ZPL_ALLOWED = {
    "^XA", "^XZ", "^FO", "^FD", "^FS", "^A", "^A0", "^BC", "^BQ",
    "^BY", "^CI", "^PW", "^LL", "^LH",
}


def validate_zpl(body: bytes) -> ValidatedBinary:
    if len(body) > 10 * 1024 * 1024:
        raise BinaryValidationError("ZPL exceeds 10 MiB")
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError as exc:
        raise BinaryValidationError("ZPL must be ASCII") from exc
    if not text.startswith("^XA") or not text.endswith("^XZ"):
        raise BinaryValidationError("ZPL requires one ^XA/^XZ document")
    commands = _ZPL_COMMAND.findall(text)
    if any(command.startswith("~") for command in commands):
        raise BinaryValidationError("ZPL tilde commands are forbidden")
    denied = [command for command in commands if command not in _ZPL_ALLOWED]
    if denied:
        raise BinaryValidationError(f"ZPL command is not allowed: {denied[0]}")
    return _result(body, "application/zpl", "zpl")
```

Extend `ir.attachment` with job-bound fields:

```python
# odoo/addons/picking_assistant_integration/models/resources.py
import base64
import hashlib
from uuid import uuid4

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    pwr_job_record_id = fields.Many2one(
        "picking.assistant.integration.job", ondelete="cascade", index=True
    )
    pwr_media_ref = fields.Char(index=True)
    pwr_artifact_ref = fields.Char(index=True)
    pwr_source_event_id = fields.Char(index=True)
    pwr_artifact_kind = fields.Char(index=True)
    pwr_sha256 = fields.Char(index=True)
    pwr_original_filename = fields.Char()
    pwr_retention_until = fields.Datetime(index=True)

    _job_media_unique = models.Constraint(
        "UNIQUE(pwr_job_record_id, pwr_media_ref)",
        "Media reference must be unique per job.",
    )
    _job_artifact_unique = models.Constraint(
        "UNIQUE(pwr_job_record_id, pwr_source_event_id, pwr_artifact_kind)",
        "Artifact kind must be unique per job event.",
    )


class PickingAssistantIntegrationJobResources(models.Model):
    _inherit = "picking.assistant.integration.job"

    def _require_current_generation(self, generation):
        self.ensure_one()
        if self.delivery_generation != int(generation):
            raise ValidationError("Stale delivery generation.")
        receipt = self.env["picking.assistant.event.receipt"].search(
            [
                ("job_record_id", "=", self.id),
                ("state", "=", "processing"),
                ("processing_lease_expires_at", ">", fields.Datetime.now()),
            ],
            limit=1,
        )
        if not receipt:
            raise ValidationError("Job has no active processing lease.")
        return receipt

    def _bind_job_media(
        self,
        attachment,
        *,
        media_ref,
        sha256,
        retention_until=False,
        original_filename=False,
    ):
        self.ensure_one()
        attachment.write(
            {
                "pwr_job_record_id": self.id,
                "pwr_media_ref": media_ref,
                "pwr_sha256": sha256,
                "pwr_original_filename": original_filename or False,
                "pwr_retention_until": retention_until or False,
            }
        )
        return media_ref

    @api.model
    def api_get_job_media(self, job_id, media_ref, generation):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        job = self.sudo().search([("job_id", "=", job_id)], limit=1)
        if not job:
            raise ValidationError("Job not found.")
        job._require_current_generation(generation)
        attachment = self.env["ir.attachment"].sudo().search(
            [
                ("pwr_job_record_id", "=", job.id),
                ("pwr_media_ref", "=", media_ref),
            ],
            limit=1,
        )
        if not attachment:
            raise ValidationError("Media not found.")
        return {
            "content_base64": attachment.datas.decode()
            if isinstance(attachment.datas, bytes)
            else attachment.datas,
            "mimetype": attachment.mimetype,
            "sha256": attachment.pwr_sha256,
            "original_filename": attachment.pwr_original_filename or "",
        }

    @api.model
    def api_store_job_artifact(
        self,
        job_id,
        source_event_id,
        artifact_kind,
        generation,
        content_base64,
        sha256,
        mimetype,
        filename,
    ):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        job = self.sudo().search([("job_id", "=", job_id)], limit=1)
        if not job:
            raise ValidationError("Job not found.")
        job._require_current_generation(generation)
        outbox = self.env["picking.assistant.outbox"].sudo().search(
            [
                ("job_record_id", "=", job.id),
                ("event_id", "=", source_event_id),
            ],
            limit=1,
        )
        if not outbox:
            raise ValidationError("Source event not found.")
        raw = base64.b64decode(content_base64, validate=True)
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValidationError("Artifact hash mismatch.")
        existing = self.env["ir.attachment"].sudo().search(
            [
                ("pwr_job_record_id", "=", job.id),
                ("pwr_source_event_id", "=", source_event_id),
                ("pwr_artifact_kind", "=", artifact_kind),
            ],
            limit=1,
        )
        if existing:
            if existing.pwr_sha256 != sha256:
                raise ValidationError("Artifact replay has different bytes.")
            return {"artifact_ref": existing.pwr_artifact_ref, "replayed": True}
        artifact_ref = str(uuid4())
        attachment = self.env["ir.attachment"].sudo().create(
            {
                "name": filename,
                "type": "binary",
                "datas": content_base64,
                "mimetype": mimetype,
                "res_model": self._name,
                "res_id": job.id,
                "pwr_job_record_id": job.id,
                "pwr_artifact_ref": artifact_ref,
                "pwr_source_event_id": source_event_id,
                "pwr_artifact_kind": artifact_kind,
                "pwr_sha256": sha256,
            }
        )
        return {"artifact_ref": artifact_ref, "replayed": False}

    @api.model
    def _cron_cleanup_job_resources(self, limit=1000):
        attachments = self.env["ir.attachment"].sudo().search(
            [
                ("pwr_job_record_id", "!=", False),
                ("pwr_retention_until", "!=", False),
                ("pwr_retention_until", "<=", fields.Datetime.now()),
                ("pwr_job_record_id.legal_hold", "=", False),
            ],
            limit=int(limit),
        )
        processed = len(attachments)
        attachments.unlink()
        remaining = self.env["ir.attachment"].sudo().search_count(
            [
                ("pwr_job_record_id", "!=", False),
                ("pwr_retention_until", "!=", False),
                ("pwr_retention_until", "<=", fields.Datetime.now()),
                ("pwr_job_record_id.legal_hold", "=", False),
            ]
        )
        self.env["ir.cron"]._commit_progress(processed, remaining=remaining)
        return processed
```

Register the cleanup daily. The Foundation never invents a business completion
timestamp: Visual Quality sets the media deadline to alert-close/review-close plus
30 days, and Shipping sets artifact deadlines to shipment/cancellation plus 90
days. Until a feature add-on records that explicit deadline, the attachment remains
out of the cleanup domain. Findings and decision-audit retention belong to the
Visual Quality add-on; the shared job `legal_hold` blocks every linked resource.

Add guarded `api_reserve_request_nonce(direction, key_id, nonce, expires_at, job_id, delivery_generation)` to the nonce model. It rejects duplicate n8n-to-backend nonces, checks the named job and current generation, and creates the nonce before resource access.

Add these exact FastAPI routes:

```text
GET  /api/internal/instances/{odoo_instance}/jobs/{job_id}/media/{media_ref}
POST /api/internal/instances/{odoo_instance}/jobs/{job_id}/events/{source_event_id}/artifacts/{artifact_kind}
```

Both depend on `verify_n8n_to_backend_request`. They require header generation to equal the path-bound job generation verified in Odoo. The media route:

1. rejects non-empty query and invalid HMAC before Odoo;
2. reserves the signed nonce;
3. calls `api_get_job_media`;
4. base64-decodes internal JSON-RPC data;
5. verifies the returned SHA-256;
6. calls `validate_image`;
7. returns raw bytes with the validated MIME and `Content-Disposition: inline` using a server-generated `job_id-media_ref.ext` filename.

The artifact route:

1. accepts only path kinds `pdf` and `zpl`;
2. reads raw body once and validates HMAC against it;
3. requires a 1-128 ASCII `Idempotency-Key`;
4. reserves the nonce;
5. calls `validate_pdf` or `validate_zpl`;
6. generates `job_id-artifact_kind.ext`;
7. base64-encodes only for the internal Odoo JSON-RPC hop;
8. calls `api_store_job_artifact`;
9. returns `201` for a new artifact and `200` for an identical replay.

No event, callback, HTTP log, or n8n execution JSON contains those base64 bytes.

- [ ] **Step 4: Run binary, route, Odoo resource, and dependency tests**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_binary_validation.py \
  tests/test_n8n_v2_binary_routes.py \
  tests/test_n8n_v2_routes.py \
  -q

cd ..
docker compose --profile odoo19-trial run --rm --no-deps odoo19-trial \
  --database masterfischer_o19_foundation_test \
  --db-filter '^masterfischer_o19_foundation_test$' \
  --workers=0 --max-cron-threads=0 --without-demo=all \
  --update picking_assistant_integration \
  --test-tags /picking_assistant_integration \
  --stop-after-init
```

Expected: all malicious inputs fail with no stored attachment; valid image/PDF/ZPL round trips pass; Odoo resource tests report zero failures.

- [ ] **Step 5: Commit resource contracts**

```bash
git add \
  backend/requirements.txt \
  backend/app/routers/n8n_v2.py \
  backend/app/services/binary_validation.py \
  backend/tests/test_binary_validation.py \
  backend/tests/test_n8n_v2_binary_routes.py \
  odoo/addons/picking_assistant_integration/models/__init__.py \
  odoo/addons/picking_assistant_integration/models/resources.py \
  odoo/addons/picking_assistant_integration/data/ir_cron.xml \
  odoo/addons/picking_assistant_integration/tests/test_resources.py
git commit -m "feat(integration): add signed job media and artifact transfer"
```

### Task 12: Odoo-19 Core Idempotency Handoff

**Handoff gate:** Start this task only after `wave1-odoo19-handoff` exists and the Foundation branch has rebased onto the integration branch.

**Files:**
- Create: `odoo/addons/picking_assistant_core/models/idempotency.py`
- Create: `odoo/addons/picking_assistant_core/data/ir_cron.xml`
- Create: `odoo/addons/picking_assistant_core/migrations/19.0.2.0.0/pre-migrate.py`
- Create: `odoo/addons/picking_assistant_core/tests/__init__.py`
- Create: `odoo/addons/picking_assistant_core/tests/test_idempotency.py`
- Modify: `odoo/addons/picking_assistant_core/models/picking_assistant.py`
- Modify: `odoo/addons/picking_assistant_core/models/__init__.py`
- Modify: `odoo/addons/picking_assistant_core/__manifest__.py`
- Modify: `odoo/addons/picking_assistant_core/security/ir.model.access.csv`
- Modify: `backend/app/services/mobile_workflow.py`
- Modify: `backend/tests/test_mobile_workflow_service.py`

**Interfaces:**
- Consumes: `group_api_service` and API guard from Task 5; `WriteRequestContext.principal_scope` from Task 7.
- Produces: scoped `api_reserve_request`, `api_finalize_request`, `api_abort_request`, `_cron_cleanup_expired`, and explicit API-service checks on existing Core RPC methods.

- [ ] **Step 1: Write failing scoped-idempotency tests**

```python
# odoo/addons/picking_assistant_core/tests/test_idempotency.py
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user


class TestScopedIdempotency(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.api_user = new_test_user(
            cls.env,
            login="core_api",
            groups="base.group_user,picking_assistant_integration.group_api_service",
        )
        cls.picker = new_test_user(
            cls.env,
            login="core_picker",
            groups="base.group_user,picking_assistant_integration.group_picker",
        )

    def test_picker_cannot_call_public_reservation_method(self):
        with self.assertRaises(AccessError):
            self.env["picking.assistant.idempotency"].with_user(
                self.picker
            ).api_reserve_request(
                "confirm-line",
                "same-key",
                "a" * 64,
                "user:7",
            )

    def test_same_key_is_independent_between_principal_scopes(self):
        model = self.env["picking.assistant.idempotency"].with_user(self.api_user)
        first = model.api_reserve_request(
            "confirm-line", "same-key", "a" * 64, "user:7"
        )
        second = model.api_reserve_request(
            "confirm-line", "same-key", "a" * 64, "user:8"
        )
        self.assertEqual(first["status"], "reserved")
        self.assertEqual(second["status"], "reserved")
        self.assertNotEqual(first["entry_id"], second["entry_id"])

    def test_same_scope_key_with_different_fingerprint_conflicts(self):
        model = self.env["picking.assistant.idempotency"].with_user(self.api_user)
        model.api_reserve_request(
            "confirm-line", "same-key", "a" * 64, "user:7"
        )
        conflict = model.api_reserve_request(
            "confirm-line", "same-key", "b" * 64, "user:7"
        )
        self.assertEqual(conflict["status"], "conflict")
        self.assertEqual(conflict["status_code"], 409)

    def test_expired_row_is_reused_without_transaction_rollback(self):
        model = self.env["picking.assistant.idempotency"].with_user(self.api_user)
        first = model.api_reserve_request(
            "confirm-line", "same-key", "a" * 64, "user:7", ttl_seconds=1
        )
        entry = self.env["picking.assistant.idempotency"].browse(first["entry_id"])
        entry.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        second = model.api_reserve_request(
            "confirm-line", "same-key", "b" * 64, "user:7"
        )
        self.assertEqual(second["status"], "reserved")
        self.assertEqual(second["entry_id"], first["entry_id"])
        self.assertEqual(entry.request_fingerprint, "b" * 64)
```

Update the backend test expectation:

```python
async def test_begin_idempotent_request_passes_server_principal_scope(service):
    context = WriteRequestContext(
        idempotency_key="confirm:7:42",
        identity=PickerIdentity(user_id=7, device_id="device-42"),
        principal_scope="user:7",
    )
    await service.begin_idempotent_request(
        "confirm-line", context, "a" * 64, picking_id=42
    )
    call = service._odoo.execute_kw.await_args
    assert call.args[2][3] == "user:7"
```

- [ ] **Step 2: Run Core and backend tests to see old behavior**

Run:

```bash
docker compose --profile odoo19-trial run --rm --no-deps odoo19-trial \
  --database masterfischer_o19_foundation_test \
  --db-filter '^masterfischer_o19_foundation_test$' \
  --workers=0 --max-cron-threads=0 --without-demo=all \
  --update picking_assistant_integration,picking_assistant_core \
  --test-tags /picking_assistant_core \
  --stop-after-init

cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_mobile_workflow_service.py -q
```

Expected: Odoo cannot discover the new tests/model contract; backend still calls the old unscoped method.

- [ ] **Step 3: Migrate the model without whole-transaction rollback**

Move only `PickingAssistantIdempotency` out of `picking_assistant.py`; keep `StockPicking` there. Update the manifest:

```python
{
    "name": "Picking Assistant Core",
    "version": "19.0.2.0.0",
    "author": "Mobile Picking Assistant",
    "category": "Inventory/Barcode",
    "summary": "Mobile claim and scoped idempotency support",
    "depends": [
        "stock",
        "stock_picking_batch",
        "picking_assistant_integration",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
```

The pre-migration is idempotent:

```python
# migrations/19.0.2.0.0/pre-migrate.py
from odoo.tools import SQL


def migrate(cr, version):
    cr.execute(
        """
        ALTER TABLE picking_assistant_idempotency
        ADD COLUMN IF NOT EXISTS principal_scope varchar
        """
    )
    cr.execute(
        """
        UPDATE picking_assistant_idempotency
           SET principal_scope = 'legacy'
         WHERE principal_scope IS NULL OR principal_scope = ''
        """
    )
    cr.execute(
        """
        ALTER TABLE picking_assistant_idempotency
        DROP CONSTRAINT IF EXISTS picking_assistant_idempotency_key_unique
        """
    )
```

The Odoo-19 model declares:

```python
# models/idempotency.py
import json
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import SQL
from psycopg2 import IntegrityError


class PickingAssistantIdempotency(models.Model):
    _name = "picking.assistant.idempotency"
    _description = "Picking Assistant Idempotency Entry"
    _order = "create_date desc"

    endpoint = fields.Char(required=True, index=True)
    principal_scope = fields.Char(required=True, index=True, default="legacy")
    key = fields.Char(required=True, index=True)
    request_fingerprint = fields.Char(required=True)
    response_payload = fields.Text()
    status_code = fields.Integer(default=200)
    state = fields.Selection(
        [("pending", "Pending"), ("completed", "Completed")],
        default="pending",
        required=True,
        index=True,
    )
    picker_user_id = fields.Many2one("res.users", ondelete="set null")
    device_id = fields.Char()
    picking_id = fields.Many2one("stock.picking", ondelete="set null")
    expires_at = fields.Datetime(required=True, index=True)
    processed_at = fields.Datetime()

    _endpoint_scope_key_unique = models.Constraint(
        "UNIQUE(endpoint, principal_scope, key)",
        "The idempotency key must be unique per operation and principal.",
    )

    def _require_api(self):
        self.env["picking.assistant.api.mixin"]._require_api_service()

    def _payload(self):
        self.ensure_one()
        payload = {
            "status": self.state,
            "entry_id": self.id,
            "status_code": self.status_code or 200,
        }
        if self.response_payload:
            payload["response_payload"] = json.loads(self.response_payload)
        return payload

    @api.model
    def api_reserve_request(
        self,
        endpoint,
        key,
        request_fingerprint,
        principal_scope,
        picking_id=False,
        picker_user_id=False,
        device_id=False,
        ttl_seconds=86400,
    ):
        self._require_api()
        if not principal_scope or principal_scope == "legacy":
            raise ValidationError("A non-legacy principal scope is required.")
        now = fields.Datetime.now()
        self.env.cr.execute(
            SQL(
                """
                SELECT id
                  FROM picking_assistant_idempotency
                 WHERE endpoint = %(endpoint)s
                   AND principal_scope = %(scope)s
                   AND key = %(key)s
                 FOR UPDATE
                """,
                endpoint=endpoint,
                scope=principal_scope,
                key=key,
            )
        )
        row = self.env.cr.fetchone()
        existing = self.sudo().browse(row[0]) if row else self.browse()
        values = {
            "endpoint": endpoint,
            "principal_scope": principal_scope,
            "key": key,
            "request_fingerprint": request_fingerprint,
            "picking_id": int(picking_id) if picking_id else False,
            "picker_user_id": int(picker_user_id) if picker_user_id else False,
            "device_id": device_id or False,
            "expires_at": now + timedelta(seconds=int(ttl_seconds)),
            "state": "pending",
            "response_payload": False,
            "processed_at": False,
        }
        if existing and existing.expires_at <= now:
            existing.write(values)
            return {"status": "reserved", "entry_id": existing.id, "status_code": 200}
        if existing:
            if existing.request_fingerprint != request_fingerprint:
                return {
                    "status": "conflict",
                    "entry_id": existing.id,
                    "status_code": 409,
                    "response_payload": {
                        "detail": "Idempotency-Key conflicts with another request."
                    },
                }
            if existing.state == "completed":
                replay = existing._payload()
                replay["status"] = "replay"
                return replay
            return {
                "status": "pending",
                "entry_id": existing.id,
                "status_code": 409,
                "response_payload": {"detail": "Request is already processing."},
            }
        try:
            with self.env.cr.savepoint():
                created = self.sudo().create(values)
        except IntegrityError:
            return self.api_reserve_request(
                endpoint,
                key,
                request_fingerprint,
                principal_scope,
                picking_id,
                picker_user_id,
                device_id,
                ttl_seconds,
            )
        return {"status": "reserved", "entry_id": created.id, "status_code": 200}

    @api.model
    def api_finalize_request(
        self, entry_id, principal_scope, response_payload, status_code=200
    ):
        self._require_api()
        entry = self.sudo().browse(int(entry_id)).exists()
        if not entry or entry.principal_scope != principal_scope:
            raise ValidationError("Idempotency reservation scope mismatch.")
        entry.write(
            {
                "response_payload": json.dumps(
                    response_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "status_code": int(status_code),
                "state": "completed",
                "processed_at": fields.Datetime.now(),
            }
        )
        return True

    @api.model
    def api_abort_request(self, entry_id, principal_scope):
        self._require_api()
        entry = self.sudo().browse(int(entry_id)).exists()
        if not entry or entry.principal_scope != principal_scope:
            raise ValidationError("Idempotency reservation scope mismatch.")
        entry.unlink()
        return True

    @api.model
    def _cron_cleanup_expired(self, limit=1000):
        records = self.sudo().search(
            [("expires_at", "<=", fields.Datetime.now())], limit=int(limit)
        )
        processed = len(records)
        records.unlink()
        remaining = self.sudo().search_count(
            [("expires_at", "<=", fields.Datetime.now())]
        )
        self.env["ir.cron"]._commit_progress(processed, remaining=remaining)
        return processed
```

The hourly cron invokes `_cron_cleanup_expired(limit=1000)`. Every existing public `api_*` method in `StockPicking` calls `_require_api_service()` before browsing, `sudo()`, or writing. API Service receives read-only idempotency ACL; only System has raw CRUD.

Pass the scope in all backend calls:

```python
result = await self._odoo.execute_kw(
    "picking.assistant.idempotency",
    "api_reserve_request",
    [
        endpoint,
        context.idempotency_key,
        fingerprint,
        context.principal_scope,
        picking_id or False,
        context.identity.user_id or False,
        context.identity.device_id or False,
        settings.mobile_idempotency_ttl_seconds,
    ],
)
```

`finalize_idempotent_request()` and `abort_idempotent_request()` pass the same immutable `context.principal_scope`; therefore add `principal_scope` to `IdempotencyReservation` when it is created. No request body or header may supply this scope.

- [ ] **Step 4: Run migration, Odoo tests, and backend workflow tests**

Run:

```bash
docker compose --profile odoo19-trial run --rm --no-deps odoo19-trial \
  --database masterfischer_o19_foundation_test \
  --db-filter '^masterfischer_o19_foundation_test$' \
  --workers=0 --max-cron-threads=0 --without-demo=all \
  --update picking_assistant_integration,picking_assistant_core \
  --test-tags '/picking_assistant_integration,/picking_assistant_core' \
  --stop-after-init

cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_mobile_workflow_service.py \
  tests/test_mobile_routes.py \
  tests/test_n8n_internal_routes.py \
  -q
```

Expected: Odoo migration/update and both module tags report zero failures;
browser reservations retain their authenticated `user:*` scope and all five legacy
n8n handlers still pass `service:n8n-v1`.

- [ ] **Step 5: Commit the post-handoff Core migration**

```bash
git add \
  odoo/addons/picking_assistant_core \
  backend/app/services/mobile_workflow.py \
  backend/tests/test_mobile_workflow_service.py
git commit -m "fix(odoo): scope idempotency by authenticated principal"
```

### Task 13: Dedicated PostgreSQL Roles and Existing-Volume Migration

**Handoff gate:** This task runs after the Odoo-19 merge has established the production Odoo database name and before n8n, session, or dispatcher activation.

**Files:**
- Create: `infrastructure/scripts/init-db-roles.sh`
- Create: `infrastructure/scripts/clone-postgres-volume.sh`
- Create: `infrastructure/scripts/migrate-n8n-db-role.sh`
- Create: `infrastructure/scripts/verify-db-role-isolation.sh`
- Create: `infrastructure/docker-compose.db-migration.yml`
- Create: `infrastructure/tests/test_db_role_scripts.py`
- Create: `docs/runbooks/n8n-db-role-migration.md`
- Modify: `infrastructure/scripts/init-n8n-db.sql`
- Modify later in Task 15: `docker-compose.yml` and `.env.example`

**Interfaces:**
- Consumes: final Odoo-19 database name and a stopped n8n service.
- Produces: bootstrap role `pwr_db_admin`, app roles `odoo_app` and `n8n_app`,
  fresh-volume initialization, offline volume clone modes `create`, `verify`,
  `delete`, and migration modes `backup`, `apply`, `verify`, `rollback`.

- [ ] **Step 1: Write failing script-contract tests**

```python
# infrastructure/tests/test_db_role_scripts.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_fresh_init_creates_separate_non_superuser_app_roles():
    script = text("infrastructure/scripts/init-db-roles.sh")
    assert "pwr_db_admin" in script
    assert "odoo_app" in script
    assert "n8n_app" in script
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE" in script
    assert "REVOKE CONNECT" in script


def test_existing_volume_migration_has_all_reversible_modes():
    script = text("infrastructure/scripts/migrate-n8n-db-role.sh")
    for mode in ("backup", "apply", "verify", "rollback"):
        assert f'"{mode}")' in script
    assert "pg_dump --format=custom" in script
    assert "pg_dumpall --roles-only" in script
    assert "REASSIGN OWNED" in script
    assert "NOLOGIN" in script


def test_isolation_probe_contains_positive_and_negative_checks():
    script = text("infrastructure/scripts/verify-db-role-isolation.sh")
    assert "rolsuper" in script
    assert "n8n_app" in script and "odoo_app" in script
    assert "expected connection failure" in script


def test_volume_clone_is_offline_verified_and_deletable():
    script = text("infrastructure/scripts/clone-postgres-volume.sh")
    for mode in ("create", "verify", "delete"):
        assert f'"{mode}")' in script
    assert "docker volume inspect" in script
    assert "running container still mounts source volume" in script
    assert "manifest.sha256" in script
    override = text("infrastructure/docker-compose.db-migration.yml")
    assert "PWR_DB_MIGRATION_VOLUME" in override
    assert "/var/lib/postgresql/data" in override


def test_no_app_uses_cluster_bootstrap_role_in_compose():
    compose = text("docker-compose.yml")
    assert "DB_POSTGRESDB_USER: ${N8N_DB_USER:-n8n_app}" in compose
    assert "USER: ${ODOO_DB_USER:-odoo_app}" in compose
```

The final test remains red until Task 15 updates Compose; during Task 13 run the first three node IDs explicitly.

- [ ] **Step 2: Confirm current shared-superuser state and red tests**

Run:

```bash
PYTHONPATH=. python3 -m pytest \
  infrastructure/tests/test_db_role_scripts.py::test_fresh_init_creates_separate_non_superuser_app_roles \
  infrastructure/tests/test_db_role_scripts.py::test_existing_volume_migration_has_all_reversible_modes \
  infrastructure/tests/test_db_role_scripts.py::test_isolation_probe_contains_positive_and_negative_checks \
  infrastructure/tests/test_db_role_scripts.py::test_volume_clone_is_offline_verified_and_deletable \
  -q

docker compose exec -T db psql -U "${POSTGRES_USER:-odoo}" -d postgres \
  -Atc "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolcanlogin FROM pg_roles WHERE rolname='${POSTGRES_USER:-odoo}'"
```

Expected before implementation: tests fail because scripts are absent; the SQL probe reports the current `odoo` role as a superuser. Save the probe output in the program status without its password.

- [ ] **Step 3: Add fresh bootstrap, reversible migration, and isolation probe**

`clone-postgres-volume.sh` accepts `create SOURCE_VOLUME COPY_VOLUME
MANIFEST_DIR`, `verify SOURCE_VOLUME COPY_VOLUME MANIFEST_DIR`, or
`delete COPY_VOLUME MANIFEST_DIR`. It:

1. resolves both names with `docker volume inspect` and refuses identical names;
2. refuses `create` while any running container mounts the source volume;
3. creates the destination only when absent and empty;
4. copies offline through
   `docker run --rm --network none -v "$source:/source:ro" -v "$copy:/copy" alpine:3.20`
   using `tar`;
5. writes sorted relative-path SHA-256 manifests for both volumes, excluding
   `postmaster.pid`, and requires byte-identical manifests plus matching
   `PG_VERSION`;
6. writes source/copy volume IDs and creation UTC to a mode-`0600` manifest in a
   mode-`0700` directory;
7. makes `verify` recompute both manifests; and
8. makes `delete` refuse the source ID, remove only the recorded copy volume, and
   remove its manifest directory.

Create this fixed Compose override:

```yaml
# infrastructure/docker-compose.db-migration.yml
services:
  db:
    volumes:
      - pwr_migration_data:/var/lib/postgresql/data

volumes:
  pwr_migration_data:
    external: true
    name: ${PWR_DB_MIGRATION_VOLUME:?PWR_DB_MIGRATION_VOLUME is required}
```

The migration run uses an isolated `COMPOSE_PROJECT_NAME` and this override, so no
container can mount the live source volume accidentally.

`init-db-roles.sh` reads passwords from `PWR_DB_ADMIN_PASSWORD_FILE`, `ODOO_DB_PASSWORD_FILE`, and `N8N_DB_PASSWORD_FILE`, requires all files mode `0400` or `0600`, and never echoes their content. It runs only in PostgreSQL's fresh-volume init directory.

Its SQL behavior is exactly:

```sql
-- Executed as the image-created pwr_db_admin bootstrap superuser.
SELECT format(
  'CREATE ROLE odoo_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
  :'odoo_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'odoo_app')
\gexec

SELECT format(
  'CREATE ROLE n8n_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
  :'n8n_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'n8n_app')
\gexec

SELECT format('CREATE DATABASE %I OWNER odoo_app', :'odoo_db')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'odoo_db')
\gexec

SELECT 'CREATE DATABASE n8n OWNER n8n_app'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'n8n')
\gexec

REVOKE CONNECT, TEMPORARY ON DATABASE n8n FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE n8n TO n8n_app;
```

For the Odoo database, generate the `REVOKE CONNECT, TEMPORARY ... FROM PUBLIC` and `GRANT ... TO odoo_app` statements with `format('%I', :'odoo_db') \gexec`. In each database:

```sql
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO n8n_app;
ALTER SCHEMA public OWNER TO n8n_app;
ALTER DEFAULT PRIVILEGES FOR ROLE n8n_app GRANT ALL ON TABLES TO n8n_app;
ALTER DEFAULT PRIVILEGES FOR ROLE n8n_app GRANT ALL ON SEQUENCES TO n8n_app;
```

Run the same statements in the Odoo database with its concrete application role:

```sql
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO odoo_app;
ALTER SCHEMA public OWNER TO odoo_app;
ALTER DEFAULT PRIVILEGES FOR ROLE odoo_app GRANT ALL ON TABLES TO odoo_app;
ALTER DEFAULT PRIVILEGES FOR ROLE odoo_app GRANT ALL ON SEQUENCES TO odoo_app;
```

Replace `init-n8n-db.sql` with idempotent schema/grant statements that assume `n8n_app` already exists; database and role creation stays in the shell bootstrap because passwords cannot be committed into SQL.

`migrate-n8n-db-role.sh` accepts:

```text
backup "$BACKUP_DIR"
apply "$BACKUP_DIR"
verify
rollback "$BACKUP_DIR"
```

It uses `umask 077`, refuses a world-readable backup directory, and implements:

**backup**

```bash
pg_dumpall --roles-only > "$backup_dir/roles-before.sql"
pg_dump --format=custom --file "$backup_dir/n8n-before.dump" n8n
psql -X -At -d postgres -c \
  "SELECT datname, datacl FROM pg_database ORDER BY datname" \
  > "$backup_dir/database-acl-before.tsv"
psql -X -At -d n8n -c \
  "SELECT nspname, nspacl FROM pg_namespace ORDER BY nspname" \
  > "$backup_dir/n8n-schema-acl-before.tsv"
```

It writes `manifest.sha256` over all four files and records the old role flags.

**apply**

1. verify `manifest.sha256`;
2. require n8n stopped: `docker compose stop n8n`;
3. create `pwr_db_admin`, `odoo_app`, `n8n_app` if absent using password files;
4. in `n8n`, run `REASSIGN OWNED BY odoo TO n8n_app`, alter database/schema ownership, tables, sequences, and default privileges;
5. in the Odoo-19 DB, reassign application objects from `odoo` to `odoo_app`;
6. require the resolved Compose config to contain `odoo_app` and `n8n_app`, then
   start Odoo and n8n with the supplied role secret files;
7. invoke the isolation verifier;
8. only after every positive/negative check passes, run:

```sql
ALTER ROLE odoo NOSUPERUSER NOCREATEDB NOCREATEROLE NOLOGIN;
```

If the existing role has a different name, the script requires `LEGACY_DB_SUPERUSER` and refuses `postgres` or `pwr_db_admin`.

**rollback**

1. stop n8n and Odoo;
2. re-enable the legacy role using the flags saved by `backup`;
3. restore n8n from `n8n-before.dump` into a clean `n8n` database owned by the legacy role;
4. restore database/schema grants from the ACL report through generated, reviewed SQL;
5. start services with the recorded legacy-role override;
6. run their pre-migration health probes.

The rollback does not drop `pwr_db_admin`, `odoo_app`, or `n8n_app`; it removes their application grants after the old services are healthy, preserving an auditable recovery path.

The verifier executes all six checks:

```text
1. pwr_db_admin: rolsuper=true, application services do not use it.
2. odoo_app: rolsuper=false, rolcreatedb=false, rolcreaterole=false.
3. n8n_app: rolsuper=false, rolcreatedb=false, rolcreaterole=false.
4. n8n_app can connect/create/rollback a temporary table in n8n.
5. n8n_app connection to the Odoo database fails with expected connection failure.
6. odoo_app can connect/read its schema; connection to n8n fails with expected connection failure.
```

Use `PGCONNECT_TIMEOUT=3`. A negative check that unexpectedly connects is a hard failure. The script redacts connection URIs and never invokes `set -x`.

Document an operator sequence in `docs/runbooks/n8n-db-role-migration.md`:

```bash
BACKUP_DIR="n8n/backups/db-role-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP_DIR"
bash infrastructure/scripts/migrate-n8n-db-role.sh backup "$BACKUP_DIR"
bash infrastructure/scripts/migrate-n8n-db-role.sh apply "$BACKUP_DIR"
bash infrastructure/scripts/migrate-n8n-db-role.sh verify
# On failure:
bash infrastructure/scripts/migrate-n8n-db-role.sh rollback "$BACKUP_DIR"
```

Include prerequisites, expected output for each phase, stop/start impact, backup retention, exact rollback decision point, and the rule that legacy-superuser demotion requires a second operator review.

- [ ] **Step 4: Run static checks; defer the real copy gate to Task 15**

Run:

```bash
bash -n infrastructure/scripts/init-db-roles.sh
bash -n infrastructure/scripts/clone-postgres-volume.sh
bash -n infrastructure/scripts/migrate-n8n-db-role.sh
bash -n infrastructure/scripts/verify-db-role-isolation.sh
PYTHONPATH=. python3 -m pytest \
  infrastructure/tests/test_db_role_scripts.py::test_fresh_init_creates_separate_non_superuser_app_roles \
  infrastructure/tests/test_db_role_scripts.py::test_existing_volume_migration_has_all_reversible_modes \
  infrastructure/tests/test_db_role_scripts.py::test_isolation_probe_contains_positive_and_negative_checks \
  infrastructure/tests/test_db_role_scripts.py::test_volume_clone_is_offline_verified_and_deletable \
  -q
```

Expected: syntax and four focused tests pass. Do not claim a live migration yet:
Task 15 first wires the final application roles into Compose, then runs
clone/apply/isolation/rollback against the verified disposable volume. Never run
`apply` against the real volume in a feature worktree.

- [ ] **Step 5: Commit database role migration tooling**

```bash
git add \
  infrastructure/docker-compose.db-migration.yml \
  infrastructure/scripts/clone-postgres-volume.sh \
  infrastructure/scripts/init-db-roles.sh \
  infrastructure/scripts/init-n8n-db.sql \
  infrastructure/scripts/migrate-n8n-db-role.sh \
  infrastructure/scripts/verify-db-role-isolation.sh \
  infrastructure/tests/test_db_role_scripts.py \
  docs/runbooks/n8n-db-role-migration.md
git commit -m "feat(database): isolate Odoo and n8n application roles"
```

### Task 14: n8n Credential Bootstrap, Registry Importer, and Verifier

**Files:**
- Create: `n8n/scripts/provision-credentials.mjs`
- Create: `n8n/tests/provision-credentials.test.mjs`
- Create: `infrastructure/scripts/provision-n8n-credentials.sh`
- Create: `infrastructure/scripts/stage_workflow.py`
- Create: `infrastructure/scripts/workflow_verifier.py`
- Create: `infrastructure/tests/test_stage_workflow.py`
- Create: `infrastructure/tests/test_import_workflows.py`
- Create: `infrastructure/tests/test_verify_workflows_v2.py`
- Modify: `infrastructure/scripts/import-workflows.sh`
- Modify: `infrastructure/scripts/verify-workflows.py`
- Modify: `n8n/workflow-registry.json` when the smoke workflow lands in Task 15

**Interfaces:**
- Consumes: logical credential bindings from Task 3 and custom credential types from Task 4.
- Produces: credential modes `provision`, `verify`, `rotate`; `indexCredentials`, `resolveCredentialId`, `buildDefinitions`; `stage_workflow(...)`; `verify_v2_workflow(workflow, spec) -> list[str]`; registry-only backup/import/activation.

- [ ] **Step 1: Write failing credential, staging, and v2 verifier tests**

```javascript
// n8n/tests/provision-credentials.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';

import {
    buildDefinitions,
    indexCredentials,
    resolveCredentialId,
} from '../scripts/provision-credentials.mjs';

test('indexes credentials by exact name and type and rejects duplicates', () => {
    const index = indexCredentials([
        {id: 'id-1', name: 'pwr.v2.inbound-header', type: 'httpHeaderAuth'},
    ]);
    assert.equal(
        index.get('pwr.v2.inbound-header\0httpHeaderAuth')[0].id,
        'id-1',
    );
    assert.throws(
        () => resolveCredentialId(
            'pwr.v2.inbound-header',
            'httpHeaderAuth',
            new Map([[
                'pwr.v2.inbound-header\0httpHeaderAuth',
                [{id: 'a'}, {id: 'b'}],
            ]]),
        ),
        /duplicate/,
    );
});

test('preserves existing id and builds the three exact logical credentials', () => {
    const existing = new Map([[
        'pwr.v2.inbound-header\0httpHeaderAuth',
        [{id: 'stable-id'}],
    ]]);
    assert.equal(
        resolveCredentialId(
            'pwr.v2.inbound-header', 'httpHeaderAuth', existing,
        ),
        'stable-id',
    );
    const definitions = buildDefinitions({
        ids: {
            inboundHeader: 'stable-id',
            inboundHmac: 'hmac-in',
            outboundHmac: 'hmac-out',
        },
        nativeHeaderSecret: 'native-secret',
        backendToN8n: {
            activeKeyId: 'b2n-active',
            activeSecretBase64: 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=',
            previousKeyId: '',
            previousSecretBase64: '',
        },
        n8nToBackend: {
            baseUrl: 'http://backend:8000',
            activeKeyId: 'n2b-active',
            activeSecretBase64: 'MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=',
            legacyCallbackSecret: 'legacy-secret',
        },
    });
    assert.deepEqual(
        definitions.map(item => [item.name, item.type]),
        [
            ['pwr.v2.inbound-header', 'httpHeaderAuth'],
            ['pwr.v2.backend-to-n8n-hmac', 'pwrInboundHmac'],
            ['pwr.v2.n8n-to-backend-hmac', 'pwrOutboundHmac'],
        ],
    );
});
```

```python
# infrastructure/tests/test_stage_workflow.py
import json

import pytest

from infrastructure.scripts.stage_workflow import stage_workflow


def test_injects_ids_only_into_staged_copy(tmp_path):
    source = {
        "name": "PWR Smoke",
        "nodes": [
            {"name": "Webhook", "type": "n8n-nodes-base.webhook", "credentials": {}},
            {"name": "Signature Gate", "type": "n8n-nodes-pwr.pwrSignatureGate"},
        ],
        "active": True,
    }
    bindings = [
        {
            "node": "Webhook",
            "credential_type": "httpHeaderAuth",
            "logical_name": "pwr.v2.inbound-header",
        }
    ]
    staged = stage_workflow(
        source,
        bindings=bindings,
        credential_index={
            ("pwr.v2.inbound-header", "httpHeaderAuth"): {
                "id": "credential-id",
                "name": "pwr.v2.inbound-header",
                "type": "httpHeaderAuth",
            }
        },
        existing_workflow_id="workflow-id",
        error_workflow_id=None,
    )
    assert staged["active"] is False
    assert staged["id"] == "workflow-id"
    assert staged["nodes"][0]["credentials"]["httpHeaderAuth"] == {
        "id": "credential-id",
        "name": "pwr.v2.inbound-header",
    }
    assert source["active"] is True
    assert source["nodes"][0]["credentials"] == {}


def test_missing_or_duplicate_credential_fails_closed():
    with pytest.raises(ValueError, match="exactly one credential"):
        stage_workflow(
            {"name": "x", "nodes": [{"name": "Webhook"}]},
            bindings=[{
                "node": "Webhook",
                "credential_type": "httpHeaderAuth",
                "logical_name": "pwr.v2.inbound-header",
            }],
            credential_index={},
            existing_workflow_id=None,
            error_workflow_id=None,
        )
```

```python
# infrastructure/tests/test_verify_workflows_v2.py
from copy import deepcopy

import pytest

from infrastructure.scripts.workflow_verifier import verify_v2_workflow

SPEC = {
    "file": "fixture.json",
    "generation": "v2",
    "webhook_paths": ["fixture-v2"],
    "callback_paths": ["/api/internal/n8n/v2/callbacks/status"],
    "allowed_target_hosts": ["backend"],
    "authentication": "native_header_hmac",
}


@pytest.fixture
def v2_fixture():
    return {
        "name": "Fixture v2",
        "active": False,
        "nodes": [
            {
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "parameters": {
                    "path": "fixture-v2",
                    "authentication": "headerAuth",
                    "options": {"rawBody": True},
                },
            },
            {
                "name": "PWR Signature Gate",
                "type": "CUSTOM.pwrSignatureGate",
                "parameters": {},
            },
            {
                "name": "Acceptance",
                "type": "CUSTOM.pwrSignedHttpRequest",
                "parameters": {
                    "target": "/api/internal/n8n/v2/events/accept",
                    "host": "backend",
                },
            },
        ],
        "connections": {
            "Webhook": {
                "main": [[{
                    "node": "PWR Signature Gate", "type": "main", "index": 0
                }]]
            },
            "PWR Signature Gate": {
                "main": [[{"node": "Acceptance", "type": "main", "index": 0}], []]
            },
        },
    }


@pytest.fixture
def verify():
    return lambda workflow: verify_v2_workflow(deepcopy(workflow), SPEC)


def test_v2_rejects_unauthenticated_webhook(v2_fixture, verify):
    v2_fixture["nodes"][0]["parameters"]["authentication"] = "none"
    errors = verify(v2_fixture)
    assert any("headerAuth" in error for error in errors)


def test_v2_rejects_business_node_before_gate(v2_fixture, verify):
    v2_fixture["connections"] = {
        "Webhook": {"main": [[{"node": "Model Call", "type": "main", "index": 0}]]},
    }
    errors = verify(v2_fixture)
    assert any("Signature Gate must be first" in error for error in errors)


def test_v2_rejects_normal_http_node_for_internal_callback(v2_fixture, verify):
    v2_fixture["nodes"].append({
        "name": "Unsafe Callback",
        "type": "n8n-nodes-base.httpRequest",
        "parameters": {
            "url": "http://backend:8000/api/internal/n8n/v2/callbacks/status"
        },
    })
    errors = verify(v2_fixture)
    assert any("PWR Signed HTTP Request" in error for error in errors)
```

- [ ] **Step 2: Run all three focused suites**

Run:

```bash
node --test n8n/tests/provision-credentials.test.mjs
PYTHONPATH=. python3 -m pytest \
  infrastructure/tests/test_import_workflows.py \
  infrastructure/tests/test_stage_workflow.py \
  infrastructure/tests/test_verify_workflows_v2.py \
  -q
```

Expected: modules/functions/fixtures are absent, so both commands fail.

- [ ] **Step 3: Provision internally and make the registry the sole rollout source**

The Node module exports these pure functions before its CLI entry point:

```javascript
// n8n/scripts/provision-credentials.mjs
import {randomUUID} from 'node:crypto';
import {chmod, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';

const key = (name, type) => `${name}\0${type}`;

export function indexCredentials(credentials) {
    const index = new Map();
    for (const credential of credentials) {
        const itemKey = key(credential.name, credential.type);
        index.set(itemKey, [...(index.get(itemKey) || []), credential]);
    }
    return index;
}

export function resolveCredentialId(name, type, existing) {
    const matches = existing.get(key(name, type)) || [];
    if (matches.length > 1) {
        throw new Error(`duplicate credential: ${name} (${type})`);
    }
    return matches[0]?.id || randomUUID();
}

export function buildDefinitions(config) {
    return [
        {
            id: config.ids.inboundHeader,
            name: 'pwr.v2.inbound-header',
            type: 'httpHeaderAuth',
            data: {
                name: 'X-PWR-Webhook-Secret',
                value: config.nativeHeaderSecret,
            },
        },
        {
            id: config.ids.inboundHmac,
            name: 'pwr.v2.backend-to-n8n-hmac',
            type: 'pwrInboundHmac',
            data: config.backendToN8n,
        },
        {
            id: config.ids.outboundHmac,
            name: 'pwr.v2.n8n-to-backend-hmac',
            type: 'pwrOutboundHmac',
            data: config.n8nToBackend,
        },
    ];
}
```

The CLI:

1. accepts only `provision`, `verify`, or `rotate`;
2. creates a `0700` temporary directory and `0600` JSON files;
3. sets `CREDENTIAL_EXPORT_PATH="$TMP_DIR/credentials-export.json"` and calls
   `n8n export:credentials --all --output="$CREDENTIAL_EXPORT_PATH"` without
   `--decrypted`;
4. reads only `id`, `name`, and `type` from the export;
5. reads secret bytes from these files:

```text
/run/secrets/pwr_n8n_native_header
/run/secrets/pwr_backend_to_n8n_active_hmac
/run/secrets/pwr_backend_to_n8n_previous_hmac
/run/secrets/pwr_n8n_to_backend_active_hmac
/run/secrets/pwr_n8n_callback_legacy
```

6. reads nonsecret IDs from `PWR_BACKEND_TO_N8N_ACTIVE_KEY_ID`, optional previous ID, and `PWR_N8N_TO_BACKEND_ACTIVE_KEY_ID`;
7. validates each HMAC secret as base64 decoding to at least 32 bytes;
8. in `verify`, requires exactly one `(name,type)` match for all three and writes a metadata-only index;
9. in `provision`, preserves an existing ID or generates one, writes definitions to
   `CREDENTIAL_IMPORT_PATH="$TMP_DIR/credentials-import.json"` with mode `0600`,
   invokes `n8n import:credentials --input="$CREDENTIAL_IMPORT_PATH"`, re-exports,
   and verifies;
10. in `rotate`, requires both new active and previous key/secret, provisions active plus previous, and never removes previous until the live signature smoke has passed;
11. removes the directory in `finally`, even when CLI import fails.

Its only stdout is a metadata object:

```json
{
  "credentials": [
    {"id": "opaque", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"},
    {"id": "opaque", "name": "pwr.v2.backend-to-n8n-hmac", "type": "pwrInboundHmac"},
    {"id": "opaque", "name": "pwr.v2.n8n-to-backend-hmac", "type": "pwrOutboundHmac"}
  ]
}
```

The shell wrapper checks secret file ownership/mode, runs the module inside the n8n container, writes stdout to its own `0600` temporary metadata file, and never enables `set -x`.

Implement the staging helper:

```python
# infrastructure/scripts/stage_workflow.py
from copy import deepcopy
from uuid import uuid4


def stage_workflow(
    source: dict,
    *,
    bindings: list[dict],
    credential_index: dict[tuple[str, str], dict],
    existing_workflow_id: str | None,
    error_workflow_id: str | None,
) -> dict:
    staged = deepcopy(source)
    staged["id"] = existing_workflow_id or staged.get("id") or uuid4().hex
    staged["active"] = False
    by_name = {node.get("name"): node for node in staged.get("nodes") or []}
    for binding in bindings:
        node = by_name.get(binding["node"])
        if node is None:
            raise ValueError(f"credential node not found: {binding['node']}")
        lookup = (
            binding["logical_name"],
            binding["credential_type"],
        )
        credential = credential_index.get(lookup)
        if not credential:
            raise ValueError(
                f"expected exactly one credential for {binding['logical_name']}"
            )
        node.setdefault("credentials", {})[binding["credential_type"]] = {
            "id": credential["id"],
            "name": credential["name"],
        }
    if error_workflow_id:
        staged.setdefault("settings", {})["errorWorkflow"] = error_workflow_id
    return staged
```

Refactor `import-workflows.sh` so:

- `WORKFLOW_FILES`, `ACTIVATION_ORDER`, workflow names, and credential bindings come only from `workflow_registry.py`;
- `backup` exports every `managed=true` workflow;
- `import` first runs verifier and credential `verify`, stages every file into `TMP_ROOT`, injects only metadata IDs, imports inactive, and deletes `TMP_ROOT` through its existing trap;
- `activate` refuses `production_activation=false`, absent credentials, duplicates, or an unverified workflow;
- `activate-test FILE RUN_ID` accepts exactly one registry entry returned by
  `test-only-files`, requires a nonempty operator-generated `RUN_ID`, refuses every
  `production_activation=true` workflow, activates no dependency workflow, and
  writes a `0600` restoration manifest;
- `deactivate-test FILE RUN_ID` requires that same manifest and restores the prior
  active state; a missing/mismatched run ID is a hard failure;
- rollback uses the backup manifest rather than a second file list;
- no workflow ID or credential ID is committed to source JSON.

Move verification logic into importable `workflow_verifier.py`. Keep
`verify-workflows.py` as the thin CLI wrapper that loads the registry and calls its
`verify_v2_workflow(workflow, spec)` pure function, which enforces for every v2
workflow:

1. Webhook authentication equals `headerAuth`;
2. `options.rawBody` is `true`;
3. output 0 of `PWR Signature Gate` is the first business edge from Webhook;
4. rejection output reaches only `Respond to Webhook`;
5. no model, carrier, Odoo, callback, or external node is reachable before acceptance returns `process=true`;
6. v2 internal requests use only `pwrSignedHttpRequest`;
7. event and callback nodes reference `event_id`, `odoo_instance`, delivery generation, lease, and idempotency fields;
8. targets are relative registered paths, concrete targets must match registered
   `{field}` templates segment by segment after expression resolution, and the
   resolved host is in `allowed_target_hosts`;
9. direct Odoo URLs and unknown backend internal paths fail;
10. a Quality workflow cannot claim image analysis from only `photo_count`;
11. `bodyMode=literalUtf8` is accepted only for a `test_only=true` registry entry,
    and Code/Edit Fields nodes may not place artifact or base64 content in item
    JSON.

Known registry-marked v1 workflows remain valid during migration, but a new file cannot opt itself into `legacy_v1`: the verifier compares the file list to the reviewed registry.

Add importer tests proving normal `activate` rejects the Foundation smoke,
`activate-test` rejects every non-`test_only` workflow, and the matching
activate/deactivate pair restores the exact previous active state. Both live smoke
scripts create `RUN_ID="$(uuidgen)"`, register a trap that calls
`deactivate-test`, and fail if cleanup cannot restore the workflow.
Add verifier fixtures for one registered artifact-path template, a mismatching
resolved segment, and literal body mode under both test-only and production specs.

- [ ] **Step 4: Run provisioning units, registry verification, and importer dry run**

Run:

```bash
node --test n8n/tests/provision-credentials.test.mjs
PYTHONPATH=. python3 -m pytest \
  infrastructure/tests/test_workflow_registry.py \
  infrastructure/tests/test_stage_workflow.py \
  infrastructure/tests/test_verify_workflows_v2.py \
  -q
python3 infrastructure/scripts/verify-workflows.py
bash -n infrastructure/scripts/import-workflows.sh
bash -n infrastructure/scripts/provision-n8n-credentials.sh
```

Expected: all tests pass; current registered v1 workflows verify; both shell scripts pass syntax checks.

- [ ] **Step 5: Commit secure credential and rollout tooling**

```bash
git add \
  n8n/scripts/provision-credentials.mjs \
  n8n/tests/provision-credentials.test.mjs \
  infrastructure/scripts/import-workflows.sh \
  infrastructure/scripts/provision-n8n-credentials.sh \
  infrastructure/scripts/stage_workflow.py \
  infrastructure/scripts/verify-workflows.py \
  infrastructure/scripts/workflow_verifier.py \
  infrastructure/tests/test_import_workflows.py \
  infrastructure/tests/test_stage_workflow.py \
  infrastructure/tests/test_verify_workflows_v2.py
git commit -m "feat(n8n): provision credentials and verify registry rollout"
```

### Task 15: Custom n8n Image, Network Boundaries, Caddy, and TLS Gates

**Handoff gate:** Start Compose edits only after `wave1-odoo19-handoff`. Rebase first and preserve the Odoo-19 service/image/mount facts delivered by that branch.

**Files:**
- Create: `n8n/Dockerfile`
- Create: `n8n/workflows/pwr-foundation-smoke-v2.json`
- Create: `docker-compose.dev.yml`
- Create: `infrastructure/scripts/test-pwr-n8n-signing.sh`
- Create: `infrastructure/scripts/test-db-role-migration-copy.sh`
- Create: `infrastructure/scripts/check-certificate-expiry.sh`
- Create: `infrastructure/scripts/verify-production-gates.sh`
- Create: `infrastructure/tests/test_production_surface.py`
- Modify: `n8n/workflow-registry.json`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `backend/app/config.py` and `backend/app/dependencies.py` for Docker secret files
- Modify: `infrastructure/caddy/Caddyfile`
- Modify: `infrastructure/scripts/setup-certs.sh`
- Modify: `infrastructure/certs/README.md`
- Modify: `docs/SETUP.md`

**Interfaces:**
- Consumes: custom node build Task 4, registry/importer Task 14, DB roles Task 13, final Odoo-19 Compose service.
- Produces: n8n custom image, three-network production topology, localhost-only
  development ports, no public n8n/Odoo routes, verified disposable DB-role
  migration, SAN/expiry tooling, and live signing smoke.

- [ ] **Step 1: Write failing production-surface tests**

```python
# infrastructure/tests/test_production_surface.py
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def service_block(compose, service):
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  [a-zA-Z0-9_-]+:\n|^volumes:|^networks:)",
        compose,
    )
    assert match, service
    return match.group(1)


def test_production_publishes_only_caddy_ports():
    compose = read("docker-compose.yml")
    assert '"443:443"' in service_block(compose, "caddy")
    assert '"80:80"' in service_block(compose, "caddy")
    for service in ("backend", "db", "odoo", "n8n", "whisper", "piper", "ollama"):
        assert "\n    ports:" not in service_block(compose, service)


def test_dev_admin_ports_bind_only_loopback():
    override = read("docker-compose.dev.yml")
    for binding in (
        "127.0.0.1:${BACKEND_HOST_PORT:-8000}:8000",
        "127.0.0.1:${POSTGRES_HOST_PORT:-5433}:5432",
        "127.0.0.1:${ODOO_HOST_PORT:-8069}:8069",
        "127.0.0.1:${N8N_HOST_PORT:-5678}:5678",
    ):
        assert binding in override
    assert re.search(r'(?m)^\s*-\s*"(?!127\.0\.0\.1:)[0-9]+:[0-9]+"', override) is None


def test_caddy_blocks_internal_before_public_api_and_has_no_admin_proxy():
    caddy = read("infrastructure/caddy/Caddyfile")
    blocked = caddy.index("@blocked")
    public_api = caddy.index("@public_api")
    assert blocked < public_api
    for forbidden in ("reverse_proxy n8n:", "localhost:8069", "@n8n_host", "/nn"):
        assert forbidden not in caddy
    for path in (
        "/api/internal/*",
        "/api/obsidian/*",
        "/api/demo/*",
        "/api/docs*",
        "/api/redoc*",
        "/api/openapi.json",
    ):
        assert path in caddy


def test_n8n_is_private_and_code_nodes_cannot_read_environment():
    compose = read("docker-compose.yml")
    block = service_block(compose, "n8n")
    assert "N8N_BLOCK_ENV_ACCESS_IN_NODE: \"true\"" in block
    assert "N8N_PUBLIC_API_DISABLED: \"true\"" in block
    assert "N8N_PUBLIC_API_SWAGGERUI_DISABLED: \"true\"" in block
    assert "NODE_FUNCTION_ALLOW_BUILTIN" not in block
    assert "automation-net" in block
    assert "edge-net" not in block


def test_database_apps_use_separate_roles():
    compose = read("docker-compose.yml")
    assert "DB_POSTGRESDB_USER: ${N8N_DB_USER:-n8n_app}" in compose
    assert "USER: ${ODOO_DB_USER:-odoo_app}" in compose


def test_backend_mounts_the_reviewed_workflow_registry_read_only():
    compose = read("docker-compose.yml")
    block = service_block(compose, "backend")
    assert (
        "./n8n/workflow-registry.json:/run/pwr/workflow-registry.json:ro"
        in block
    )
    assert "WORKFLOW_REGISTRY_PATH: /run/pwr/workflow-registry.json" in block
```

Add a registry test asserting `pwr-foundation-smoke-v2.json` is `generation=v2`,
`authentication=native_header_hmac`, `managed=true`,
`production_activation=false`, and `test_only=true`.

- [ ] **Step 2: Run production-surface and registry tests**

Run:

```bash
PYTHONPATH=. python3 -m pytest \
  infrastructure/tests/test_production_surface.py \
  infrastructure/tests/test_workflow_registry.py \
  -q
```

Expected: tests fail on current direct DB/Odoo/n8n ports, single network, public Caddy admin paths, and missing smoke workflow.

- [ ] **Step 3: Build the private image and production topology**

Use a custom extension path outside `/home/node/.n8n`, because the persistent `n8n_data` volume masks that home directory:

```dockerfile
# n8n/Dockerfile
FROM node:22.16-alpine AS builder
WORKDIR /build/n8n-nodes-pwr
COPY custom-nodes/n8n-nodes-pwr/package.json ./
COPY custom-nodes/n8n-nodes-pwr/package-lock.json ./
RUN npm ci
COPY custom-nodes/n8n-nodes-pwr/tsconfig.json ./
COPY custom-nodes/n8n-nodes-pwr/src ./src
RUN npm run build && npm prune --omit=dev

FROM docker.n8n.io/n8nio/n8n:2.13.3
USER root
RUN mkdir -p /opt/n8n-custom/n8n-nodes-pwr
COPY --from=builder --chown=node:node \
  /build/n8n-nodes-pwr/package.json \
  /opt/n8n-custom/n8n-nodes-pwr/package.json
COPY --from=builder --chown=node:node \
  /build/n8n-nodes-pwr/dist \
  /opt/n8n-custom/n8n-nodes-pwr/dist
COPY --from=builder --chown=node:node \
  /build/n8n-nodes-pwr/node_modules \
  /opt/n8n-custom/n8n-nodes-pwr/node_modules
ENV N8N_CUSTOM_EXTENSIONS=/opt/n8n-custom/n8n-nodes-pwr
USER node
```

The new smoke workflow has these exact nodes and edges:

```text
PWR Foundation Smoke v2
Webhook (POST quality-assessment-v2, headerAuth, rawBody=true)
  output 0 -> PWR Signature Gate
PWR Signature Gate
  output 0 -> Build Acceptance
  output 1 -> Reject Response
Build Acceptance
  -> PWR Signed Acceptance (POST /api/internal/n8n/v2/events/accept)
  -> Accepted Response
  -> If Process
If Process
  false -> Stop Duplicate
  true  -> Smoke Wait
Smoke Wait
  -> Build Running Callback
  -> PWR Signed Running Callback (POST /api/internal/n8n/v2/callbacks/status)
  -> If Artifact Probe
If Artifact Probe
  false -> Build Terminal Callback
  true  -> PWR Signed Artifact (POST /api/internal/instances/{instance}/jobs/{job}/events/{event}/artifacts/zpl)
PWR Signed Artifact
  -> Build Terminal Callback
  -> PWR Signed Terminal Callback (POST /api/internal/n8n/v2/callbacks/status)
```

`Build Acceptance` is an Edit Fields node that creates:

```json
{
  "schema_version": "v2",
  "event_id": "={{ $json.body.event_id }}",
  "job_id": "={{ $json.body.payload.job_id }}",
  "odoo_instance": "={{ $json.body.source.odoo_instance }}",
  "payload_fingerprint": "={{ $json.pwr.body_sha256 }}",
  "ingress_key_id": "={{ $json.pwr.key_id }}",
  "ingress_nonce": "={{ $json.pwr.nonce }}",
  "delivery_generation": "={{ $json.pwr.delivery_generation }}"
}
```

The Gate has immutable `expectedMethod=POST` and
`expectedTarget=/webhook/quality-assessment-v2`, matching Task 9's dispatcher
target. The signed acceptance node uses the event ID as `Idempotency-Key`, the body
generation, JSON body mode, and `pwr.v2.n8n-to-backend-hmac`. Rejection responds
with its `status_code` and only `reason_code`. `Accepted Response` responds
immediately, before the Wait, and passes its input through so the execution can
continue. It returns exactly:

```json
{"accepted": true, "event_id": "={{ $json.event_id }}"}
```

`If Process=false` ends without a callback. For `process=true`, `Smoke Wait` waits
the nonnegative `payload.test_delay_seconds` supplied only by the deterministic test
seed, capped at 60 seconds and defaulting to zero. The immutable test payload also
contains `callback_ids_by_generation` with distinct running/terminal UUIDs for
generations 1 and 2; the workflow fails closed if the signed generation has no
entry. `Build Running Callback` selects the IDs for the current signed generation
and constructs the frozen callback envelope with sequence 1, status `running`, the
acceptance `processing_lease_token`, the event's
instance/job/correlation IDs, attempt/generation, and `$execution.id`; its signed
node uses the selected running ID as `Idempotency-Key`.

`If Artifact Probe` is true only when the immutable test payload contains
`artifact_probe=true`. `PWR Signed Artifact` is the same credential-backed custom
HTTP node from Task 4, with `bodyMode=literalUtf8`,
`contentType=application/zpl`, and this non-sensitive deterministic fixture:

```text
^XA^FO20,20^FDFoundation smoke^FS^XZ
```

It sends the literal bytes directly, returns only status, SHA-256, and byte count,
and never places the body in output item JSON. Its target is constructed only from
the already verified `odoo_instance`, `job_id`, and `event_id`; it signs the exact
resolved path and uses the generation-specific
`payload.artifact_idempotency_keys_by_generation` value. The static verifier and
importer reject `bodyMode=literalUtf8` unless the registry entry is
`test_only=true`; production Shipping uses binary input instead. `Build Terminal
Callback` preserves the event bindings, uses
sequence 2 and status `succeeded`, and its signed node uses the selected terminal
ID. Thus a processing retry gets new callback and artifact request IDs while the
artifact endpoint's `(instance, job, event, kind)` identity still yields one stored
artifact; a node-level HTTP retry reuses the constructed IDs and changes only
timestamp, nonce, and signature.

The workflow contains no feature model, carrier call, real label, or Quality
decision. Its business effects are the test job state transition and one synthetic
artifact row. The static verifier rejects any callback or artifact edge that can
bypass a successful `process=true` acceptance, rejects real label content in Edit
Fields/Code/output JSON, and matches resolved artifact paths against the registered
template. Execution persistence is disabled, but the live gate still inspects the
execution metadata and requires that the synthetic bytes are absent.

Add this registry entry:

```json
{
  "file": "pwr-foundation-smoke-v2.json",
  "name": "PWR Foundation Smoke v2",
  "generation": "v2",
  "event_names": ["quality.assessment.requested.v1"],
  "webhook_paths": ["quality-assessment-v2"],
  "callback_paths": [
    "/api/internal/n8n/v2/events/accept",
    "/api/internal/n8n/v2/callbacks/status",
    "/api/internal/instances/{odoo_instance}/jobs/{job_id}/events/{source_event_id}/artifacts/zpl"
  ],
  "authentication": "native_header_hmac",
  "managed": true,
  "production_activation": false,
  "test_only": true,
  "activation_order": 90,
  "allowed_target_hosts": ["backend"],
  "credential_bindings": [
    {
      "node": "Webhook",
      "credential_type": "httpHeaderAuth",
      "logical_name": "pwr.v2.inbound-header"
    },
    {
      "node": "PWR Signature Gate",
      "credential_type": "pwrInboundHmac",
      "logical_name": "pwr.v2.backend-to-n8n-hmac"
    },
    {
      "node": "PWR Signed Acceptance",
      "credential_type": "pwrOutboundHmac",
      "logical_name": "pwr.v2.n8n-to-backend-hmac"
    },
    {
      "node": "PWR Signed Running Callback",
      "credential_type": "pwrOutboundHmac",
      "logical_name": "pwr.v2.n8n-to-backend-hmac"
    },
    {
      "node": "PWR Signed Artifact",
      "credential_type": "pwrOutboundHmac",
      "logical_name": "pwr.v2.n8n-to-backend-hmac"
    },
    {
      "node": "PWR Signed Terminal Callback",
      "credential_type": "pwrOutboundHmac",
      "logical_name": "pwr.v2.n8n-to-backend-hmac"
    }
  ]
}
```

This workflow is a test-only scaffold for the frozen Quality event target and stays
`production_activation=false`. The Visual Quality integration commit replaces this
registry entry with its approved workflow before activation; it must not leave two
managed workflows claiming `quality-assessment-v2`. The Foundation smoke remains
available only at its recorded rollback commit.

In production Compose:

```yaml
networks:
  edge-net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.10.0/24
  core-net:
    driver: bridge
    internal: true
  automation-net:
    driver: bridge
    internal: true
```

Attach services exactly:

```text
edge-net:       caddy=172.28.10.2, backend=172.28.10.3, pwa
core-net:       backend, final Odoo-19 service(s), db
automation-net: backend, db, n8n, whisper, piper, ollama
```

Mount `./n8n/workflow-registry.json` into backend at
`/run/pwr/workflow-registry.json:ro` and set
`WORKFLOW_REGISTRY_PATH=/run/pwr/workflow-registry.json`. The dispatcher loads
targets from that mount at runtime; Compose contains no duplicate webhook-path
environment variables.

Only Caddy retains:

```yaml
ports:
  - "443:443"
  - "80:80"
```

Remove `ports` from DB, every Odoo service/profile, n8n, and all model/audio services. `docker-compose.dev.yml` adds only:

```yaml
services:
  backend:
    ports: ["127.0.0.1:${BACKEND_HOST_PORT:-8000}:8000"]
  db:
    ports: ["127.0.0.1:${POSTGRES_HOST_PORT:-5433}:5432"]
  odoo:
    ports: ["127.0.0.1:${ODOO_HOST_PORT:-8069}:8069"]
  n8n:
    ports: ["127.0.0.1:${N8N_HOST_PORT:-5678}:5678"]
```

Apply corresponding loopback bindings to optional final Odoo-19 profiles under
distinct explicit variables. The backend loopback exists only in the development
and isolated live-test override so signed internal-route fixtures can bypass the
edge deny-list; production Compose publishes no backend port.

Switch role settings:

```yaml
db:
  environment:
    POSTGRES_USER: ${PWR_DB_ADMIN_USER:-pwr_db_admin}
    POSTGRES_PASSWORD: ${PWR_DB_ADMIN_PASSWORD:?PWR_DB_ADMIN_PASSWORD muss gesetzt sein}

odoo:
  environment:
    USER: ${ODOO_DB_USER:-odoo_app}
    PASSWORD: ${ODOO_DB_PASSWORD:?ODOO_DB_PASSWORD muss gesetzt sein}

n8n:
  build:
    context: ./n8n
    dockerfile: Dockerfile
  environment:
    DB_POSTGRESDB_USER: ${N8N_DB_USER:-n8n_app}
    DB_POSTGRESDB_PASSWORD: ${N8N_DB_PASSWORD:?N8N_DB_PASSWORD muss gesetzt sein}
    N8N_BLOCK_ENV_ACCESS_IN_NODE: "true"
    N8N_PUBLIC_API_DISABLED: "true"
    N8N_PUBLIC_API_SWAGGERUI_DISABLED: "true"
    N8N_SSRF_PROTECTION_ENABLED: "true"
    N8N_SSRF_ALLOWED_HOSTNAMES: backend
    EXECUTIONS_DATA_PRUNE: "true"
    EXECUTIONS_DATA_MAX_AGE: 720
    EXECUTIONS_DATA_SAVE_ON_SUCCESS: none
    EXECUTIONS_DATA_SAVE_ON_ERROR: all
```

Remove `NODE_FUNCTION_ALLOW_BUILTIN`, direct ports, public `WEBHOOK_URL`, and any edge network from n8n. Mount the credential bootstrap script read-only and mount Docker secret files below `/run/secrets`. Existing external-email workflows remain inactive while n8n has no egress.

Add secret-file settings to FastAPI:

```python
session_throttle_hmac_secret_file: str = ""
pwr_backend_to_n8n_active_secret_file: str = ""
pwr_backend_to_n8n_previous_secret_file: str = ""
pwr_n8n_to_backend_active_secret_file: str = ""
pwr_n8n_to_backend_previous_secret_file: str = ""
n8n_webhook_secret_file: str = ""
n8n_callback_secret_file: str = ""


def read_secret(direct: str, file_path: str) -> str:
    if direct and file_path:
        raise ValueError("Configure a secret value or a secret file, not both")
    if file_path:
        path = Path(file_path)
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise ValueError(f"Secret file permissions are too broad: {path}")
        return path.read_text(encoding="utf-8").strip()
    return direct
```

Update `validate_runtime_security()` first: resolve every direct/file pair exactly
once with `read_secret`, validate the resolved native secrets, decode the resolved
base64 values, and compare previous-key presence against the resolved previous
secret. A file-only production configuration must therefore pass the same checks
as a direct-value test configuration, while setting both forms fails startup.
Pass those resolved values into Task 6's session/throttle constructors, Task 9's
transport factory, Task 10's receiver keyring builder, and the legacy callback
guard. No downstream factory may test only a `*_b64` direct field. Compose mounts
the same direction-specific secrets into the relevant backend/n8n containers.
`.env.example` contains key IDs and secret file paths only, plus:

```text
RUNTIME_PROFILE=production
MOBILE_HEADER_GRACE_MODE=false
PWA_ORIGINS=https://picking.warehouse.test
TRUSTED_CADDY_PEERS=172.28.10.2
PWR_DB_ADMIN_USER=pwr_db_admin
ODOO_DB_USER=odoo_app
N8N_DB_USER=n8n_app
WORKFLOW_REGISTRY_PATH=/run/pwr/workflow-registry.json
```

No example contains a usable credential.

Replace Caddy with:

```caddy
:443 {
    tls /certs/cert.pem /certs/key.pem

    @blocked path \
        /docs /docs/* \
        /redoc /redoc/* \
        /openapi.json \
        /api/docs* \
        /api/redoc* \
        /api/openapi.json \
        /api/internal/* \
        /api/obsidian/* \
        /api/demo/*
    respond @blocked 404

    @public_api path /api/*
    handle @public_api {
        reverse_proxy backend:8000
    }

    handle {
        reverse_proxy pwa:80
    }

    log {
        output stdout
        format console
    }
}

:80 {
    redir https://{$LAN_HOST}{uri} permanent
}
```

There is no Odoo redirect, n8n path, n8n host matcher, or internal API proxy.

Update certificate generation to require DNS and IP:

```bash
LAN_DNS="${1:?Usage: setup-certs.sh picking.warehouse.test 192.0.2.10}"
LAN_IP="${2:?Usage: setup-certs.sh picking.warehouse.test 192.0.2.10}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkcert -cert-file "$TMP_DIR/cert.pem" -key-file "$TMP_DIR/key.pem" \
  "$LAN_DNS" "$LAN_IP" localhost 127.0.0.1
openssl x509 -in "$TMP_DIR/cert.pem" -noout -ext subjectAltName \
  | grep -F "DNS:$LAN_DNS"
openssl x509 -in "$TMP_DIR/cert.pem" -noout -ext subjectAltName \
  | grep -F "IP Address:$LAN_IP"
install -m 0644 "$TMP_DIR/cert.pem" "$CERT_DIR/cert.pem.new"
install -m 0600 "$TMP_DIR/key.pem" "$CERT_DIR/key.pem.new"
mv -f "$CERT_DIR/cert.pem.new" "$CERT_DIR/cert.pem"
mv -f "$CERT_DIR/key.pem.new" "$CERT_DIR/key.pem"
```

`check-certificate-expiry.sh` runs `openssl x509 -checkend 2592000 -noout` and exits nonzero when fewer than 30 days remain.

`test-db-role-migration-copy.sh` is the only feature-worktree entry point for a live
role migration. It:

1. resolves the current DB container's named volume mounted at
   `/var/lib/postgresql/data`;
2. stops backend, Odoo, n8n, and DB, then proves no running container mounts that
   source;
3. creates a run-ID-named copy and manifest with
   `clone-postgres-volume.sh create`, immediately runs `verify`, and never remounts
   the source;
4. exports an isolated `COMPOSE_PROJECT_NAME`, the base plus
   `docker-compose.db-migration.yml`, and the copy volume name;
5. starts only the copied DB with the recorded legacy superuser and proves both
   application services remain stopped;
6. creates a mode-`0700` backup directory and runs migration `backup`; then `apply`
   creates the app roles, switches the isolated Compose project to
   `odoo_app`/`n8n_app`, starts the apps, and is followed by `verify`, `rollback` in
   order;
7. requires both app health probes after rollback; and
8. in an `EXIT` trap, stops the copy project without `-v`, deletes only the
   manifest-bound copy volume, restores the original Compose project with the
   recorded legacy-role environment override, and verifies its pre-test health.

The script refuses an anonymous/bind-mounted source, a dirty copy name, a missing
role secret, any source/copy ID equality, or a running source mount. It prints
volume IDs, hashes, phases, and health states, never connection URIs or secrets.

`test-pwr-n8n-signing.sh`:

1. verifies credentials;
2. imports the smoke workflow inactive;
3. creates a UUID run ID and activates only that explicitly named smoke workflow
   through `activate-test`;
4. creates one real Odoo test job/outbox row with `artifact_probe=true` and
   generation-specific callback/artifact IDs;
5. dispatches it through real n8n;
6. tests valid acceptance, changed body, changed target, query, stale timestamp,
   replay signature nonce, active/previous key overlap, callback, and the real
   credential-backed synthetic ZPL artifact upload;
7. verifies the Odoo artifact hash/count and absence of request bytes in n8n
   execution JSON;
8. deactivates the smoke workflow and restores its prior state through the importer backup.

`verify-production-gates.sh` runs:

```bash
docker compose config --quiet
docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile
bash infrastructure/scripts/check-certificate-expiry.sh
curl --fail --cacert infrastructure/certs/cert.pem "https://${LAN_HOST}/api/health/live"
```

It asserts `404` for every blocked route, checks `ss -lnt` for no wildcard
8000/5432/5433/5678/8069/8100/9000/5500/11434, and prints an exact remote-probe
command for a second warehouse host. It treats port 80 only as a redirect listener;
the warehouse firewall evidence must show clients are allowed only TCP 443.

Document CA installation and trust activation on iOS/Android, SAN inspection, atomic rotation, Secure Cookie, camera, microphone, and PWA installation checks. The operator records device/OS/browser/date and pass/fail, never credentials.

- [ ] **Step 4: Run static, image, Compose, registry, TLS, and live smoke gates**

Run serially:

```bash
PYTHONPATH=. python3 -m pytest \
  infrastructure/tests/test_production_surface.py \
  infrastructure/tests/test_workflow_registry.py \
  infrastructure/tests/test_db_role_scripts.py \
  -q
python3 infrastructure/scripts/verify-workflows.py

docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet
docker compose build n8n
docker compose run --rm n8n n8n --version

bash infrastructure/scripts/test-db-role-migration-copy.sh
bash infrastructure/scripts/provision-n8n-credentials.sh provision
bash infrastructure/scripts/provision-n8n-credentials.sh verify
bash infrastructure/scripts/test-pwr-n8n-signing.sh
bash -n infrastructure/scripts/verify-production-gates.sh
```

Expected: all tests pass; n8n prints `2.13.3`; custom nodes load; the disposable
database copy passes apply/isolation/rollback and restores the untouched source;
the signed live smoke passes every positive/negative case; and the
production gate script is syntactically valid. Do not run the complete route-surface
gate yet: Task 16 owns the production app factory, and Task 17 runs the combined live
gate after that cutover. Save remote-host and physical mobile evidence only in Task
17.

- [ ] **Step 5: Commit production infrastructure**

```bash
git add \
  .env.example \
  backend/app/config.py \
  backend/app/dependencies.py \
  docker-compose.yml \
  docker-compose.dev.yml \
  docs/SETUP.md \
  infrastructure/caddy/Caddyfile \
  infrastructure/certs/README.md \
  infrastructure/scripts/check-certificate-expiry.sh \
  infrastructure/scripts/setup-certs.sh \
  infrastructure/scripts/test-db-role-migration-copy.sh \
  infrastructure/scripts/test-pwr-n8n-signing.sh \
  infrastructure/scripts/verify-production-gates.sh \
  infrastructure/tests/test_production_surface.py \
  n8n/Dockerfile \
  n8n/workflow-registry.json \
  n8n/workflows/pwr-foundation-smoke-v2.json
git commit -m "feat(platform): isolate services behind signed HTTPS edge"
```

### Task 16: Production Route Surface and Required Browser Idempotency

**Files:**
- Create: `backend/app/runtime.py`
- Create: `backend/app/services/hmac_keyrings.py`
- Create: `backend/tests/security_settings.py`
- Create: `backend/tests/test_route_security.py`
- Create: `backend/tests/test_runtime_isolation.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/dependencies.py`
- Modify: `backend/app/routers/auth.py`
- Modify: `backend/app/routers/health.py`
- Modify: `backend/app/routers/n8n_v2.py`
- Modify: `backend/app/routers/pickings.py`
- Modify: `backend/app/routers/quality.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_auth_dependencies.py`
- Modify: `backend/tests/test_auth_routes.py`
- Modify: `backend/tests/test_dependencies_instance.py`
- Modify: `backend/tests/test_mobile_routes.py`
- Modify: `backend/tests/test_n8n_internal_routes.py`
- Modify: `backend/tests/test_n8n_v2_routes.py`
- Modify: `backend/tests/test_n8n_v2_binary_routes.py`
- Modify: `backend/tests/test_cluster_routes.py` only for app-level security expectations
- Modify: `backend/tests/test_voice_routes.py` only for app-level security expectations
- Modify: `infrastructure/caddy/Caddyfile` to deny remaining service-only paths at the edge

**Ownership note:** Do not edit `backend/app/routers/voice.py`, `backend/app/routers/cluster.py`, or their domain services in this task. Voice and Cluster tracks own their business behavior. This task enforces session, Origin, CSRF, and key syntax at app inclusion; their track gates must add the business reservation flow before strict rollout.

**Interfaces:**
- Consumes: authenticated principal Task 7, scoped reservation Task 12, production network Task 15.
- Produces: `RuntimeServices`, `build_runtime_services(candidate_settings)`,
  `get_runtime(request)`, `validate_idempotency_key(value) -> str`,
  `require_domain_idempotency`, `create_app(candidate_settings) -> FastAPI`, exact
  pre-auth allowlist, and fail-closed app-bound dependencies.

- [ ] **Step 1: Write failing public-surface, CSRF, and idempotency tests**

```python
# backend/tests/security_settings.py
from app.config import Settings


def make_secure_settings(**overrides) -> Settings:
    values = {
        "runtime_profile": "production",
        "pwa_origins": "https://picking.test",
        "mobile_header_grace_mode": False,
        "odoo_api_key": "service-key",
        "session_throttle_hmac_secret_b64": (
            "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
        ),
        "pwr_backend_to_n8n_active_key_id": "b2n-route-test",
        "pwr_backend_to_n8n_active_secret_b64": (
            "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="
        ),
        "pwr_n8n_to_backend_active_key_id": "n2b-route-test",
        "pwr_n8n_to_backend_active_secret_b64": (
            "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI="
        ),
        "n8n_webhook_secret": "3" * 32,
        "n8n_callback_secret": "4" * 32,
        "dispatcher_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)
```

```python
# backend/tests/test_route_security.py
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_principal, get_session_service
from app.main import create_app
from app.models.auth import Principal
from app.services.auth_sessions import CsrfFailed
from tests.security_settings import make_secure_settings

PRINCIPAL = Principal(
    picker_user_id=7,
    picker_name="Mina Muster",
    device_id="device-42",
    odoo_instance="o19",
    roles=frozenset({"picker"}),
    session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
)


class StubSessions:
    async def validate_csrf(self, principal, token, origin):
        if token != "csrf-ok" or origin != "https://picking.test":
            raise CsrfFailed("CSRF rejected")


@pytest.fixture
def secure_settings():
    return make_secure_settings()


@pytest.fixture
def app(secure_settings):
    return create_app(secure_settings)


def test_production_has_exact_preauth_allowlist(app):
    client = TestClient(app)
    assert client.get("/api/health/live").status_code == 200
    assert client.get("/api/auth/instances").status_code == 200
    assert client.get("/api/pickers").status_code == 401
    assert client.get(
        "/api/pickings",
        headers={
            "X-Picker-User-Id": "7",
            "X-Device-Id": "spoof",
            "X-Odoo-Instance": "o19",
        },
    ).status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
        "/api/demo/traceability",
        "/api/obsidian/search?q=test",
        "/api/instances",
        "/api/health",
    ],
)
def test_removed_production_surfaces_are_404(app, path):
    assert TestClient(app).get(path).status_code == 404


def test_browser_post_requires_origin_csrf_and_domain_key(app):
    app.dependency_overrides[get_current_principal] = lambda: PRINCIPAL
    app.dependency_overrides[get_session_service] = lambda: StubSessions()
    try:
        client = TestClient(app)
        path = "/api/pickings/42/confirm-line"
        body = {"move_line_id": 9, "scanned_barcode": "ABC", "quantity": 1}
        assert client.post(path, json=body).status_code == 403
        assert client.post(
            path,
            json=body,
            headers={
                "Origin": "https://picking.test",
                "X-CSRF-Token": "csrf-ok",
            },
        ).status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "value",
    ["", "contains space", "a" * 129, "umlaut-\u00e4", "line\nbreak"],
)
def test_domain_idempotency_key_is_1_to_128_visible_ascii(app, value):
    app.dependency_overrides[get_current_principal] = lambda: PRINCIPAL
    app.dependency_overrides[get_session_service] = lambda: StubSessions()
    try:
        response = TestClient(app).post(
            "/api/quality-alerts",
            headers={
                "Origin": "https://picking.test",
                "X-CSRF-Token": "csrf-ok",
                "Idempotency-Key": value,
            },
            data={"description": "test"},
        )
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()
```

Add matrix tests:

```python
DOMAIN_MUTATIONS = (
    ("POST", "/api/pickings/42/confirm-line"),
    ("POST", "/api/pickings/42/replenishment-request"),
    ("POST", "/api/quality-alerts"),
    ("POST", "/api/cluster/batches"),
    ("POST", "/api/cluster/batches/5/confirm-line"),
    ("POST", "/api/cluster/batches/5/validate"),
)

IDEMPOTENCY_EXEMPT = (
    ("POST", "/api/auth/picker-session"),
    ("POST", "/api/auth/csrf"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/pickings/42/heartbeat"),
    ("POST", "/api/voice/recognize"),
    ("POST", "/api/voice/assist"),
    ("POST", "/api/voice/tts"),
)
```

The matrix asserts missing keys fail only the domain list. All authenticated browser POSTs other than login require CSRF. `voice/assist` remains idempotency-exempt only while it performs no downstream business write.

```python
# backend/tests/test_runtime_isolation.py
import base64

from fastapi import Depends
from fastapi.testclient import TestClient

from app.dependencies import get_n8n_to_backend_keyring, get_request_settings
from app.main import create_app
from tests.security_settings import make_secure_settings


def test_two_apps_do_not_share_settings_keys_or_cors():
    secure_settings = make_secure_settings()
    left_settings = secure_settings.model_copy(
        update={
            "session_cookie_name": "left_session",
            "pwa_origins": "https://left.test",
            "pwr_n8n_to_backend_active_key_id": "n2b-left",
        }
    )
    right_settings = secure_settings.model_copy(
        update={
            "session_cookie_name": "right_session",
            "pwa_origins": "https://right.test",
            "pwr_n8n_to_backend_active_key_id": "n2b-right",
        }
    )
    left = create_app(left_settings)
    right = create_app(right_settings)

    @left.get("/_test/runtime")
    def left_runtime(
        candidate=Depends(get_request_settings),
        keyring=Depends(get_n8n_to_backend_keyring),
    ):
        return {"cookie": candidate.session_cookie_name, "key": keyring.active.key_id}

    @right.get("/_test/runtime")
    def right_runtime(
        candidate=Depends(get_request_settings),
        keyring=Depends(get_n8n_to_backend_keyring),
    ):
        return {"cookie": candidate.session_cookie_name, "key": keyring.active.key_id}

    assert TestClient(left).get("/_test/runtime").json() == {
        "cookie": "left_session",
        "key": "n2b-left",
    }
    assert TestClient(right).get("/_test/runtime").json() == {
        "cookie": "right_session",
        "key": "n2b-right",
    }
    cors = TestClient(left).options(
        "/api/auth/instances",
        headers={
            "Origin": "https://left.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert cors.headers["access-control-allow-origin"] == "https://left.test"
    assert "access-control-allow-origin" not in TestClient(left).options(
        "/api/auth/instances",
        headers={
            "Origin": "https://right.test",
            "Access-Control-Request-Method": "GET",
        },
    ).headers


def test_runtime_reads_file_only_hmac_secrets(tmp_path):
    encoded = base64.b64encode(b"f" * 32).decode("ascii")
    paths = {}
    for name in ("session", "backend_to_n8n", "n8n_to_backend"):
        path = tmp_path / name
        path.write_text(encoded, encoding="utf-8")
        path.chmod(0o600)
        paths[name] = str(path)

    candidate = make_secure_settings(
        session_throttle_hmac_secret_b64="",
        session_throttle_hmac_secret_file=paths["session"],
        pwr_backend_to_n8n_active_secret_b64="",
        pwr_backend_to_n8n_active_secret_file=paths["backend_to_n8n"],
        pwr_n8n_to_backend_active_secret_b64="",
        pwr_n8n_to_backend_active_secret_file=paths["n8n_to_backend"],
    )
    runtime = create_app(candidate).state.runtime
    assert runtime.sessions is not None
    assert runtime.n8n_to_backend_keyring.active.key_id == "n2b-route-test"
```

Also create two production apps with distinct cookie names, trusted-proxy lists,
origins, and stub session services. A login through each app must emit only its own
`Set-Cookie` name and `Max-Age`; logout must delete that same name. A forwarded
source IP trusted by the left app but not the right app must be interpreted
differently. This test reaches the real auth router rather than a synthetic test
route.

- [ ] **Step 2: Run route security plus existing router suites**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  tests/test_route_security.py \
  tests/test_runtime_isolation.py \
  tests/test_auth_dependencies.py \
  tests/test_dependencies_instance.py \
  tests/test_mobile_routes.py \
  tests/test_n8n_internal_routes.py \
  tests/test_n8n_v2_routes.py \
  tests/test_n8n_v2_binary_routes.py \
  tests/test_cluster_routes.py \
  tests/test_voice_routes.py \
  tests/test_auth_routes.py \
  -q
```

Expected: production surface and route dependency tests fail against the current global app and permissive routes.

- [ ] **Step 3: Build the app from an explicit route policy**

Add strict key validation and path classification:

```python
# backend/app/dependencies.py
import re

_IDEMPOTENCY_KEY = re.compile(r"^[\x21-\x7e]{1,128}$")
_DOMAIN_MUTATIONS = (
    re.compile(r"^/api/pickings/[1-9][0-9]*/confirm-line$"),
    re.compile(r"^/api/pickings/[1-9][0-9]*/validate$"),
    re.compile(r"^/api/pickings/[1-9][0-9]*/replenishment-request$"),
    re.compile(r"^/api/pickings/[1-9][0-9]*/pack$"),
    re.compile(r"^/api/quality-alerts$"),
    re.compile(r"^/api/quality-dispositions(?:/.*)?$"),
    re.compile(r"^/api/cluster/batches$"),
    re.compile(r"^/api/cluster/batches/[1-9][0-9]*/(?:confirm-line|abort|validate)$"),
    re.compile(r"^/api/shipping/labels(?:/.*)?$"),
)


def validate_idempotency_key(value: str | None) -> str:
    if value is None or not _IDEMPOTENCY_KEY.fullmatch(value):
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key must contain 1 to 128 visible ASCII characters.",
        )
    return value


def require_domain_idempotency(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    if request.method == "POST" and any(
        pattern.fullmatch(request.url.path) for pattern in _DOMAIN_MUTATIONS
    ):
        validate_idempotency_key(idempotency_key)


async def require_csrf_on_browser_mutation(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    sessions: SessionService = Depends(get_session_service),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        try:
            await sessions.validate_csrf(
                principal, x_csrf_token, request.headers.get("Origin")
            )
        except CsrfFailed as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
```

`get_write_request_context()` reuses the already validated key, and domain route
bodies never provide it. The app-level dependency rejects a missing or malformed key
before a domain route runs. Existing route methods then call Task 12's
`begin_idempotent_request()` before any business read/write; that method requires the
server-derived `context.principal_scope`. Remove header-specific error copy from
Quality. Claim/release may retain optional idempotency; heartbeat always bypasses
persistent reservation.

Build one isolated dependency graph per application:

```python
# backend/app/runtime.py
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from app.config import (
    OdooProfile,
    Settings,
    decode_secret_b64,
    get_instance_registry,
    parse_origins,
    read_secret,
)
from app.models.webhook_security import HmacKeyring
from app.services.auth_sessions import SessionService
from app.services.hmac_keyrings import build_n8n_to_backend_keyring
from app.services.odoo_client import OdooClient
from app.services.outbox_dispatcher import (
    IntegrationWatchdog,
    OutboxDispatcher,
    build_integration_watchdog,
    build_outbox_dispatcher,
)
from app.services.workflow_targets import load_event_targets


@dataclass
class OdooClientPool:
    profiles: dict[str, OdooProfile]
    _clients: dict[str, OdooClient] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def get(self, name: str) -> OdooClient:
        profile = self.profiles.get(name)
        if profile is None:
            raise KeyError(name)
        client = self._clients.get(name)
        if client is None:
            with self._lock:
                client = self._clients.get(name)
                if client is None:
                    client = OdooClient(profile)
                    self._clients[name] = client
        return client


@dataclass(frozen=True)
class RuntimeServices:
    settings: Settings
    instances: dict[str, OdooProfile]
    clients: OdooClientPool
    sessions: SessionService | None
    n8n_to_backend_keyring: HmacKeyring | None
    dispatcher: OutboxDispatcher | None
    watchdog: IntegrationWatchdog | None


def build_runtime_services(candidate: Settings) -> RuntimeServices:
    instances = get_instance_registry(candidate)
    clients = OdooClientPool(instances)
    throttle_secret_b64 = read_secret(
        candidate.session_throttle_hmac_secret_b64,
        candidate.session_throttle_hmac_secret_file,
    )
    sessions = None
    if throttle_secret_b64:
        sessions = SessionService(
            client_factory=clients.get,
            instance_names=set(instances),
            throttle_secret=decode_secret_b64(
                "SESSION_THROTTLE_HMAC_SECRET_B64",
                throttle_secret_b64,
            ),
            allowed_origins=set(parse_origins(candidate.pwa_origins)),
            session_seconds=candidate.session_max_age_seconds,
            revalidate_seconds=candidate.session_role_revalidate_seconds,
        )
    keyring = (
        build_n8n_to_backend_keyring(candidate)
        if candidate.pwr_n8n_to_backend_active_key_id
        else None
    )
    targets = (
        load_event_targets(Path(candidate.workflow_registry_path))
        if candidate.dispatcher_enabled
        else {}
    )
    return RuntimeServices(
        settings=candidate,
        instances=instances,
        clients=clients,
        sessions=sessions,
        n8n_to_backend_keyring=keyring,
        dispatcher=(
            build_outbox_dispatcher(candidate, clients.get, targets)
            if candidate.dispatcher_enabled
            else None
        ),
        watchdog=(
            build_integration_watchdog(candidate, clients.get)
            if candidate.dispatcher_enabled
            else None
        ),
    )
```

Move Task 10's pure `build_n8n_to_backend_keyring(candidate)` implementation into
`app/services/hmac_keyrings.py`; it resolves active and previous values with
`read_secret(direct, file_path)` before base64 decoding. `dependencies.py` imports
that builder only for tests and obtains the built keyring from `RuntimeServices` at
request time. Task 1 adds `workflow_registry_path`; Task 9 implements
`load_event_targets()`, `build_outbox_dispatcher()`, and
`build_integration_watchdog()` with the signatures imported above. Task 15 updates
the dispatcher factory to resolve its native and HMAC credentials through
`read_secret`. The runtime builder must not open a network connection; Odoo and
HTTP clients connect lazily.

Replace module-global settings/client caches in `dependencies.py` with:

```python
def get_runtime(request: Request) -> RuntimeServices:
    return request.app.state.runtime


def get_request_settings(
    runtime: RuntimeServices = Depends(get_runtime),
) -> Settings:
    return runtime.settings


def get_session_service(
    runtime: RuntimeServices = Depends(get_runtime),
) -> SessionService:
    if runtime.sessions is None:
        raise HTTPException(status_code=503, detail="Session service is not configured.")
    return runtime.sessions


def get_n8n_to_backend_keyring(
    runtime: RuntimeServices = Depends(get_runtime),
) -> HmacKeyring:
    if runtime.n8n_to_backend_keyring is None:
        raise HTTPException(status_code=503, detail="HMAC receiver is not configured.")
    return runtime.n8n_to_backend_keyring
```

Refactor `get_current_principal`, `require_roles`,
`require_n8n_callback_secret`, every Odoo-client dependency, the HMAC dependency,
and the legacy n8n/LLM client builders to consume `RuntimeServices` or
`get_request_settings`; none may reference module-global `settings`, `_clients`, or
an `lru_cache`. Every auth route receives `Settings` through
`Depends(get_request_settings)`: cookie name, `Secure`, `SameSite`, path,
`Max-Age`, Origin policy, and trusted proxy peers all come from that request's app
runtime. `auth.list_auth_instances` reads `runtime.instances.values()`.
`get_callback_odoo_client` takes the runtime, and every handler in
`routers/n8n_v2.py` uses that dependency; unknown instance names are rejected
before `runtime.clients.get`.

Rewrite the Task 10/11 route fixtures at the same time: they create an app with
`make_secure_settings(odoo_instances_json=...)`, insert their `FakeOdoo` objects
into `app.state.runtime.clients._clients` under the declared instance names, and
use that app's `TestClient`. Remove every monkeypatch of
`app.dependencies._get_cached_client` because that global no longer exists. Add a
negative fixture case where an undeclared instance returns `403` and no fake's call
list changes.

Apply the same app-bound pattern to Task 7's `test_auth_dependencies.py`,
`test_dependencies_instance.py`, `test_n8n_internal_routes.py`, and
`test_auth_routes.py`: build through
`create_app(candidate)`, override dependencies on that app, and access fake clients
only through `app.state.runtime.clients`. `backend/tests/conftest.py` must not
import the module-global `app` when it constructs shared clients. A repository-wide
search for `_get_cached_client`, `app.dependencies._clients`, and direct mutation
of module-global `settings` in tests must return no matches before the full suite.

Refactor Task 9's lifespan to accept this runtime. When dispatching is enabled,
assert its dispatcher and watchdog are non-null, iterate `runtime.instances`, and
retain the per-instance `try/except` so one unavailable Odoo profile does not kill
the watchdog task:

```python
def build_lifespan(runtime: RuntimeServices):
    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        stop_event = asyncio.Event()
        tasks: list[asyncio.Task] = []
        if runtime.settings.dispatcher_enabled:
            assert runtime.dispatcher is not None and runtime.watchdog is not None
            tasks.append(asyncio.create_task(runtime.dispatcher.run(stop_event)))

            async def watchdog_loop():
                while not stop_event.is_set():
                    for instance in runtime.instances:
                        try:
                            await runtime.watchdog.run_once(instance)
                        except Exception:
                            logger.exception(
                                "Watchdog cycle failed for instance %s", instance
                            )
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=60)
                    except TimeoutError:
                        pass

            tasks.append(asyncio.create_task(watchdog_loop()))
        try:
            yield
        finally:
            stop_event.set()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    return app_lifespan
```

Define the app factory:

```python
# backend/app/main.py
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.dependencies import (
    get_current_principal,
    require_csrf_on_browser_mutation,
    require_domain_idempotency,
)


def create_app(candidate_settings=settings) -> FastAPI:
    validate_runtime_security(candidate_settings)
    runtime = build_runtime_services(candidate_settings)
    production = candidate_settings.runtime_profile == "production"
    application = FastAPI(
        title="Picking Assistant API",
        version="0.2.0",
        docs_url=None if production else "/api/docs",
        redoc_url=None if production else "/api/redoc",
        openapi_url=None if production else "/api/openapi.json",
        lifespan=build_lifespan(runtime),
    )
    application.state.runtime = runtime
    origins = [
        item.strip()
        for item in candidate_settings.pwa_origins.split(",")
        if item.strip()
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
    )

    application.include_router(health.router, prefix="/api", tags=["health"])
    application.include_router(auth.router, prefix="/api", tags=["auth"])

    browser_dependencies = [
        Depends(get_current_principal),
        Depends(require_csrf_on_browser_mutation),
        Depends(require_domain_idempotency),
    ]
    for router, tag in (
        (pickings.router, "pickings"),
        (cluster.router, "cluster"),
        (quality.router, "quality"),
        (voice.router, "voice"),
        (scan.router, "scan"),
    ):
        application.include_router(
            router,
            prefix="/api",
            tags=[tag],
            dependencies=browser_dependencies,
        )

    application.include_router(n8n_v2.router, prefix="/api")
    application.include_router(n8n_internal.router, prefix="/api")
    application.include_router(llm.router, prefix="/api")
    application.include_router(integration.router, prefix="/api")

    if not production:
        application.include_router(obsidian.router, prefix="/api")
        application.include_router(demo.router, prefix="/api")
        application.include_router(instances.router, prefix="/api")
    return application


app = create_app()
```

Change health to:

```python
@router.get("/health/live")
async def liveness():
    return {"status": "ok", "service": "picking-assistant-backend"}
```

Do not keep `/api/health`. Readiness and diagnostics live below an internal router and are not proxied by Caddy.

Add `/api/integration/*` to Caddy's blocked matcher; n8n reaches it directly over `automation-net`. `/api/internal/*`, Obsidian, Demo, Docs, n8n editor/API, and Odoo stay unreachable from the edge.

Add explicit downstream gates to the program status:

```text
PWA gate:
  login UI uses loginPickerSession/getCurrentSession/rotateCsrfToken/logoutPickerSession
  reload rotates missing CSRF
  instance switch logs out and requires credentials

Voice gate:
  voice/assist cannot invoke shortage-reported or any business write directly
  a confirmed mutation calls an explicit idempotent domain endpoint

Cluster gate:
  create/confirm/abort/validate use MobileWorkflowService reservation
  same key/same body replays; same key/different body conflicts
```

Production rollout cannot set `DISPATCHER_ENABLED=true` or close the legacy header mode until these three downstream test gates are attached to their integration commits.

- [ ] **Step 4: Run full backend and PWA API suites in secure mode**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests -q \
  --ignore=tests/live

cd ..
node --test pwa/js/tests/*.test.mjs
python3 infrastructure/scripts/verify-workflows.py
git diff --check
```

Expected: all backend, PWA API, and workflow contract tests pass; production factory has only the intended pre-auth routes and protected internal service routes.

- [ ] **Step 5: Commit the production API surface**

```bash
git add \
  backend/app/dependencies.py \
  backend/app/main.py \
  backend/app/runtime.py \
  backend/app/services/hmac_keyrings.py \
  backend/app/routers/auth.py \
  backend/app/routers/health.py \
  backend/app/routers/n8n_v2.py \
  backend/app/routers/pickings.py \
  backend/app/routers/quality.py \
  backend/tests/conftest.py \
  backend/tests/test_auth_dependencies.py \
  backend/tests/test_auth_routes.py \
  backend/tests/test_cluster_routes.py \
  backend/tests/test_dependencies_instance.py \
  backend/tests/test_mobile_routes.py \
  backend/tests/test_n8n_internal_routes.py \
  backend/tests/test_n8n_v2_routes.py \
  backend/tests/test_n8n_v2_binary_routes.py \
  backend/tests/test_route_security.py \
  backend/tests/test_runtime_isolation.py \
  backend/tests/security_settings.py \
  backend/tests/test_voice_routes.py \
  infrastructure/caddy/Caddyfile
git commit -m "feat(api): enforce session csrf and domain idempotency"
```

### Task 17: Two-Database, Concurrency, Restart, and Rollout Gates

**Files:**
- Create: `backend/tests/live/__init__.py`
- Create: `backend/tests/live/conftest.py`
- Create: `backend/tests/live/test_odoo19_instance_routing.py`
- Create: `backend/tests/live/test_odoo19_outbox_concurrency.py`
- Create: `infrastructure/scripts/seed-foundation-live-test.py`
- Create: `infrastructure/scripts/test-foundation-restart.sh`
- Create: `infrastructure/scripts/run-foundation-live-gates.sh`
- Create: `infrastructure/scripts/verify-remote-surface.sh`
- Create: `docs/runbooks/foundation-rollout.md`
- Modify: `backend/pytest.ini`
- Modify: `.gitignore` to ignore `/.artifacts/`
- Modify at integration time: `docs/superpowers/parallel/2026-07-23-program-status.md`

**Interfaces:**
- Consumes: all previous Foundation tasks. The PWA, Voice, and Cluster gates listed
  in Task 16 are recorded as later production-activation blockers, not as
  prerequisites for merging the Foundation.
- Produces: reproducible evidence for two-instance isolation, real database races,
  kill/restart delivery, remote port isolation, device TLS trust, and a controlled
  rollout/rollback runbook for the later integrated release.

- [ ] **Step 1: Write live tests that cannot pass against mocks**

Register markers:

```ini
# backend/pytest.ini
[pytest]
markers =
    odoo19_live: requires a real Odoo 19 process with two independent RPC connections
    foundation_live: requires the real Odoo 19, FastAPI, n8n, and PostgreSQL stack
```

The live fixture refuses missing environment instead of silently using `local`:

```python
# backend/tests/live/conftest.py
import base64
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

REQUIRED = (
    "ODOO19_LIVE_URL",
    "ODOO19_LIVE_DB_A",
    "ODOO19_LIVE_DB_B",
    "ODOO19_LIVE_USER",
    "ODOO19_LIVE_PASSWORD_FILE",
    "FOUNDATION_API_URL",
    "FOUNDATION_CA_FILE",
    "FOUNDATION_N2B_KEY_ID",
    "FOUNDATION_N2B_SECRET_FILE",
    "FOUNDATION_SEED_METADATA",
)


@pytest.fixture(scope="session")
def live_config():
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        pytest.fail(f"live gate requires environment: {', '.join(missing)}")
    return {name: os.environ[name] for name in REQUIRED}


@pytest_asyncio.fixture
async def independent_rpc_clients(live_config):
    limits = httpx.Limits(max_connections=2, max_keepalive_connections=0)
    async with (
        httpx.AsyncClient(limits=limits) as first,
        httpx.AsyncClient(limits=limits) as second,
    ):
        yield first, second
```

The same `conftest.py` implements these concrete fixtures; none may return a mock:

```python
@pytest.fixture(scope="session")
def seed_metadata(live_config):
    path = Path(live_config["FOUNDATION_SEED_METADATA"])
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"instances", "twenty_event_ids", "restart_event"}
    if set(data) != required:
        pytest.fail("seed metadata schema mismatch")
    return data


@pytest.fixture
def live_service_password(live_config):
    path = Path(live_config["ODOO19_LIVE_PASSWORD_FILE"])
    if path.stat().st_mode & 0o077:
        pytest.fail("live service password file permissions are too broad")
    return path.read_text(encoding="utf-8").strip()


@pytest.fixture
def rpc_call(live_config, live_service_password):
    async def call(client, database, model, method, args):
        uid = await json_rpc(
            client,
            live_config["ODOO19_LIVE_URL"],
            "common",
            "authenticate",
            [
                database,
                live_config["ODOO19_LIVE_USER"],
                live_service_password,
                {},
            ],
        )
        if not uid:
            pytest.fail(f"live API authentication failed for {database}")
        return await json_rpc(
            client,
            live_config["ODOO19_LIVE_URL"],
            "object",
            "execute_kw",
            [
                database,
                uid,
                live_service_password,
                model,
                method,
                args,
                {},
            ],
        )

    return call


@pytest.fixture
def seeded_twenty_events(seed_metadata):
    return tuple(seed_metadata["twenty_event_ids"])


@pytest.fixture
def seeded_event(seed_metadata):
    return dict(seed_metadata["restart_event"])
```

`json_rpc()` posts JSON-RPC 2.0 with a per-call UUID, requires HTTP 200, rejects an
RPC `error` member, and returns only `result`. `odoo_probe(database, selector)` uses
the same `rpc_call` and guarded `api_get_job`/read-only `search_count` methods.
`all_database_write_counts()` returns job/outbox/event-receipt/callback-receipt
counts for both named databases. `signed_callback(...)` loads the selected seeded
job/lease metadata, builds `CallbackEnvelopeV2`, serializes once, signs with the
configured n8n-to-backend key from the mode-`0600` secret file, and posts with
`httpx.AsyncClient`. `FOUNDATION_API_URL` is the loopback-only backend URL in the
isolated live override; the fixture rejects a non-loopback plain-HTTP URL. If the
configured URL is HTTPS it uses `FOUNDATION_CA_FILE` for verification. Public
Caddy/TLS behavior is tested separately through the edge and remote probes. The
fixture never obtains a `local` client. Add fixture self-tests that corrupt the seed
schema and RPC error response and assert fail-closed behavior.

The instance-routing test:

```python
# backend/tests/live/test_odoo19_instance_routing.py
import pytest


@pytest.mark.foundation_live
@pytest.mark.asyncio
async def test_same_numeric_ids_never_cross_instance(
    live_config, signed_callback, odoo_probe
):
    seeded_a = await odoo_probe(live_config["ODOO19_LIVE_DB_A"], "seeded")
    seeded_b = await odoo_probe(live_config["ODOO19_LIVE_DB_B"], "seeded")
    assert seeded_a["aggregate_id"] == seeded_b["aggregate_id"]
    assert seeded_a["job_id"] != seeded_b["job_id"]

    response = await signed_callback(
        instance="o19-a",
        job_id=seeded_a["job_id"],
        source_event_id=seeded_a["event_id"],
        aggregate_id=seeded_a["aggregate_id"],
    )
    assert response.status_code == 200
    assert (await odoo_probe(
        live_config["ODOO19_LIVE_DB_A"], seeded_a["job_id"]
    ))["state"] == "succeeded"
    assert (await odoo_probe(
        live_config["ODOO19_LIVE_DB_B"], seeded_b["job_id"]
    ))["state"] == "queued"


@pytest.mark.foundation_live
@pytest.mark.asyncio
async def test_unknown_signed_instance_has_no_local_fallback(
    signed_callback, all_database_write_counts
):
    before = await all_database_write_counts()
    response = await signed_callback(
        instance="unknown",
        job_id="c5ee6068-a8f3-4902-a882-2c17de2dfed1",
    )
    assert response.status_code == 403
    assert await all_database_write_counts() == before
```

The real concurrency test uses two independent JSON-RPC HTTP clients and asserts:

```python
# backend/tests/live/test_odoo19_outbox_concurrency.py
import asyncio
import pytest


@pytest.mark.odoo19_live
@pytest.mark.asyncio
async def test_two_dispatchers_lease_disjoint_union(
    live_config, seeded_twenty_events, rpc_call, independent_rpc_clients
):
    first, second = independent_rpc_clients
    leases_a, leases_b = await asyncio.gather(
        rpc_call(
            first,
            live_config["ODOO19_LIVE_DB_A"],
            "picking.assistant.outbox",
            "api_lease_due",
            ["worker-a", 20, 60],
        ),
        rpc_call(
            second,
            live_config["ODOO19_LIVE_DB_A"],
            "picking.assistant.outbox",
            "api_lease_due",
            ["worker-b", 20, 60],
        ),
    )
    ids_a = {item["event_id"] for item in leases_a}
    ids_b = {item["event_id"] for item in leases_b}
    assert ids_a.isdisjoint(ids_b)
    assert ids_a | ids_b == set(seeded_twenty_events)


@pytest.mark.odoo19_live
@pytest.mark.asyncio
async def test_acceptance_race_starts_exactly_one_processing_attempt(
    live_config, seeded_event, rpc_call, independent_rpc_clients
):
    first, second = independent_rpc_clients
    common = [
        seeded_event["event_id"],
        seeded_event["job_id"],
        seeded_event["fingerprint"],
        "b2n-live",
    ]
    results = await asyncio.gather(
        rpc_call(
            first,
            live_config["ODOO19_LIVE_DB_A"],
            "picking.assistant.event.receipt",
            "api_accept_event",
            [
                *common,
                "123e4567-e89b-42d3-a456-426614174021",
                1,
                "n2b-live",
                "123e4567-e89b-42d3-a456-426614174011",
            ],
        ),
        rpc_call(
            second,
            live_config["ODOO19_LIVE_DB_A"],
            "picking.assistant.event.receipt",
            "api_accept_event",
            [
                *common,
                "123e4567-e89b-42d3-a456-426614174022",
                1,
                "n2b-live",
                "123e4567-e89b-42d3-a456-426614174012",
            ],
        ),
    )
    assert sorted(result["process"] for result in results) == [False, True]
```

Add two more real-race tests:

- concurrent scoped Core reserve: one `reserved`, one `pending`/`replay`, one row;
- watchdog generation rollover: old lease/generation callback conflicts, current lease succeeds, one terminal job.

`seed-foundation-live-test.py` is an Odoo-shell seed, not a public RPC client. The
orchestrator creates databases with `pwr_db_admin` and initializes modules through
the Odoo CLI first; it then pipes this versioned script into a one-off
`odoo shell -d DATABASE` process running as the normal Odoo application service.
The script receives `PWR_SEED_INSTANCE` and the test password through the
short-lived `PWR_TEST_SERVICE_PASSWORD` process environment, uses the
shell-provided `env`, installs no demo data, exposes no seed endpoint, and
deterministically creates:

- service/picker/supervisor users using the password read from the mounted
  mode-`0400` test secret file;
- identical aggregate numeric IDs in both databases;
- 20 pending events for concurrency in database A;
- one delayed smoke event for restart with immutable, distinct generation-1 and
  generation-2 callback and artifact-request UUIDs.

The two invocations run serially (`o19-a`, then `o19-b`). Each writes exactly one
stdout line prefixed `PWR_SEED_METADATA=` containing only that database's IDs and
counts; Odoo logs may surround it. The host orchestrator requires exactly one
marker per invocation, extracts it into mode-`0600` temporary files, validates
them, and atomically merges them into
`.artifacts/foundation-seed-metadata.json` inside a host-owned mode-`0700` ignored
directory. No container writes the bind-mounted directory, so the gate is
independent of the Odoo image UID. The orchestrator removes old metadata before
the first invocation and requires the final top-level schema `instances`,
`twenty_event_ids`, and `restart_event` before starting tests. Neither the marker
nor logs contain credentials, tokens, event bodies, or artifact bytes.

- [ ] **Step 2: Run tests without live environment and confirm fail-closed behavior**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  -m "odoo19_live or foundation_live" tests/live -q
```

Expected: the session fixture fails with the exact missing environment list. A skip is not an acceptable gate result.

- [ ] **Step 3: Add serial orchestration and rollback runbook**

`test-foundation-restart.sh` uses the test-only smoke workflow and performs:

```text
1. Create a run ID, call activate-test, register mandatory deactivate-test cleanup,
   then create one job/outbox event with `test_delay_seconds=60` and
   `artifact_probe=true`.
2. Poll until outbox=delivered and event receipt=processing.
3. Record event_id, body SHA-256, generation=1, job ID, and business effect count.
4. docker compose stop backend n8n.
5. Start backend first; wait for the five-minute lease/watchdog transition.
6. Start n8n; dispatcher sends the same event ID and exact body at generation=2.
7. Poll for one terminal succeeded callback.
8. Assert one job, one terminal effect, one event receipt, monotonically increasing
   callbacks, and exactly one `zpl` artifact uploaded by the real
   `PWR Signed Artifact` n8n node.
9. Fetch artifact metadata through the guarded Odoo API and require the SHA-256 and
   byte count of the fixed synthetic ZPL, with no second artifact/provider effect.
10. Compare pre/post stored envelope SHA-256 and require equality, then inspect n8n
    execution metadata and require that neither ZPL nor base64 body content appears.
```

The script has a 12-minute total timeout, traps cleanup, restores prior service/workflow state, and prints only IDs, hashes, state names, and timings. It fails when any service restarts into legacy header mode.

`verify-remote-surface.sh` accepts a host DNS name and uses a three-second timeout:

```bash
HOST="${1:?Usage: verify-remote-surface.sh picking.warehouse.test}"
nc -z -w3 "$HOST" 443
for port in 80 8000 5432 5433 5678 8069 8100 9000 5500 11434; do
    if nc -z -w3 "$HOST" "$port"; then
        echo "unexpected open port: $port" >&2
        exit 1
    fi
done
```

The external firewall blocks 80; Caddy's port 80 redirect remains useful only on a controlled local/admin segment.

Write `docs/runbooks/foundation-rollout.md` with this exact order:

1. record integration commit and create immutable database/workflow backups;
2. run Odoo-19 fact gate and both module test tags;
3. run DB role `backup`, `apply`, `verify`; stop on any unexpected cross-connect;
4. deploy integration models with `DISPATCHER_ENABLED=false`;
5. run two-database and concurrency live tests;
6. provision native/HMAC credentials and verify metadata;
7. import v2 workflows inactive; run static verifier;
8. activate only Foundation smoke through `activate-test` and run
   signed/binary/replay tests, then require matching `deactivate-test`;
9. run kill/restart test;
10. merge and verify PWA login UI, Voice no-write assist, and Cluster reservation gates;
11. set `MOBILE_HEADER_GRACE_MODE=false`; verify startup;
12. set `DISPATCHER_ENABLED=true` for the smoke event only;
13. deploy production Caddy/Compose surface and run local/remote/TLS/mobile gates;
14. activate Visual Quality, then Shipping, one workflow at a time in their approved plans;
15. retain legacy v1 workflows only until each replacement's rollback window closes.

Rollback triggers and actions:

```text
DB isolation fails:
  stop apps; run DB role rollback; restore prior role names; verify health.

Session/PWA gate fails:
  keep strict production disabled; restore prior frontend; do not expose header grace publicly.

Signature or replay gate fails:
  deactivate v2 workflows; disable dispatcher; keep outbox rows pending; do not delete receipts.

Restart/duplicate-effect gate fails:
  disable dispatcher and provider workflow; preserve job/outbox/receipt records for review.

Network gate fails:
  restore prior Caddy/Compose version behind host firewall; do not open service ports as a workaround.
```

Create the program status entry using this fixed table:

```markdown
| Track | Branch | Worktree | Spec | Plan | Commit | Tests | Blocker | Integration |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Foundation | codex/foundation-platform-contracts-security | 01-foundation-platform-contracts-security | platform-security-event-contracts | platform-security-event-contracts-foundation | execution tag `foundation-plan-approved-2026-07-23` | implementation tests not started | execution not started | pending |
```

Replace the initial planning/test state with actual values in the integration
worktree on every task merge. Status updates never contain secrets or full binary
payloads.

- [ ] **Step 4: Run the complete serial Foundation gate**

Implement `run-foundation-live-gates.sh` with `set -Eeuo pipefail`. It owns the
run-ID environment and cleanup trap for its entire lifetime. Its setup is:

```bash
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
export COMPOSE_PROJECT_NAME="pwr-foundation-live-${RUN_ID}"
export COMPOSE_FILE="docker-compose.yml:docker-compose.dev.yml:infrastructure/docker-compose.db-migration.yml"
export PWR_DB_MIGRATION_VOLUME="pwr_foundation_live_pg_${RUN_ID}"
docker volume create "$PWR_DB_MIGRATION_VOLUME"
cleanup_foundation_live() {
  docker compose down --remove-orphans || true
  docker volume rm "$PWR_DB_MIGRATION_VOLUME" || true
}
trap cleanup_foundation_live EXIT

docker compose up -d db
until docker compose exec -T db pg_isready -U pwr_db_admin -d postgres; do
  sleep 1
done

for database in \
  masterfischer_o19_foundation_module_test \
  masterfischer_o19_foundation_a \
  masterfischer_o19_foundation_b
do
  docker compose exec -T db sh -ceu '
    export PGPASSWORD="$(cat "${PWR_DB_ADMIN_PASSWORD_FILE:?}")"
    printf "CREATE DATABASE \"%s\" OWNER odoo_app;\n" "$1" |
      psql -X -v ON_ERROR_STOP=1 -U pwr_db_admin -d postgres
    psql -X -v ON_ERROR_STOP=1 -U pwr_db_admin -d postgres -c \
      "REVOKE CONNECT, TEMPORARY ON DATABASE \"$1\" FROM PUBLIC"
    psql -X -v ON_ERROR_STOP=1 -U pwr_db_admin -d postgres -c \
      "GRANT CONNECT, TEMPORARY ON DATABASE \"$1\" TO odoo_app"
    psql -X -v ON_ERROR_STOP=1 -U pwr_db_admin -d "$1" <<SQL
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO odoo_app;
ALTER SCHEMA public OWNER TO odoo_app;
SQL
  ' sh "$database"
done

docker compose run --rm --no-deps odoo \
  --database masterfischer_o19_foundation_module_test \
  --db-filter '^masterfischer_o19_foundation_module_test$' \
  --workers=0 --max-cron-threads=0 --without-demo=all \
  --init picking_assistant_integration,picking_assistant_core \
  --test-tags '/picking_assistant_integration,/picking_assistant_core' \
  --stop-after-init

for database in \
  masterfischer_o19_foundation_a \
  masterfischer_o19_foundation_b
do
  docker compose run --rm --no-deps odoo \
    --database "$database" \
    --db-filter "^${database}$" \
    --workers=0 --max-cron-threads=0 --without-demo=all \
    --init picking_assistant_integration,picking_assistant_core \
    --stop-after-init
done

install -d -m 0700 .artifacts
rm -f .artifacts/foundation-seed-*.json .artifacts/foundation-seed-*.log
umask 077
export PWR_TEST_SERVICE_PASSWORD="$(
  tr -d '\r\n' < secrets/pwr_test_service_password
)"
seed_json_files=()
for pair in \
  'o19-a:masterfischer_o19_foundation_a' \
  'o19-b:masterfischer_o19_foundation_b'
do
  instance="${pair%%:*}"
  database="${pair#*:}"
  seed_log="$(mktemp ".artifacts/foundation-seed-${instance}.XXXXXX.log")"
  seed_json="$(mktemp ".artifacts/foundation-seed-${instance}.XXXXXX.json")"
  docker compose run -T --rm --no-deps \
    -e PWR_SEED_INSTANCE="$instance" \
    -e PWR_TEST_SERVICE_PASSWORD \
    odoo shell -d "$database" \
    < infrastructure/scripts/seed-foundation-live-test.py \
    > "$seed_log"
  test "$(grep -c '^PWR_SEED_METADATA=' "$seed_log")" = 1
  sed -n 's/^PWR_SEED_METADATA=//p' "$seed_log" > "$seed_json"
  python3 - "$seed_json" "$instance" <<'PY'
import json
import sys
from pathlib import Path

item = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert set(item) == {"instance", "twenty_event_ids", "restart_event"}
assert item["instance"]["name"] == sys.argv[2]
PY
  seed_json_files+=("$seed_json")
done

python3 - "${seed_json_files[@]}" \
  .artifacts/foundation-seed-metadata.json <<'PY'
import json
import os
import sys
from pathlib import Path

inputs = [json.loads(Path(name).read_text(encoding="utf-8")) for name in sys.argv[1:-1]]
instances = {item["instance"]["name"]: item["instance"] for item in inputs}
source = next(item for item in inputs if item["instance"]["name"] == "o19-a")
data = {
    "instances": instances,
    "twenty_event_ids": source["twenty_event_ids"],
    "restart_event": source["restart_event"],
}
assert set(instances) == {"o19-a", "o19-b"}
assert len(data["twenty_event_ids"]) == 20
assert data["restart_event"]["artifact_probe"] is True
output = Path(sys.argv[-1])
temporary = output.with_suffix(".tmp")
temporary.write_text(
    json.dumps(data, sort_keys=True, separators=(",", ":")),
    encoding="utf-8",
)
os.chmod(temporary, 0o600)
temporary.replace(output)
PY
rm -f "${seed_json_files[@]}" .artifacts/foundation-seed-*.log
test "$(stat -c '%a' .artifacts/foundation-seed-metadata.json)" = 600

export ODOO_INSTANCES_JSON="$(
  python3 - <<'PY'
import json
import os

password = os.environ["PWR_TEST_SERVICE_PASSWORD"]
profiles = {
    "o19-a": {
        "display_name": "Foundation A",
        "url": "http://odoo:8069",
        "db": "masterfischer_o19_foundation_a",
        "user": "pwr_test_service",
        "password": password,
    },
    "o19-b": {
        "display_name": "Foundation B",
        "url": "http://odoo:8069",
        "db": "masterfischer_o19_foundation_b",
        "user": "pwr_test_service",
        "password": password,
    },
}
print(json.dumps(profiles, sort_keys=True, separators=(",", ":")))
PY
)"
unset PWR_TEST_SERVICE_PASSWORD
test "$(
  python3 - <<'PY'
import json
import os
print(",".join(sorted(json.loads(os.environ["ODOO_INSTANCES_JSON"]))))
PY
)" = "o19-a,o19-b"

docker compose up -d odoo backend n8n pwa caddy

wait_http() {
  name="$1"
  shift
  for _attempt in $(seq 1 120); do
    if "$@" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "$name did not become ready" >&2
  return 1
}
wait_http odoo curl --fail http://127.0.0.1:8069/web/login
wait_http backend curl --fail http://127.0.0.1:8000/api/health/live
wait_http n8n curl --fail http://127.0.0.1:5678/healthz
wait_http caddy curl --fail \
  --cacert infrastructure/certs/cert.pem \
  --resolve picking.warehouse.test:443:127.0.0.1 \
  https://picking.warehouse.test/api/health/live

python3 - <<'PY'
import json
from urllib.request import urlopen

with urlopen("http://127.0.0.1:8000/api/auth/instances", timeout=3) as response:
    instances = json.load(response)
assert {item["name"] for item in instances} == {"o19-a", "o19-b"}
PY

bash infrastructure/scripts/provision-n8n-credentials.sh provision
bash infrastructure/scripts/provision-n8n-credentials.sh verify
```

Expected before tests: this run-ID project owns a newly initialized external DB
volume; `init-db-roles.sh` created the three roles and the n8n database;
`pwr_db_admin` alone created the three fixed Foundation databases; Odoo initialized
and seeded them while connected as `odoo_app`; and the backend runtime contains
explicit `o19-a`/`o19-b` profiles backed by the protected test-service credential.
The source/developer DB volume is not mounted by any project container. The script
validates host-owned seed metadata, waits for all five services, provisions the
three required credentials into the fresh n8n store, and verifies them before any
workflow import. The cleanup trap must succeed before the gate can be recorded
PASS.

The same script then runs, without spawning an unmonitored background shell:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests -q \
  --ignore=tests/live

ODOO19_LIVE_URL=http://127.0.0.1:8069 \
ODOO19_LIVE_DB_A=masterfischer_o19_foundation_a \
ODOO19_LIVE_DB_B=masterfischer_o19_foundation_b \
ODOO19_LIVE_USER=pwr_test_service \
ODOO19_LIVE_PASSWORD_FILE=../secrets/pwr_test_service_password \
FOUNDATION_API_URL=http://127.0.0.1:8000 \
FOUNDATION_CA_FILE=../infrastructure/certs/cert.pem \
FOUNDATION_N2B_KEY_ID="$PWR_N8N_TO_BACKEND_ACTIVE_KEY_ID" \
FOUNDATION_N2B_SECRET_FILE=../secrets/pwr_n8n_to_backend_active_hmac \
FOUNDATION_SEED_METADATA=../.artifacts/foundation-seed-metadata.json \
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio \
  -m "odoo19_live or foundation_live" tests/live -q

cd ..
node --test pwa/js/tests/*.test.mjs
(cd n8n/custom-nodes/n8n-nodes-pwr && npm ci && npm test)
node --test n8n/tests/*.test.mjs
PYTHONPATH=. python3 -m pytest infrastructure/tests -q
python3 infrastructure/scripts/verify-workflows.py
bash infrastructure/scripts/test-pwr-n8n-signing.sh
bash infrastructure/scripts/test-foundation-restart.sh
bash infrastructure/scripts/verify-db-role-isolation.sh
bash infrastructure/scripts/verify-production-gates.sh
ssh -o BatchMode=yes -o ConnectTimeout=5 "$FOUNDATION_REMOTE_PROBE_SSH" \
  bash -s -- picking.warehouse.test \
  < infrastructure/scripts/verify-remote-surface.sh
```

Run the orchestrator:

```bash
bash -n infrastructure/scripts/run-foundation-live-gates.sh
bash infrastructure/scripts/run-foundation-live-gates.sh
```

`FOUNDATION_REMOTE_PROBE_SSH` is required and names a key-authenticated second
warehouse host. Streaming the versioned script over stdin avoids assuming a repo
checkout there. The orchestrator captures its exact output before cleanup and fails
if SSH, port 443, or any negative port probe fails.

Expected:

```text
Backend unit/contract: PASS, no skipped security tests
Odoo 19 module tests: 0 failed
Two-database routing: PASS
Real concurrency: PASS
PWA API: PASS
Custom n8n nodes: PASS
n8n workflow tests/verifier: PASS
Signed live smoke: PASS, credential-backed synthetic ZPL upload
Kill/restart: PASS, one business effect and one artifact
DB role isolation: PASS
Production and remote surface: PASS, only warehouse TCP 443 reachable
Physical iOS/Android CA trust and HTTPS reachability: recorded PASS
PWA login/camera/mic/install workflow: recorded as pending the named PWA integration gate
```

Before reporting completion, invoke `superpowers:verification-before-completion`, inspect the exact fresh outputs, and compare the integration diff with both approved specs.

- [ ] **Step 5: Commit live gates and merge through the integrator**

```bash
git add \
  .gitignore \
  backend/pytest.ini \
  backend/tests/live \
  infrastructure/scripts/seed-foundation-live-test.py \
  infrastructure/scripts/run-foundation-live-gates.sh \
  infrastructure/scripts/test-foundation-restart.sh \
  infrastructure/scripts/verify-remote-surface.sh \
  docs/runbooks/foundation-rollout.md
git commit -m "test(platform): add live isolation and restart gates"

cd "/mnt/c/Users/endri/Desktop/Bachelor-worktrees/00-integration-bachelor-hardening"
git merge --no-ff codex/foundation-platform-contracts-security \
  -m "merge: add platform security and event foundation"
```

Expected: the Foundation merge is performed after task review, exact-path diff
review, secret scan, and every Foundation serial gate. It lands with
`DISPATCHER_ENABLED=false` and no production activation. The integrator records the
merge commit and rollback point, plus explicit pending blockers for the PWA login
flow, Voice no-write command gate, Cluster scoped reservations, and later
feature-specific mobile checks. Those blockers are closed in their own approved
plans before the runbook enables strict production.

## Spec Coverage Matrix

| Approved spec section | Implemented by |
| --- | --- |
| Goals, trust boundaries, Odoo as system of record | Global Constraints, Tasks 8-10 |
| Picker session, cookie, principal, roles, revalidation | Tasks 1, 5-7 |
| CSRF, Origin, CORS, login throttle, trusted proxy | Tasks 1, 5-7, 16 |
| Odoo instance binding and no local fallback | Tasks 6, 7, 10, 17 |
| Event envelope v2 and first event names | Task 2 |
| HMAC canonicalization, rotation, query binding, replay | Tasks 2, 4, 8, 10, 14 |
| Callback envelope, heartbeat, lease, retry semantics | Tasks 2, 8, 10 |
| Job state machine and seven Odoo models | Tasks 5 and 8 |
| Persistent outbox, backoff, dead letter, watchdog | Tasks 8 and 9 |
| Browser/domain idempotency and Core migration | Tasks 7, 12, 16 |
| Media and artifact paths, formats, retention | Tasks 8 and 11 |
| Edge/Core/Automation networks and public surface | Tasks 13, 15, 16 |
| Dedicated n8n database role and existing-volume rollback | Task 13 |
| Workflow registry, custom nodes, credentials, importer, verifier | Tasks 3, 4, 14, 15 |
| Odoo-19-only rollout and v1 compatibility | Global Constraints, Tasks 12, 15-17 |
| Auth, HMAC, instance, outbox, callback, network, live binary tests | Tasks 1-17, especially Task 17 |

## Completion Boundary

This plan delivers and verifies the shared Foundation. It does not choose a vision model, carrier, Voice v2 model, label layout, or PWA visual design. Production strict mode remains closed until the separately approved PWA, Voice, and Cluster plans deliver the three Task 16 handoff gates; Visual Quality and Shipping then consume the frozen v2 contracts without editing Foundation-owned files.
