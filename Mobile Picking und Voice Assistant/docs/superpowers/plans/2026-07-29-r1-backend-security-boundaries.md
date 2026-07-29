# R1 — Backend Security Boundaries Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three backend defects that let a misconfigured runtime profile disable every production guard, that break the five legacy n8n callbacks in production, and that let a PDF smuggle an unbounded raster image past the binary validator.

**Architecture:** Three independent changes inside `backend/`. Task 1 turns the runtime profile into a closed enum, collapses two competing origin settings into one, caps the signature window against the nonce retention, and flips the grace-mode default to off. Task 2 gives the service-to-service callbacks their own non-browser dependency. Task 3 extends PDF validation to inline images and replaces the Odoo-side byte denylist with a refusal to accept binaries that did not pass the backend validator.

**Tech Stack:** Python 3, FastAPI, pydantic-settings v2, pytest, pypdf.

## Global Constraints

- Test command: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q`
- The repo's Python interpreter is `python`, not `python3`. pytest is vendored gitignored at `backend/.deps` and does not exist inside git worktrees; from a worktree use `PYTHONPATH="<main-tree>/Mobile Picking und Voice Assistant/backend/.deps"`.
- `backend/app/main.py` is entirely CRLF. Added lines must keep that convention; `git diff --check` will flag every added line otherwise and those warnings are expected noise, not defects.
- Edits to `backend/app/dependencies.py` and `backend/app/main.py` must be **strictly additive where possible** — append blocks, do not reorder, do not reformat, do not tidy imports. R2 also touches `auth_sessions.py`.
- TDD is mandatory: every task writes a failing test first and proves it fails before implementing.
- Never log a header value, a token, a secret, or a credential.
- The baseline on the merged tree is **543 passing backend tests**. A task that ends with fewer passing tests than it started with has broken something.

---

### Task 1: Close the runtime configuration

Finding #1 (Critical), #2a (Critical), M3 (Minor). `runtime_profile` is a bare `str`, so
`validate_runtime_security` returns early for `"prod"`, `"Production"`, `""` and every other typo,
silently selecting the full development posture. `mobile_header_grace_mode` defaults to `True`.
`main.py` configures CORS from `cors_origins`, which nothing validates, while
`validate_runtime_security` validates the separate `pwa_origins`.

**Files:**
- Modify: `backend/app/config.py` (Settings fields, new `reject_removed_env_vars`, new model validator)
- Modify: `backend/app/main.py:101-107` (CORS middleware origin source)
- Modify: `backend/app/dependencies.py:154-160` (`_grace_mode_active`)
- Test: `backend/tests/test_runtime_profile_config.py` (create)

**Interfaces:**
- Consumes: `Settings`, `validate_runtime_security(candidate: Settings) -> None`, `parse_origins(value: str) -> tuple[str, ...]`, `get_instance_registry(candidate: Settings | None = None)` — all existing in `backend/app/config.py`.
- Produces: `reject_removed_env_vars(environ: Mapping[str, str]) -> None` raising `ValueError`; `Settings.runtime_profile: Literal["development", "test", "production"]`; the module constant `ODOO_NONCE_RETENTION_SECONDS = 900`. `Settings.cors_origins` is **removed** — any other module referencing it must be updated in this task.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_runtime_profile_config.py`:

```python
"""Runtime-profile and origin configuration must fail closed.

Regression cover for whole-branch review findings #1 and #2a: a typo in
RUNTIME_PROFILE used to select the full development posture silently, and CORS
was configured from a setting that nothing validated.
"""

import base64

import pytest
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware

from app.config import (
    ODOO_NONCE_RETENTION_SECONDS,
    Settings,
    parse_origins,
    reject_removed_env_vars,
    validate_runtime_security,
)

PROD_INSTANCES = (
    '{"o19-a": {"url": "https://o19-a:8069", "db": "o19-a-db", "api_key": "key-a"}}'
)


def _b64_secret() -> str:
    return base64.b64encode(b"0" * 32).decode("ascii")


@pytest.mark.parametrize(
    "value",
    ["prod", "Production", "PRODUCTION", " production", "production ", "", "dev", "prd"],
)
def test_unknown_runtime_profile_is_rejected_at_construction(value):
    with pytest.raises(ValidationError):
        Settings(runtime_profile=value)


@pytest.mark.parametrize("value", ["development", "test", "production"])
def test_known_runtime_profiles_are_accepted(value):
    assert Settings(runtime_profile=value).runtime_profile == value


def test_grace_mode_is_off_by_default():
    assert Settings().mobile_header_grace_mode is False


def test_hmac_skew_above_300_seconds_is_rejected():
    with pytest.raises(ValidationError):
        Settings(pwr_hmac_max_skew_seconds=301)


def test_role_revalidation_above_300_seconds_is_rejected():
    with pytest.raises(ValidationError):
        Settings(session_role_revalidate_seconds=301)


def test_nonce_ttl_must_exceed_the_signature_acceptance_window():
    # The window is +/- skew, so 2 * skew wide. A nonce that is forgotten
    # before the window closes is a replay that no store can catch.
    with pytest.raises(ValidationError):
        Settings(pwr_hmac_max_skew_seconds=300, pwr_nonce_ttl_seconds=599)


def test_nonce_ttl_may_not_exceed_the_odoo_retention():
    # Odoo retains nonces for ODOO_NONCE_RETENTION_SECONDS. Configuring the
    # backend to expect longer memory than Odoo actually has is a lie.
    with pytest.raises(ValidationError):
        Settings(pwr_nonce_ttl_seconds=ODOO_NONCE_RETENTION_SECONDS + 1)


def test_removed_cors_origins_env_var_fails_closed():
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        reject_removed_env_vars({"CORS_ORIGINS": "*"})


def test_reject_removed_env_vars_passes_a_clean_environment():
    reject_removed_env_vars({"PWA_ORIGINS": "https://pwa.example.com"})


def test_settings_no_longer_carries_a_second_origin_field():
    assert "cors_origins" not in Settings.model_fields


def test_production_rejects_wildcard_pwa_origins():
    candidate = Settings(
        runtime_profile="production",
        pwa_origins="*",
        odoo_instances_json=PROD_INSTANCES,
        n8n_webhook_secret="w" * 32,
        n8n_callback_secret="c" * 32,
        session_throttle_hmac_secret_b64=_b64_secret(),
        pwr_backend_to_n8n_active_secret_b64=_b64_secret(),
        pwr_n8n_to_backend_active_secret_b64=_b64_secret(),
        pwr_backend_to_n8n_active_key_id="k1",
        pwr_n8n_to_backend_active_key_id="k2",
    )
    with pytest.raises(ValueError, match="Wildcard"):
        validate_runtime_security(candidate)


def test_cors_middleware_uses_the_single_validated_origin_list():
    from app.config import settings
    from app.main import app

    cors = [entry for entry in app.user_middleware if entry.cls is CORSMiddleware]
    assert len(cors) == 1, "exactly one CORS middleware is expected"
    assert tuple(cors[0].kwargs["allow_origins"]) == parse_origins(settings.pwa_origins)


def test_grace_mode_is_inactive_outside_development(monkeypatch):
    from app import dependencies

    monkeypatch.setattr(dependencies.settings, "runtime_profile", "test")
    monkeypatch.setattr(dependencies.settings, "mobile_header_grace_mode", True)
    assert dependencies._grace_mode_active() is False


def test_grace_mode_still_works_in_development_when_explicitly_enabled(monkeypatch):
    from app import dependencies

    monkeypatch.setattr(dependencies.settings, "runtime_profile", "development")
    monkeypatch.setattr(dependencies.settings, "mobile_header_grace_mode", True)
    assert dependencies._grace_mode_active() is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/test_runtime_profile_config.py -q`
Expected: collection error — `ImportError: cannot import name 'ODOO_NONCE_RETENTION_SECONDS'` and `'reject_removed_env_vars'` from `app.config`.

- [ ] **Step 3: Make the runtime profile a closed enum and cap the windows**

In `backend/app/config.py`, extend the imports at the top of the file:

```python
import os
from collections.abc import Mapping
from typing import Literal

from pydantic import Field, model_validator
```

Add above the `Settings` class:

```python
# Odoo retains request nonces for 900 seconds (see the addon's nonce model).
# The backend must never be configured to expect a longer memory than Odoo has,
# and its signature acceptance window must close well inside that retention.
ODOO_NONCE_RETENTION_SECONDS = 900

# Settings that were removed rather than renamed. `extra="ignore"` would let a
# stale value sit in .env looking effective while doing nothing, so refuse to
# start instead of silently ignoring it.
_REMOVED_ENV_VARS = ("CORS_ORIGINS",)


def reject_removed_env_vars(environ: Mapping[str, str]) -> None:
    for name in _REMOVED_ENV_VARS:
        if name in environ:
            raise ValueError(
                f"{name} was removed. Configure PWA_ORIGINS instead; it is the "
                "single origin list and it is validated in production."
            )
```

Inside `Settings`, replace the `cors_origins` field (delete the line entirely) and change these
four fields:

```python
    runtime_profile: Literal["development", "test", "production"] = "development"
    mobile_header_grace_mode: bool = False
    session_role_revalidate_seconds: int = Field(default=300, ge=1, le=300)
    pwr_hmac_max_skew_seconds: int = Field(default=300, ge=1, le=300)
```

Add this validator as the last member of the `Settings` class body:

```python
    @model_validator(mode="after")
    def _check_replay_window(self) -> "Settings":
        window = 2 * self.pwr_hmac_max_skew_seconds
        if self.pwr_nonce_ttl_seconds <= window:
            raise ValueError(
                "PWR_NONCE_TTL_SECONDS must exceed the signature acceptance "
                f"window of {window}s (2 x PWR_HMAC_MAX_SKEW_SECONDS)"
            )
        if self.pwr_nonce_ttl_seconds > ODOO_NONCE_RETENTION_SECONDS:
            raise ValueError(
                "PWR_NONCE_TTL_SECONDS must not exceed the Odoo nonce retention "
                f"of {ODOO_NONCE_RETENTION_SECONDS}s"
            )
        return self
```

Immediately before the existing module-level `settings = Settings()` instantiation, add:

```python
reject_removed_env_vars(os.environ)
```

- [ ] **Step 4: Point CORS at the single validated origin list**

In `backend/app/main.py:101-107`, change only the `allow_origins` argument:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(parse_origins(settings.pwa_origins)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Add `parse_origins` to the existing `from app.config import ...` line in that file. Do not
reorder the other imports.

- [ ] **Step 5: Restrict grace mode to development**

In `backend/app/dependencies.py:160`, change the return expression and the docstring's first
sentence:

```python
def _grace_mode_active() -> bool:
    """Grace-Mode ist nur im Profil `development` UND nur mit dem expliziten
    Feature-Flag aktiv. `validate_runtime_security` verbietet das Flag in
    production zusaetzlich fail-closed -- diese Funktion ist die zweite,
    redundante Absicherung direkt an der Nutzungsstelle. `test` und jedes
    kuenftige Profil zaehlen bewusst NICHT als development.
    """
    return settings.runtime_profile == "development" and settings.mobile_header_grace_mode
```

- [ ] **Step 6: Find and fix every remaining reference to the removed setting**

Run: `cd backend && grep -rn "cors_origins\|CORS_ORIGINS" app/ tests/ ../infrastructure ../pwa ../.env.example 2>/dev/null`
Update every hit. `.env.example` must document `PWA_ORIGINS` instead. If `.env.example` does not
exist, skip it — do not create one, and do not touch `.env`.

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/test_runtime_profile_config.py -q`
Expected: PASS, 14 tests.

- [ ] **Step 8: Run the whole suite and repair the fallout**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q`
Expected: every test passes. Existing tests that relied on grace mode being on by default must now
enable it explicitly — that is a correct test change, not a workaround. Any test that constructs
`Settings(cors_origins=...)` must be moved to `pwa_origins`.

- [ ] **Step 9: Commit**

```bash
git add backend/app/config.py backend/app/main.py backend/app/dependencies.py backend/tests/test_runtime_profile_config.py
git commit -m "fix(config): close the runtime profile, origin and replay-window gaps"
```

---

### Task 2: Give the legacy n8n callbacks a service dependency

Finding #8 (Important). All five legacy callbacks resolve `MobileWorkflowService` through
`get_mobile_workflow_service`, which depends on `get_request_odoo_client_or_grace`. Those routes
are authorised by `require_n8n_callback_secret` and never carry a browser cookie, so in production
that dependency raises 401 before the handler runs. In development it lets `X-Odoo-Instance`
redirect idempotency bookkeeping to another instance while the business write stays on `local`.
`get_odoo_client`'s own docstring already states the intent: "Lokale/Default-Instanz. Genutzt von
n8n-Callbacks (bewusst immer local)."

**Files:**
- Modify: `backend/app/dependencies.py` (append one dependency below `get_mobile_workflow_service`)
- Modify: `backend/app/routers/n8n_internal.py:413, 553, 694, 864, 1019`
- Test: `backend/tests/test_legacy_callback_dependency.py` (create)

**Interfaces:**
- Consumes: `get_odoo_client() -> OdooClient` (`dependencies.py:57`), `MobileWorkflowService`, `require_n8n_callback_secret`.
- Produces: `get_legacy_n8n_workflow_service(odoo: OdooClient = Depends(get_odoo_client)) -> MobileWorkflowService`. `get_mobile_workflow_service` stays in place for any browser-facing caller.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_legacy_callback_dependency.py`:

```python
"""The five legacy n8n callbacks are service-to-service routes.

Regression cover for whole-branch review finding #8. These routes are
authorised by the shared callback secret and never see a browser cookie, so
they must not resolve their workflow service through the browser/grace
dependency: that returns 401 in production before the handler is reached.
"""

import pytest
from fastapi import Depends

from app.dependencies import (
    get_legacy_n8n_workflow_service,
    get_mobile_workflow_service,
    get_odoo_client,
    get_request_odoo_client_or_grace,
)
from app.routers import n8n_internal

LEGACY_CALLBACK_PATHS = {
    "/n8n/quality-assessment",
    "/n8n/replenishment-action",
    "/n8n/quality-assessment-failed",
    "/n8n/manual-review-activity",
}


def _dependency_names(route):
    return {
        dependency.call
        for dependency in route.dependant.dependencies
    }


def _flattened_calls(dependant):
    calls = set()
    for sub in dependant.dependencies:
        calls.add(sub.call)
        calls |= _flattened_calls(sub)
    return calls


def test_legacy_service_dependency_uses_the_local_client():
    signature_default = get_legacy_n8n_workflow_service.__defaults__
    assert signature_default is not None
    dependency = signature_default[0]
    assert dependency.dependency is get_odoo_client


def test_no_legacy_callback_route_depends_on_the_grace_client():
    offenders = []
    for route in n8n_internal.router.routes:
        path = getattr(route, "path", "")
        if not any(path.endswith(suffix.split("/")[-1]) for suffix in LEGACY_CALLBACK_PATHS):
            continue
        calls = _flattened_calls(route.dependant)
        if get_request_odoo_client_or_grace in calls or get_mobile_workflow_service in calls:
            offenders.append(path)
    assert offenders == [], (
        f"legacy service routes still resolve through the browser/grace client: {offenders}"
    )


def test_legacy_callback_routes_still_require_the_callback_secret():
    from app.dependencies import require_n8n_callback_secret

    checked = 0
    for route in n8n_internal.router.routes:
        path = getattr(route, "path", "")
        if not any(path.endswith(suffix.split("/")[-1]) for suffix in LEGACY_CALLBACK_PATHS):
            continue
        checked += 1
        assert require_n8n_callback_secret in _flattened_calls(route.dependant), path
    assert checked == len(LEGACY_CALLBACK_PATHS)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/test_legacy_callback_dependency.py -q`
Expected: collection error — `ImportError: cannot import name 'get_legacy_n8n_workflow_service'`.

- [ ] **Step 3: Add the service dependency**

Append to `backend/app/dependencies.py`, directly below the existing
`get_mobile_workflow_service`:

```python
def get_legacy_n8n_workflow_service(
    odoo: OdooClient = Depends(get_odoo_client),
) -> MobileWorkflowService:
    """Workflow-Service fuer die fuenf Legacy-n8n-Callbacks (Service-zu-Service).

    Diese Routen sind ueber `require_n8n_callback_secret` autorisiert und sehen
    NIE einen Browser-Cookie. Sie duerfen deshalb nicht ueber
    `get_request_odoo_client_or_grace` laufen: der wirft in production 401,
    bevor der Handler ueberhaupt erreicht wird, und liesse im Development
    `X-Odoo-Instance` die Idempotenz-Buchfuehrung auf eine andere Instanz
    umlenken, waehrend der Business-Write ueber `get_odoo_client` fest auf
    `local` schreibt. Beide Haelften benutzen jetzt denselben Client.
    """
    return MobileWorkflowService(odoo)
```

- [ ] **Step 4: Rewire the five callback routes**

In `backend/app/routers/n8n_internal.py`, change the workflow parameter default on the handlers at
lines 413, 553, 694, 864 and 1019 from
`Depends(get_mobile_workflow_service)` to `Depends(get_legacy_n8n_workflow_service)`, and add
`get_legacy_n8n_workflow_service` to the existing `from app.dependencies import (...)` block at
line 14. Change nothing else in those handlers.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/test_legacy_callback_dependency.py -q`
Expected: PASS, 3 tests.

- [ ] **Step 6: Fix the positive tests that override the wrong seam**

Run: `cd backend && grep -n "get_mobile_workflow_service" tests/test_n8n_internal_routes.py`

Every positive test that overrode `get_mobile_workflow_service` was bypassing the real dependency
graph, which is why finding #8 survived. Change those overrides to replace **`get_odoo_client`**
with the fake Odoo client instead, so the real `MobileWorkflowService` is constructed by the real
dependency. Where a test genuinely needs a service double, override
`get_legacy_n8n_workflow_service` and add a comment naming what that test is *not* covering.

- [ ] **Step 7: Run the whole suite**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q`
Expected: every test passes.

- [ ] **Step 8: Commit**

```bash
git add backend/app/dependencies.py backend/app/routers/n8n_internal.py backend/tests/test_legacy_callback_dependency.py backend/tests/test_n8n_internal_routes.py
git commit -m "fix(n8n): resolve legacy callbacks through a service-authorized workflow service"
```

---

### Task 3: Close the binary validation boundary

Findings #9a and #9b (Important). `_consume_stream_budget` inspects `/Filter` on stream *objects*
only. An inline image inside a content stream (`BI ... ID <data> EI`) carries its own abbreviated
filter and dimension keys and never becomes a stream object, so a 586-byte PDF declaring
`/F /DCT` at 65535 x 65535 passes. Separately, `resources.py:469` guards the Odoo write path with
`PDF_ACTIVE_MARKERS`, a raw byte denylist that `/J#61vaScript` defeats, because PDF name objects
allow `#xx` hex escapes that the parser resolves and a byte search does not.

**Files:**
- Modify: `backend/app/services/binary_validation.py` (add inline-image rejection)
- Modify: `odoo/addons/picking_assistant_integration/models/resources.py` (replace the denylist with an attestation requirement)
- Test: `backend/tests/test_binary_validation.py` (extend)
- Test: `odoo/addons/picking_assistant_integration/tests/test_resources.py` (extend)

**Interfaces:**
- Consumes: `BinaryValidationError`, `_consume_stream_budget(node, remaining) -> int` — both existing in `backend/app/services/binary_validation.py`.
- Produces: `_reject_inline_images(content: bytes) -> None` raising `BinaryValidationError`. Odoo side: `PDF_ACTIVE_MARKERS` is **removed**; the validated-content gate is whatever `_bind_job_media` already enforces.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_binary_validation.py`:

```python
def _pdf_with_inline_image(filter_abbreviation: bytes) -> bytes:
    """Smallest PDF carrying an inline image inside a content stream.

    Inline images never become stream objects, so the object-graph filter and
    expansion budget never sees them. Regression cover for finding #9a.
    """
    content = (
        b"q\n"
        b"BI /W 65535 /H 65535 /CS /RGB /BPC 8 /F " + filter_abbreviation + b"\n"
        b"ID \xff\xd8\xff\xe0 EI\n"
        b"Q\n"
    )
    objects = [
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n",
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 10 10]/Contents 4 0 R>>endobj\n",
        b"4 0 obj<</Length " + str(len(content)).encode("ascii") + b">>stream\n"
        + content
        + b"\nendstream endobj\n",
    ]
    body = b"%PDF-1.7\n" + b"".join(objects)
    return body + b"trailer<</Root 1 0 R/Size 5>>\n%%EOF\n"


@pytest.mark.parametrize("abbreviation", [b"/DCT", b"/CCF", b"/AHx", b"/A85", b"/RL", b"/LZW"])
def test_inline_images_are_rejected_regardless_of_filter(abbreviation):
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf_bytes(_pdf_with_inline_image(abbreviation))


def test_inline_image_without_a_filter_is_also_rejected():
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf_bytes(_pdf_with_inline_image(b"/Fl"))


def test_the_letters_bi_inside_ordinary_text_do_not_trip_the_check():
    # "BI" must be recognised as an operator, not as a substring: a delivery
    # note containing the word "KABINE" is not an inline image.
    ordinary = _minimal_valid_pdf(text=b"KABINE BID BIG")
    validate_pdf_bytes(ordinary)
```

`validate_pdf_bytes` and `_minimal_valid_pdf` already exist in that test module; if the public
entry point is named differently, use the name the module already imports and keep the assertions
identical. Add `import pytest` only if it is not already imported.

Append to `odoo/addons/picking_assistant_integration/tests/test_resources.py`:

```python
    def test_hex_escaped_javascript_name_is_not_a_security_boundary(self):
        """A byte denylist cannot see /J#61vaScript, which the PDF parser reads
        as /JavaScript. Regression cover for finding #9b: the Odoo edge must
        refuse unattested binaries outright rather than pattern-match them."""
        payload = (
            b"%PDF-1.7\n1 0 obj<</Type/Catalog/OpenAction<</S/J#61vaScript"
            b"/JS(app.alert\\(1\\))>>>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
        )
        with self.assertRaises(ValidationError):
            self._store_artifact_bytes(payload, mimetype="application/pdf")

    def test_pdf_active_marker_denylist_is_gone(self):
        from odoo.addons.picking_assistant_integration.models import resources

        self.assertFalse(
            hasattr(resources, "PDF_ACTIVE_MARKERS"),
            "the raw byte denylist must not survive as an apparent boundary",
        )
```

`_store_artifact_bytes` is the helper that module already uses to reach the artifact write path;
reuse its existing name and signature rather than adding a new one.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/test_binary_validation.py -q`
Expected: FAIL — the inline-image PDFs are accepted, so `pytest.raises` reports
`DID NOT RAISE BinaryValidationError`.

- [ ] **Step 3: Reject inline images in the backend validator**

Add to `backend/app/services/binary_validation.py`:

```python
# Inline images live inside a content stream (BI ... ID <data> EI) and never
# become stream objects, so the object-graph filter and expansion budget never
# sees them. Under the current policy -- a filter is permitted only when its
# expansion can be bounded -- they are refused outright. Re-enabling them means
# decoding the content stream and checking INTRINSIC dimensions; it must never
# mean trusting the declared /W and /H.
_INLINE_IMAGE_OPERATOR = re.compile(rb"(?:^|[\s\]>)])BI[\s/\[<]")


def _reject_inline_images(content: bytes) -> None:
    if _INLINE_IMAGE_OPERATOR.search(content):
        raise BinaryValidationError(
            "PDF contains an inline image; artifact PDFs must use bounded "
            "FlateDecode stream objects"
        )
```

Add `import re` to the module imports if it is not already present.

Call it from the PDF entry point **before** any parsing, next to the existing cheap checks — it
must run in the bounded-cheap-checks phase, ahead of nonce reservation and ahead of the expensive
parse, so it cannot be used to burn nonces or CPU:

```python
    _reject_inline_images(content)
```

Every decoded content stream must be checked too, not only the raw file, because a content stream
may itself be Flate-compressed. Immediately after a content stream is inflated inside
`_consume_stream_budget`'s caller, pass the produced bytes through `_reject_inline_images` as
well. The raw-bytes check alone is the sibling-gap this finding is about.

- [ ] **Step 4: Replace the Odoo denylist with an attestation requirement**

In `odoo/addons/picking_assistant_integration/models/resources.py`, delete the
`PDF_ACTIVE_MARKERS` tuple and every use of it. A raw byte denylist must not remain in place
looking like a boundary.

The Odoo edge keeps only checks that are genuinely cheap and total: the `%PDF-` version prefix
allowlist and the size cap. Everything structural is the backend validator's job, and the Odoo
write path must therefore refuse any binary that did not come through it. Add to the guarded
binding path:

```python
    def _require_backend_attestation(self, job, generation, sha256_hex, mimetype, size):
        """Der Odoo-Rand parst kein PDF. Er verlangt stattdessen, dass genau
        diese Bytes den Backend-Validator passiert haben: Job, Generation,
        SHA-256, MIME-Typ und Groesse muessen mit der zuvor gebundenen
        Attestierung uebereinstimmen. Eine Byte-Denylist waere hier keine
        Grenze -- /J#61vaScript liest der Parser als /JavaScript, die Suche
        nach rohen Bytes sieht das nicht.
        """
```

Implement it against the record that `_bind_job_media` already writes, and call it from every
artifact write path. If no attestation record exists yet, the alternative sanctioned by decision
§3 of `docs/superpowers/parallel/2026-07-23-program-status.md` is to make direct Odoo artifact
storage technically impossible instead — i.e. the artifact bytes may only ever arrive through the
guarded backend path. Choose one, and record which in the commit message.

- [ ] **Step 5: Run both suites to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/test_binary_validation.py -q`
Expected: PASS.

Odoo. **`docker compose exec odoo` is WRONG** — that container is Odoo 18 and mounts `odoo/addons18`. The service mounting `odoo/addons` sits behind the `odoo19-trial` profile:
```bash
docker compose --profile odoo19-trial run --rm --no-deps -T odoo19-trial \
  odoo --no-http --test-enable --stop-after-init \
  --workers=0 --max-cron-threads=0 \
  -d masterfischer_o19_foundation_test -u picking_assistant_integration
```
Expected: 0 failures. This step contends with lane R2 for the Odoo container — coordinate before running it.

- [ ] **Step 6: Run the whole backend suite**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q`
Expected: every test passes.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/binary_validation.py backend/tests/test_binary_validation.py odoo/addons/picking_assistant_integration/models/resources.py odoo/addons/picking_assistant_integration/tests/test_resources.py
git commit -m "fix(media): reject PDF inline images and drop the Odoo byte denylist"
```

---

## Lane exit gate

Before this lane is offered for review:

- [ ] `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q` — all green, count >= 543 + the new tests
- [ ] The Odoo addon suite is green (Task 3 touches it)
- [ ] `grep -rn "cors_origins" backend/ infrastructure/ pwa/` returns nothing
- [ ] Adversarial review: `codex exec --sandbox read-only "<diff brief>"` in this worktree, focused on: is grace mode reachable under any profile other than development; can any origin reach a credentialed request that `validate_runtime_security` would reject; does any legacy callback still touch the grace client; can any inline image or hex-escaped PDF name reach storage
- [ ] Update the debt register in `docs/superpowers/parallel/2026-07-23-program-status.md` — mark #1, #2a, #8, #9a, #9b, M3 closed with their commit hashes
