# PWR Voice v2 Measurement and Evaluation Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first safe Voice v2 slice: structured timing, reproducible command corpus, Odoo evaluation storage, mocked-STT browser coverage, and a disabled-by-default local LLM shadow scaffold.

**Architecture:** `/api/voice/recognize` remains the Command Fast Lane: PWA audio, backend conversion, Whisper, deterministic intent, response. Evaluation writes use separate endpoints, and local LLM runs only as backend shadow work behind flags, never as a direct action source. PWA sends capture timing and gets deterministic STT mocks in Playwright without needing a real microphone in the normal test gate.

**Tech Stack:** Python 3 / FastAPI / Pydantic / pytest / Odoo 18 addon models; Vanilla JS PWA / node:test / Playwright; optional Ollama-compatible HTTP API for shadow mode.

**Spec:** `docs/superpowers/specs/2026-06-27-voice-v2-hybrid-nlu-evaluation-design.md`

---

## Scope

This plan implements the first testable v2 scaffold.

In scope:

- Additive backend timing fields for `/api/voice/recognize`.
- Safety regression tests proving recognition does not resolve Odoo or n8n dependencies.
- Golden transcript corpus for deterministic intent behavior.
- Odoo models for voice evaluation sessions and events.
- Backend evaluation endpoints that write/query those Odoo models when enabled.
- PWA recognition timing fields and timing merge helpers.
- Playwright mocked-STT coverage through the PWA push-to-talk recognition path.
- Local LLM/Ollama shadow schema and adapter, disabled by default.

Out of scope for this plan:

- Active LLM fallback canary.
- Odoo confirm-line performance refactor.
- Live audio corpus with real Whisper.
- Fake microphone audio-file smoke project.
- Any change that lets an LLM execute `confirm`, `confirm_all`, `done`, or Odoo writes.

## Global Constraints

- `/api/voice/recognize` must not depend on Odoo, n8n, or the evaluation service.
- All new behavior flags default off.
- Raw audio is not stored in Odoo in this slice.
- Standard command behavior remains deterministic.
- Every task follows TDD: write the failing test, run it red, implement the minimal code, run green, commit.
- The current worktree is mixed. Before executing this plan, either cleanly commit/park existing unrelated changes or use `git commit --only` for each scoped task.
- Do not use `git add .`.
- Do not push from a mixed index.

## File Structure

Backend recognition:

- Modify: `backend/app/routers/voice.py`
- Test: `backend/tests/test_voice_routes.py`

Golden corpus:

- Create: `backend/tests/voice/golden_transcripts.v2.jsonl`
- Create: `backend/tests/test_voice_corpus.py`

Odoo evaluation storage:

- Create: `odoo/addons/picking_assistant_core/models/voice_eval.py`
- Modify: `odoo/addons/picking_assistant_core/models/__init__.py`
- Modify: `odoo/addons/picking_assistant_core/security/ir.model.access.csv`
- Test: `backend/tests/test_voice_eval_odoo_models_static.py`

Backend evaluation API:

- Modify: `backend/app/config.py`
- Create: `backend/app/models/voice_eval.py`
- Create: `backend/app/services/voice_eval_service.py`
- Create: `backend/app/routers/voice_eval.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_voice_eval_routes.py`

PWA timing:

- Modify: `pwa/js/voice-helpers.mjs`
- Modify: `pwa/js/api.js`
- Modify: `pwa/js/voice.js`
- Test: `pwa/js/tests/voice-helpers.test.mjs`
- Test: `pwa/js/tests/api.test.mjs`

Playwright mocked STT:

- Modify: `e2e/helpers/pwa-api.js`
- Create: `e2e/helpers/voice.js`
- Create: `e2e/voice-mocked-stt.spec.js`

Local LLM shadow scaffold:

- Modify: `backend/app/config.py`
- Create: `backend/app/models/voice_llm.py`
- Create: `backend/app/services/voice_llm.py`
- Modify: `backend/app/dependencies.py`
- Modify: `backend/app/routers/voice.py`
- Test: `backend/tests/test_voice_llm.py`
- Test: `backend/tests/test_voice_routes.py`

---

### Task 1: Backend Recognition Timing Contract

**Files:**
- Modify: `Mobile Picking und Voice Assistant/backend/app/routers/voice.py`
- Test: `Mobile Picking und Voice Assistant/backend/tests/test_voice_routes.py`

**Interfaces:**
- `/api/voice/recognize` keeps existing response fields.
- `_timing` keeps `audio_bytes`, `convert_ms`, `stt_ms`, `total_ms`.
- `_timing` adds `intent_ms`, `backend_total_ms`, `recording_ms`, `speech_ms`, `silence_wait_ms`, `upload_ms`, `correlation_id`.
- Client timing fields are accepted as form fields and ignored when negative or non-numeric.

- [ ] **Step 1: Write the failing tests**

Append these tests to `backend/tests/test_voice_routes.py`:

```python
def _raise_dependency(*_args, **_kwargs):
    raise AssertionError("voice recognition hotpath must not resolve this dependency")


def test_voice_recognize_hotpath_does_not_resolve_odoo_or_n8n_dependencies(monkeypatch):
    monkeypatch.setattr(voice_router, "convert_to_wav", AsyncMock(return_value=b"wav-bytes"))
    monkeypatch.setattr(
        voice_router.whisper_client,
        "transcribe_audio",
        AsyncMock(return_value="ja"),
    )
    app.dependency_overrides[get_n8n_client] = _raise_dependency
    app.dependency_overrides[get_odoo_client] = _raise_dependency
    app.dependency_overrides[get_request_odoo_client] = _raise_dependency

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/voice/recognize",
                data={
                    "context": "awaiting_command",
                    "surface": "detail",
                    "remaining_line_count": "1",
                    "active_line_present": "true",
                },
                files={"audio": ("voice.webm", b"1234", "audio/webm")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["intent"] == "confirm"


def test_voice_recognize_reports_backend_and_client_timing(monkeypatch):
    monkeypatch.setattr(voice_router, "convert_to_wav", AsyncMock(return_value=b"wav-bytes"))
    monkeypatch.setattr(
        voice_router.whisper_client,
        "transcribe_audio",
        AsyncMock(return_value="ja"),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/voice/recognize",
            data={
                "context": "awaiting_command",
                "surface": "detail",
                "remaining_line_count": "1",
                "active_line_present": "true",
                "recording_ms": "840",
                "speech_ms": "390",
                "silence_wait_ms": "310",
                "upload_ms": "42",
                "correlation_id": "voice-test-1",
            },
            files={"audio": ("voice.webm", b"1234", "audio/webm")},
        )

    assert response.status_code == 200
    timing = response.json()["_timing"]
    assert timing["audio_bytes"] == 4
    assert isinstance(timing["convert_ms"], int)
    assert isinstance(timing["stt_ms"], int)
    assert isinstance(timing["intent_ms"], int)
    assert isinstance(timing["backend_total_ms"], int)
    assert timing["backend_total_ms"] >= timing["convert_ms"] + timing["stt_ms"]
    assert timing["total_ms"] == timing["backend_total_ms"]
    assert timing["recording_ms"] == 840
    assert timing["speech_ms"] == 390
    assert timing["silence_wait_ms"] == 310
    assert timing["upload_ms"] == 42
    assert timing["correlation_id"] == "voice-test-1"


def test_voice_recognize_empty_stt_returns_full_timing_shape(monkeypatch):
    monkeypatch.setattr(voice_router, "convert_to_wav", AsyncMock(return_value=b"wav-bytes"))
    monkeypatch.setattr(
        voice_router.whisper_client,
        "transcribe_audio",
        AsyncMock(return_value=""),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/voice/recognize",
            data={
                "context": "awaiting_command",
                "surface": "detail",
                "remaining_line_count": "1",
                "active_line_present": "true",
                "recording_ms": "-1",
                "speech_ms": "nan",
            },
            files={"audio": ("voice.webm", b"1234", "audio/webm")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "unknown"
    timing = payload["_timing"]
    assert "intent_ms" in timing
    assert "backend_total_ms" in timing
    assert timing["recording_ms"] is None
    assert timing["speech_ms"] is None
```

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant\backend"
$env:PYTHONPATH = ".deps;."
python -m pytest -p pytest_asyncio tests/test_voice_routes.py::test_voice_recognize_reports_backend_and_client_timing tests/test_voice_routes.py::test_voice_recognize_empty_stt_returns_full_timing_shape -q
```

Expected: FAIL because `_timing.intent_ms`, `_timing.backend_total_ms`, and client timing fields do not exist yet.

- [ ] **Step 3: Implement timing helpers**

In `backend/app/routers/voice.py`, add these helpers near the top below constants:

```python
def _safe_non_negative_int(value: int | str | None) -> int | None:
    if value is None:
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    if normalized < 0:
        return None
    return normalized


def _build_recognition_timing(
    *,
    audio_size: int,
    convert_ms: int,
    stt_ms: int,
    intent_ms: int,
    backend_total_ms: int,
    recording_ms: int | str | None,
    speech_ms: int | str | None,
    silence_wait_ms: int | str | None,
    upload_ms: int | str | None,
    correlation_id: str | None,
) -> dict[str, int | str | None]:
    return {
        "audio_bytes": audio_size,
        "convert_ms": convert_ms,
        "stt_ms": stt_ms,
        "intent_ms": intent_ms,
        "backend_total_ms": backend_total_ms,
        "total_ms": backend_total_ms,
        "recording_ms": _safe_non_negative_int(recording_ms),
        "speech_ms": _safe_non_negative_int(speech_ms),
        "silence_wait_ms": _safe_non_negative_int(silence_wait_ms),
        "upload_ms": _safe_non_negative_int(upload_ms),
        "correlation_id": (correlation_id or "").strip() or None,
    }
```

- [ ] **Step 4: Extend the route signature**

In `recognize_speech(...)`, add form fields:

```python
    recording_ms: int | None = Form(default=None),
    speech_ms: int | None = Form(default=None),
    silence_wait_ms: int | None = Form(default=None),
    upload_ms: int | None = Form(default=None),
    correlation_id: str | None = Form(default=None),
```

- [ ] **Step 5: Measure intent and return the full timing shape**

Replace the early `total_ms = ...` assignment after STT with `stt_elapsed_ms` only, then build final timing in both response branches:

```python
    stt_ms = round((time.monotonic() - stt_started_at) * 1000)
```

For the empty text branch:

```python
    if not text:
        backend_total_ms = round((time.monotonic() - started_at) * 1000)
        timing = _build_recognition_timing(
            audio_size=audio_size,
            convert_ms=convert_ms,
            stt_ms=stt_ms,
            intent_ms=0,
            backend_total_ms=backend_total_ms,
            recording_ms=recording_ms,
            speech_ms=speech_ms,
            silence_wait_ms=silence_wait_ms,
            upload_ms=upload_ms,
            correlation_id=correlation_id,
        )
        return {
            "text": "",
            "intent": "unknown",
            "value": None,
            "confidence": 0.0,
            "normalized_text": "",
            "match_strategy": "unknown",
            "_timing": timing,
        }
```

Before calling `recognize_intent(...)`, add:

```python
    intent_started_at = time.monotonic()
```

After the segment fallback decision, add:

```python
    intent_ms = round((time.monotonic() - intent_started_at) * 1000)
    backend_total_ms = round((time.monotonic() - started_at) * 1000)
    timing = _build_recognition_timing(
        audio_size=audio_size,
        convert_ms=convert_ms,
        stt_ms=stt_ms,
        intent_ms=intent_ms,
        backend_total_ms=backend_total_ms,
        recording_ms=recording_ms,
        speech_ms=speech_ms,
        silence_wait_ms=silence_wait_ms,
        upload_ms=upload_ms,
        correlation_id=correlation_id,
    )
```

Update log calls to use `backend_total_ms`, and return `_timing: timing`.

- [ ] **Step 6: Run tests to verify green**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant\backend"
$env:PYTHONPATH = ".deps;."
python -m pytest -p pytest_asyncio tests/test_voice_routes.py -q
```

Expected: PASS for voice route tests.

- [ ] **Step 7: Commit**

```powershell
git add "Mobile Picking und Voice Assistant/backend/app/routers/voice.py" `
        "Mobile Picking und Voice Assistant/backend/tests/test_voice_routes.py"
git commit --only -m "feat(voice): add structured recognition timing" -- `
        "Mobile Picking und Voice Assistant/backend/app/routers/voice.py" `
        "Mobile Picking und Voice Assistant/backend/tests/test_voice_routes.py"
```

---

### Task 2: Golden Transcript Corpus

**Files:**
- Create: `Mobile Picking und Voice Assistant/backend/tests/voice/golden_transcripts.v2.jsonl`
- Create: `Mobile Picking und Voice Assistant/backend/tests/test_voice_corpus.py`

**Interfaces:**
- Corpus tests call `recognize_intent(...)` directly.
- No Whisper, Odoo, n8n, Piper, microphone, or FastAPI app startup is needed.

- [ ] **Step 1: Write the failing corpus test**

Create `backend/tests/test_voice_corpus.py`:

```python
"""Golden transcript corpus for deterministic Voice v2 commands."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.intent_engine import PickingContext, VoiceSurface, recognize_intent

CORPUS_PATH = Path(__file__).parent / "voice" / "golden_transcripts.v2.jsonl"


def _load_cases() -> list[dict]:
    return [
        json.loads(line)
        for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["case_id"])
def test_golden_voice_transcripts(case):
    result = recognize_intent(
        case["transcript"],
        PickingContext(case["context"]),
        surface=VoiceSurface(case["surface"]),
        remaining_line_count=case["remaining_line_count"],
        active_line_present=case["active_line_present"],
    )
    assert result.action == case["expected_intent"]
    assert result.value == case.get("expected_value")
    if case.get("min_confidence") is not None:
        assert result.confidence >= case["min_confidence"]
    if case.get("must_not_execute"):
        assert result.action == "unknown"
```

- [ ] **Step 2: Run test to verify red**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant\backend"
$env:PYTHONPATH = ".deps;."
python -m pytest -p pytest_asyncio tests/test_voice_corpus.py -q
```

Expected: FAIL because `backend/tests/voice/golden_transcripts.v2.jsonl` does not exist.

- [ ] **Step 3: Add the corpus**

Create `backend/tests/voice/golden_transcripts.v2.jsonl` with exactly these JSONL rows:

```jsonl
{"case_id":"confirm_yes_detail","transcript":"ja","context":"awaiting_command","surface":"detail","remaining_line_count":1,"active_line_present":true,"expected_intent":"confirm","expected_value":null,"min_confidence":0.95,"must_not_execute":false}
{"case_id":"confirm_order_phrase_means_active_line","transcript":"ich moechte den auftrag bestaetigen","context":"awaiting_command","surface":"detail","remaining_line_count":2,"active_line_present":true,"expected_intent":"confirm","expected_value":null,"min_confidence":0.95,"must_not_execute":false}
{"case_id":"package_done_confirms_active_line","transcript":"paket erledigt","context":"awaiting_command","surface":"detail","remaining_line_count":2,"active_line_present":true,"expected_intent":"confirm","expected_value":null,"min_confidence":0.95,"must_not_execute":false}
{"case_id":"carton_done_confirms_active_line","transcript":"karton fertig","context":"awaiting_command","surface":"detail","remaining_line_count":2,"active_line_present":true,"expected_intent":"confirm","expected_value":null,"min_confidence":0.95,"must_not_execute":false}
{"case_id":"next_order_complete_view","transcript":"naechster auftrag bitte","context":"awaiting_command","surface":"complete","remaining_line_count":0,"active_line_present":false,"expected_intent":"next_order","expected_value":null,"min_confidence":0.95,"must_not_execute":false}
{"case_id":"next_order_detail_active_line_blocked","transcript":"naechster auftrag","context":"awaiting_command","surface":"detail","remaining_line_count":2,"active_line_present":true,"expected_intent":"unknown","expected_value":null,"min_confidence":null,"must_not_execute":true}
{"case_id":"confirm_all_explicit_detail","transcript":"auftrag erledigt","context":"awaiting_command","surface":"detail","remaining_line_count":2,"active_line_present":true,"expected_intent":"confirm_all","expected_value":null,"min_confidence":0.95,"must_not_execute":false}
{"case_id":"confirm_all_list_blocked","transcript":"auftrag komplett","context":"awaiting_command","surface":"list","remaining_line_count":3,"active_line_present":false,"expected_intent":"unknown","expected_value":null,"min_confidence":null,"must_not_execute":true}
{"case_id":"done_after_no_active_line","transcript":"fertig","context":"awaiting_command","surface":"complete","remaining_line_count":0,"active_line_present":false,"expected_intent":"done","expected_value":null,"min_confidence":0.95,"must_not_execute":false}
{"case_id":"done_last_active_line_blocked","transcript":"fertig","context":"awaiting_command","surface":"detail","remaining_line_count":0,"active_line_present":true,"expected_intent":"unknown","expected_value":null,"min_confidence":null,"must_not_execute":true}
{"case_id":"negative_confirmation_is_problem","transcript":"passt nicht","context":"awaiting_command","surface":"detail","remaining_line_count":1,"active_line_present":true,"expected_intent":"problem","expected_value":null,"min_confidence":0.95,"must_not_execute":false}
{"case_id":"list_yes_blocked","transcript":"ja","context":"awaiting_command","surface":"list","remaining_line_count":4,"active_line_present":false,"expected_intent":"unknown","expected_value":null,"min_confidence":null,"must_not_execute":true}
{"case_id":"location_check_number","transcript":"vier","context":"awaiting_location_check","surface":"detail","remaining_line_count":1,"active_line_present":true,"expected_intent":"check_digit","expected_value":"4","min_confidence":0.95,"must_not_execute":false}
{"case_id":"quantity_number","transcript":"fuenf","context":"awaiting_quantity_confirm","surface":"detail","remaining_line_count":1,"active_line_present":true,"expected_intent":"quantity","expected_value":"5","min_confidence":0.95,"must_not_execute":false}
{"case_id":"stock_query","transcript":"ist noch bestand verfuegbar","context":"awaiting_command","surface":"detail","remaining_line_count":1,"active_line_present":true,"expected_intent":"stock_query","expected_value":null,"min_confidence":0.95,"must_not_execute":false}
```

- [ ] **Step 4: Run test to verify green**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant\backend"
$env:PYTHONPATH = ".deps;."
python -m pytest -p pytest_asyncio tests/test_voice_corpus.py tests/test_intent_engine.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add "Mobile Picking und Voice Assistant/backend/tests/voice/golden_transcripts.v2.jsonl" `
        "Mobile Picking und Voice Assistant/backend/tests/test_voice_corpus.py"
git commit --only -m "test(voice): add golden transcript corpus" -- `
        "Mobile Picking und Voice Assistant/backend/tests/voice/golden_transcripts.v2.jsonl" `
        "Mobile Picking und Voice Assistant/backend/tests/test_voice_corpus.py"
```

---

### Task 3: Odoo Voice Evaluation Models

**Files:**
- Create: `Mobile Picking und Voice Assistant/odoo/addons/picking_assistant_core/models/voice_eval.py`
- Modify: `Mobile Picking und Voice Assistant/odoo/addons/picking_assistant_core/models/__init__.py`
- Modify: `Mobile Picking und Voice Assistant/odoo/addons/picking_assistant_core/security/ir.model.access.csv`
- Test: `Mobile Picking und Voice Assistant/backend/tests/test_voice_eval_odoo_models_static.py`

**Interfaces:**
- Odoo models:
  - `pwr.voice.eval.session`
  - `pwr.voice.eval.event`
- Static tests avoid importing `odoo`, so the normal backend test gate remains local.

- [ ] **Step 1: Write the failing static test**

Create `backend/tests/test_voice_eval_odoo_models_static.py`:

```python
"""Static contract tests for the Odoo voice evaluation models."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "odoo" / "addons" / "picking_assistant_core"


def test_voice_eval_model_file_declares_session_and_event_models():
    content = (ADDON / "models" / "voice_eval.py").read_text(encoding="utf-8")
    assert '_name = "pwr.voice.eval.session"' in content
    assert '_name = "pwr.voice.eval.event"' in content
    assert "audio_sha256" in content
    assert "audio_asset_ref" in content
    assert "fields.Binary" not in content


def test_voice_eval_models_are_imported_by_addon():
    content = (ADDON / "models" / "__init__.py").read_text(encoding="utf-8")
    assert "from . import voice_eval" in content


def test_voice_eval_models_have_system_access_rows():
    content = (ADDON / "security" / "ir.model.access.csv").read_text(encoding="utf-8")
    assert "model_pwr_voice_eval_session" in content
    assert "model_pwr_voice_eval_event" in content
```

- [ ] **Step 2: Run test to verify red**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant\backend"
$env:PYTHONPATH = ".deps;."
python -m pytest -p pytest_asyncio tests/test_voice_eval_odoo_models_static.py -q
```

Expected: FAIL because `voice_eval.py` does not exist.

- [ ] **Step 3: Add the Odoo model file**

Create `odoo/addons/picking_assistant_core/models/voice_eval.py`:

```python
from odoo import fields, models


class PwrVoiceEvalSession(models.Model):
    _name = "pwr.voice.eval.session"
    _description = "PWR Voice Evaluation Session"
    _order = "create_date desc"

    name = fields.Char(required=True, index=True)
    spec_version = fields.Char(default="voice-v2", index=True)
    corpus_version = fields.Char(index=True)
    app_git_sha = fields.Char(index=True)
    backend_git_sha = fields.Char(index=True)
    mode = fields.Selection(
        [
            ("golden_transcript", "Golden Transcript"),
            ("audio_corpus", "Audio Corpus"),
            ("playwright_mock", "Playwright Mock"),
            ("manual_device", "Manual Device"),
            ("live_shadow", "Live Shadow"),
        ],
        required=True,
        index=True,
    )
    started_at = fields.Datetime(index=True)
    ended_at = fields.Datetime(index=True)
    operator_user_id = fields.Many2one("res.users", ondelete="set null")
    evaluator_user_id = fields.Many2one("res.users", ondelete="set null")
    device_id_hash = fields.Char(index=True)
    device_label = fields.Char()
    browser = fields.Char()
    os = fields.Char()
    microphone_type = fields.Char()
    environment_profile = fields.Char()
    noise_db_avg = fields.Float()
    noise_db_peak = fields.Float()
    event_count = fields.Integer(default=0)
    intent_accuracy = fields.Float()
    command_success_rate = fields.Float()
    false_positive_rate = fields.Float()
    p50_end_to_end_ms = fields.Integer()
    p95_end_to_end_ms = fields.Integer()
    p95_stt_ms = fields.Integer()
    notes = fields.Text()


class PwrVoiceEvalEvent(models.Model):
    _name = "pwr.voice.eval.event"
    _description = "PWR Voice Evaluation Event"
    _order = "occurred_at desc, id desc"

    session_id = fields.Many2one("pwr.voice.eval.session", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(index=True)
    case_id = fields.Char(index=True)
    correlation_id = fields.Char(index=True)
    occurred_at = fields.Datetime(index=True)
    event_type = fields.Char(required=True, index=True)
    surface = fields.Char(index=True)
    context = fields.Char(index=True)
    picking_id = fields.Many2one("stock.picking", ondelete="set null", index=True)
    move_line_id = fields.Integer(index=True)
    product_id = fields.Many2one("product.product", ondelete="set null", index=True)
    location_id = fields.Many2one("stock.location", ondelete="set null", index=True)
    source = fields.Selection(
        [
            ("transcript", "Transcript"),
            ("mock_stt", "Mock STT"),
            ("audio_corpus", "Audio Corpus"),
            ("manual_device", "Manual Device"),
            ("live_shadow", "Live Shadow"),
        ],
        required=True,
        index=True,
    )
    audio_asset_ref = fields.Char()
    audio_sha256 = fields.Char(index=True)
    audio_bytes = fields.Integer()
    speech_ms = fields.Integer()
    expected_transcript = fields.Text()
    whisper_transcript = fields.Text()
    normalized_text = fields.Text()
    expected_intent = fields.Char(index=True)
    recognized_intent = fields.Char(index=True)
    expected_value = fields.Char()
    recognized_value = fields.Char()
    confidence = fields.Float()
    match_strategy = fields.Char()
    requires_confirmation = fields.Boolean(default=False)
    llm_enabled = fields.Boolean(default=False)
    llm_shadow = fields.Boolean(default=False)
    llm_model = fields.Char()
    llm_intent_candidate = fields.Char()
    llm_confidence = fields.Float()
    llm_disagreement_category = fields.Char()
    intent_correct = fields.Boolean()
    context_gate_correct = fields.Boolean()
    action_executed = fields.Boolean()
    backend_success = fields.Boolean()
    odoo_write_success = fields.Boolean()
    n8n_called = fields.Boolean()
    piper_used = fields.Boolean()
    browser_tts_used = fields.Boolean()
    false_positive = fields.Boolean(default=False, index=True)
    false_negative = fields.Boolean(default=False, index=True)
    failure_stage = fields.Char(index=True)
    error_message = fields.Text()
    recording_ms = fields.Integer()
    upload_ms = fields.Integer()
    convert_ms = fields.Integer()
    stt_ms = fields.Integer()
    intent_ms = fields.Integer()
    backend_total_ms = fields.Integer()
    pwa_action_ms = fields.Integer()
    odoo_ms = fields.Integer()
    n8n_ms = fields.Integer()
    tts_synthesis_ms = fields.Integer()
    tts_playback_ms = fields.Integer()
    end_to_end_ms = fields.Integer()
    time_to_next_listening_ms = fields.Integer()
    config_snapshot_json = fields.Text()
```

- [ ] **Step 4: Import model and add access rows**

In `odoo/addons/picking_assistant_core/models/__init__.py`, add:

```python
from . import voice_eval
```

Append to `odoo/addons/picking_assistant_core/security/ir.model.access.csv`:

```csv
access_pwr_voice_eval_session_system,pwr.voice.eval.session.system,model_pwr_voice_eval_session,base.group_system,1,1,1,1
access_pwr_voice_eval_event_system,pwr.voice.eval.event.system,model_pwr_voice_eval_event,base.group_system,1,1,1,1
```

- [ ] **Step 5: Run test to verify green**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant\backend"
$env:PYTHONPATH = ".deps;."
python -m pytest -p pytest_asyncio tests/test_voice_eval_odoo_models_static.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add "Mobile Picking und Voice Assistant/odoo/addons/picking_assistant_core/models/voice_eval.py" `
        "Mobile Picking und Voice Assistant/odoo/addons/picking_assistant_core/models/__init__.py" `
        "Mobile Picking und Voice Assistant/odoo/addons/picking_assistant_core/security/ir.model.access.csv" `
        "Mobile Picking und Voice Assistant/backend/tests/test_voice_eval_odoo_models_static.py"
git commit --only -m "feat(odoo): add voice evaluation storage models" -- `
        "Mobile Picking und Voice Assistant/odoo/addons/picking_assistant_core/models/voice_eval.py" `
        "Mobile Picking und Voice Assistant/odoo/addons/picking_assistant_core/models/__init__.py" `
        "Mobile Picking und Voice Assistant/odoo/addons/picking_assistant_core/security/ir.model.access.csv" `
        "Mobile Picking und Voice Assistant/backend/tests/test_voice_eval_odoo_models_static.py"
```

---

### Task 4: Backend Evaluation Endpoints

**Files:**
- Modify: `Mobile Picking und Voice Assistant/backend/app/config.py`
- Create: `Mobile Picking und Voice Assistant/backend/app/models/voice_eval.py`
- Create: `Mobile Picking und Voice Assistant/backend/app/services/voice_eval_service.py`
- Create: `Mobile Picking und Voice Assistant/backend/app/routers/voice_eval.py`
- Modify: `Mobile Picking und Voice Assistant/backend/app/main.py`
- Test: `Mobile Picking und Voice Assistant/backend/tests/test_voice_eval_routes.py`

**Interfaces:**
- `POST /api/voice/eval/sessions`
- `POST /api/voice/eval/events`
- `GET /api/voice/eval/sessions/{session_id}/events`
- Endpoints use Odoo through `get_request_odoo_client`.
- Storage is disabled unless `settings.pwr_voice_eval_storage_enabled` is true.

- [ ] **Step 1: Write the failing route tests**

Create `backend/tests/test_voice_eval_routes.py`:

```python
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app import config
from app.dependencies import get_request_odoo_client
from app.main import app


class FakeOdoo:
    def __init__(self):
        self.create = AsyncMock(side_effect=[101, 202])
        self.search_read = AsyncMock(return_value=[{"id": 202, "recognized_intent": "confirm"}])


def test_voice_eval_session_disabled_by_default(monkeypatch):
    monkeypatch.setattr(config.settings, "pwr_voice_eval_storage_enabled", False, raising=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/voice/eval/sessions",
            json={"name": "Lab run", "mode": "golden_transcript"},
        )
    assert response.status_code == 503
    assert "Voice evaluation storage ist deaktiviert" in response.json()["detail"]


def test_voice_eval_session_and_event_write_to_odoo_when_enabled(monkeypatch):
    monkeypatch.setattr(config.settings, "pwr_voice_eval_storage_enabled", True, raising=False)
    fake = FakeOdoo()
    app.dependency_overrides[get_request_odoo_client] = lambda: fake
    try:
        with TestClient(app) as client:
            session_response = client.post(
                "/api/voice/eval/sessions",
                json={
                    "name": "Lab run",
                    "mode": "golden_transcript",
                    "spec_version": "voice-v2",
                    "corpus_version": "v2",
                },
            )
            event_response = client.post(
                "/api/voice/eval/events",
                json={
                    "session_id": 101,
                    "event_type": "voice_recognize",
                    "source": "transcript",
                    "case_id": "confirm_yes_detail",
                    "expected_intent": "confirm",
                    "recognized_intent": "confirm",
                    "intent_correct": True,
                    "backend_total_ms": 120,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert session_response.status_code == 200
    assert session_response.json() == {"id": 101}
    assert event_response.status_code == 200
    assert event_response.json() == {"id": 202}
    fake.create.assert_any_await("pwr.voice.eval.session", {
        "name": "Lab run",
        "mode": "golden_transcript",
        "spec_version": "voice-v2",
        "corpus_version": "v2",
    })
    event_model, event_vals = fake.create.await_args_list[1].args
    assert event_model == "pwr.voice.eval.event"
    assert event_vals["session_id"] == 101
    assert event_vals["recognized_intent"] == "confirm"
    assert event_vals["backend_total_ms"] == 120


def test_voice_eval_events_can_be_queried(monkeypatch):
    monkeypatch.setattr(config.settings, "pwr_voice_eval_storage_enabled", True, raising=False)
    fake = FakeOdoo()
    app.dependency_overrides[get_request_odoo_client] = lambda: fake
    try:
        with TestClient(app) as client:
            response = client.get("/api/voice/eval/sessions/101/events")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [{"id": 202, "recognized_intent": "confirm"}]
    fake.search_read.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify red**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant\backend"
$env:PYTHONPATH = ".deps;."
python -m pytest -p pytest_asyncio tests/test_voice_eval_routes.py -q
```

Expected: FAIL because routes and models do not exist.

- [ ] **Step 3: Add config flags**

In `backend/app/config.py`, inside `class Settings`, add:

```python
    pwr_voice_v2_enabled: bool = False
    pwr_voice_eval_storage_enabled: bool = False
    pwr_voice_eval_raw_audio_enabled: bool = False
```

- [ ] **Step 4: Add request models**

Create `backend/app/models/voice_eval.py`:

```python
"""Pydantic models for PWR voice evaluation storage."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VoiceEvalSessionCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    mode: Literal["golden_transcript", "audio_corpus", "playwright_mock", "manual_device", "live_shadow"]
    spec_version: str = "voice-v2"
    corpus_version: str | None = None
    app_git_sha: str | None = None
    backend_git_sha: str | None = None
    device_id_hash: str | None = None
    device_label: str | None = None
    browser: str | None = None
    os: str | None = None
    microphone_type: str | None = None
    environment_profile: str | None = None
    notes: str | None = None


class VoiceEvalEventCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: int
    event_type: str = Field(min_length=1)
    source: Literal["transcript", "mock_stt", "audio_corpus", "manual_device", "live_shadow"]
    sequence: int | None = None
    case_id: str | None = None
    correlation_id: str | None = None
    surface: str | None = None
    context: str | None = None
    picking_id: int | None = None
    move_line_id: int | None = None
    product_id: int | None = None
    location_id: int | None = None
    audio_asset_ref: str | None = None
    audio_sha256: str | None = None
    audio_bytes: int | None = Field(default=None, ge=0)
    speech_ms: int | None = Field(default=None, ge=0)
    expected_transcript: str | None = None
    whisper_transcript: str | None = None
    normalized_text: str | None = None
    expected_intent: str | None = None
    recognized_intent: str | None = None
    expected_value: str | None = None
    recognized_value: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    match_strategy: str | None = None
    requires_confirmation: bool | None = None
    llm_enabled: bool | None = None
    llm_shadow: bool | None = None
    llm_model: str | None = None
    llm_intent_candidate: str | None = None
    llm_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    llm_disagreement_category: str | None = None
    intent_correct: bool | None = None
    context_gate_correct: bool | None = None
    action_executed: bool | None = None
    backend_success: bool | None = None
    odoo_write_success: bool | None = None
    n8n_called: bool | None = None
    piper_used: bool | None = None
    browser_tts_used: bool | None = None
    false_positive: bool | None = None
    false_negative: bool | None = None
    failure_stage: str | None = None
    error_message: str | None = None
    recording_ms: int | None = Field(default=None, ge=0)
    upload_ms: int | None = Field(default=None, ge=0)
    convert_ms: int | None = Field(default=None, ge=0)
    stt_ms: int | None = Field(default=None, ge=0)
    intent_ms: int | None = Field(default=None, ge=0)
    backend_total_ms: int | None = Field(default=None, ge=0)
    pwa_action_ms: int | None = Field(default=None, ge=0)
    odoo_ms: int | None = Field(default=None, ge=0)
    n8n_ms: int | None = Field(default=None, ge=0)
    tts_synthesis_ms: int | None = Field(default=None, ge=0)
    tts_playback_ms: int | None = Field(default=None, ge=0)
    end_to_end_ms: int | None = Field(default=None, ge=0)
    time_to_next_listening_ms: int | None = Field(default=None, ge=0)
    config_snapshot_json: str | None = None
```

- [ ] **Step 5: Add service**

Create `backend/app/services/voice_eval_service.py`:

```python
"""Persistence facade for PWR voice evaluation data."""
from __future__ import annotations

from app.models.voice_eval import VoiceEvalEventCreate, VoiceEvalSessionCreate
from app.services.odoo_client import OdooClient


def _clean_values(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if value is not None}


class VoiceEvalService:
    def __init__(self, odoo: OdooClient):
        self._odoo = odoo

    async def create_session(self, body: VoiceEvalSessionCreate) -> dict[str, int]:
        record_id = await self._odoo.create(
            "pwr.voice.eval.session",
            _clean_values(body.model_dump()),
        )
        return {"id": int(record_id)}

    async def create_event(self, body: VoiceEvalEventCreate) -> dict[str, int]:
        record_id = await self._odoo.create(
            "pwr.voice.eval.event",
            _clean_values(body.model_dump()),
        )
        return {"id": int(record_id)}

    async def list_events(self, session_id: int) -> list[dict]:
        return await self._odoo.search_read(
            "pwr.voice.eval.event",
            [("session_id", "=", int(session_id))],
            ["id", "case_id", "event_type", "recognized_intent", "intent_correct", "backend_total_ms"],
            limit=500,
        )
```

- [ ] **Step 6: Add router**

Create `backend/app/routers/voice_eval.py`:

```python
"""Voice evaluation storage endpoints."""
from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.dependencies import get_request_odoo_client
from app.models.voice_eval import VoiceEvalEventCreate, VoiceEvalSessionCreate
from app.services.odoo_client import OdooClient
from app.services.voice_eval_service import VoiceEvalService

router = APIRouter()


def _require_voice_eval_enabled() -> None:
    if not settings.pwr_voice_eval_storage_enabled:
        raise HTTPException(status_code=503, detail="Voice evaluation storage ist deaktiviert.")


@router.post("/voice/eval/sessions")
async def create_voice_eval_session(
    body: VoiceEvalSessionCreate,
    odoo: OdooClient = Depends(get_request_odoo_client),
):
    _require_voice_eval_enabled()
    return await VoiceEvalService(odoo).create_session(body)


@router.post("/voice/eval/events")
async def create_voice_eval_event(
    body: VoiceEvalEventCreate,
    odoo: OdooClient = Depends(get_request_odoo_client),
):
    _require_voice_eval_enabled()
    return await VoiceEvalService(odoo).create_event(body)


@router.get("/voice/eval/sessions/{session_id}/events")
async def list_voice_eval_events(
    session_id: int,
    odoo: OdooClient = Depends(get_request_odoo_client),
):
    _require_voice_eval_enabled()
    return await VoiceEvalService(odoo).list_events(session_id)
```

In `backend/app/main.py`, add `voice_eval` to the router import and include it:

```python
from app.routers import cluster, health, instances, integration, n8n_internal, obsidian, pickings, quality, scan, voice, voice_eval
```

```python
app.include_router(voice_eval.router, prefix="/api", tags=["voice-eval"])
```

- [ ] **Step 7: Run tests to verify green**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant\backend"
$env:PYTHONPATH = ".deps;."
python -m pytest -p pytest_asyncio tests/test_voice_eval_routes.py tests/test_voice_routes.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add "Mobile Picking und Voice Assistant/backend/app/config.py" `
        "Mobile Picking und Voice Assistant/backend/app/models/voice_eval.py" `
        "Mobile Picking und Voice Assistant/backend/app/services/voice_eval_service.py" `
        "Mobile Picking und Voice Assistant/backend/app/routers/voice_eval.py" `
        "Mobile Picking und Voice Assistant/backend/app/main.py" `
        "Mobile Picking und Voice Assistant/backend/tests/test_voice_eval_routes.py"
git commit --only -m "feat(voice): add evaluation storage endpoints" -- `
        "Mobile Picking und Voice Assistant/backend/app/config.py" `
        "Mobile Picking und Voice Assistant/backend/app/models/voice_eval.py" `
        "Mobile Picking und Voice Assistant/backend/app/services/voice_eval_service.py" `
        "Mobile Picking und Voice Assistant/backend/app/routers/voice_eval.py" `
        "Mobile Picking und Voice Assistant/backend/app/main.py" `
        "Mobile Picking und Voice Assistant/backend/tests/test_voice_eval_routes.py"
```

---

### Task 5: PWA Recognition Timing Contract

**Files:**
- Modify: `Mobile Picking und Voice Assistant/pwa/js/voice-helpers.mjs`
- Modify: `Mobile Picking und Voice Assistant/pwa/js/api.js`
- Test: `Mobile Picking und Voice Assistant/pwa/js/tests/voice-helpers.test.mjs`
- Test: `Mobile Picking und Voice Assistant/pwa/js/tests/api.test.mjs`

**Interfaces:**
- `buildVoiceTimingFormFields(timing)` returns safe non-negative integer form fields.
- `mergeRecognitionTiming(serverTiming, clientTiming)` maps backend `total_ms` to `backend_total_ms`.
- `recognizeVoice(audioBlob, options)` sends timing fields when `options.timing` is provided.

- [ ] **Step 1: Write failing helper tests**

Append to `pwa/js/tests/voice-helpers.test.mjs` and add the named imports at the top:

```javascript
test('buildVoiceTimingFormFields keeps only safe non-negative integer values', () => {
    assert.deepEqual(
        buildVoiceTimingFormFields({
            capture_mode: 'push_to_talk',
            recording_ms: 820.7,
            speech_ms: 310,
            silence_wait_ms: -1,
            upload_ms: Number.NaN,
        }),
        {
            capture_mode: 'push_to_talk',
            recording_ms: 821,
            speech_ms: 310,
        },
    );
});

test('mergeRecognitionTiming preserves backend timings and maps total to backend_total_ms', () => {
    assert.deepEqual(
        mergeRecognitionTiming(
            { total_ms: 140, convert_ms: 20, stt_ms: 110, intent_ms: 3 },
            { recording_ms: 800, speech_ms: 360 },
        ),
        {
            backend_total_ms: 140,
            total_ms: 140,
            convert_ms: 20,
            stt_ms: 110,
            intent_ms: 3,
            recording_ms: 800,
            speech_ms: 360,
        },
    );
});
```

- [ ] **Step 2: Write failing API test**

Append to `pwa/js/tests/api.test.mjs`:

```javascript
test('recognizeVoice sends timing fields and merges backend timing', async () => {
    const originalFetch = global.fetch;
    let capturedBody = null;

    global.fetch = async (_url, options) => {
        capturedBody = options.body;
        return {
            ok: true,
            status: 200,
            json: async () => ({
                intent: 'confirm',
                text: 'ja',
                confidence: 0.95,
                _timing: { total_ms: 150, convert_ms: 20, stt_ms: 120, intent_ms: 4 },
            }),
        };
    };

    try {
        const blob = new Blob(['voice'], { type: 'audio/webm' });
        const result = await recognizeVoice(blob, {
            context: 'awaiting_command',
            surface: 'detail',
            remaining_line_count: 2,
            active_line_present: true,
            timing: {
                capture_mode: 'push_to_talk',
                recording_ms: 900,
                speech_ms: null,
                silence_wait_ms: null,
            },
        });

        assert.equal(capturedBody.get('capture_mode'), 'push_to_talk');
        assert.equal(capturedBody.get('recording_ms'), '900');
        assert.equal(capturedBody.get('speech_ms'), null);
        assert.equal(result._timing.backend_total_ms, 150);
        assert.equal(result._timing.recording_ms, 900);
    } finally {
        global.fetch = originalFetch;
    }
});
```

- [ ] **Step 3: Run tests to verify red**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant"
npm run test:voice
```

Expected: FAIL because timing helpers do not exist and `recognizeVoice` does not send timing fields.

- [ ] **Step 4: Add helper functions**

In `pwa/js/voice-helpers.mjs`, export:

```javascript
const TIMING_FIELD_NAMES = [
    'recording_ms',
    'speech_ms',
    'silence_wait_ms',
    'upload_ms',
    'pwa_request_ms',
];

function sanitizeTimingValue(value) {
    if (value === null || value === undefined || value === '') return null;
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric < 0) return null;
    return Math.round(numeric);
}

export function buildVoiceTimingFormFields(timing = {}) {
    const result = {};
    const captureMode = String(timing.capture_mode || '').trim();
    if (captureMode) result.capture_mode = captureMode;
    for (const field of TIMING_FIELD_NAMES) {
        const value = sanitizeTimingValue(timing[field]);
        if (value !== null) result[field] = value;
    }
    const correlationId = String(timing.correlation_id || '').trim();
    if (correlationId) result.correlation_id = correlationId;
    return result;
}

export function mergeRecognitionTiming(serverTiming = {}, clientTiming = {}) {
    const merged = {};
    const backendTotal = sanitizeTimingValue(
        serverTiming.backend_total_ms ?? serverTiming.total_ms,
    );
    if (backendTotal !== null) {
        merged.backend_total_ms = backendTotal;
        merged.total_ms = backendTotal;
    }
    for (const field of ['convert_ms', 'stt_ms', 'intent_ms', ...TIMING_FIELD_NAMES]) {
        const value = sanitizeTimingValue(serverTiming[field] ?? clientTiming[field]);
        if (value !== null) merged[field] = value;
    }
    const correlationId = String(serverTiming.correlation_id || clientTiming.correlation_id || '').trim();
    if (correlationId) merged.correlation_id = correlationId;
    return merged;
}
```

- [ ] **Step 5: Update `api.js`**

At the top of `pwa/js/api.js`, add:

```javascript
import { buildVoiceTimingFormFields, mergeRecognitionTiming } from './voice-helpers.mjs';
```

In `recognizeVoice(audioBlob, options = {})`, after existing context fields, add:

```javascript
    const timingFields = buildVoiceTimingFormFields(options.timing || {});
    for (const [key, value] of Object.entries(timingFields)) {
        formData.append(key, String(value));
    }
```

Replace the final return line:

```javascript
    return request('POST', '/voice/recognize', formData);
```

with:

```javascript
    const requestStartedAt = Date.now();
    const result = await request('POST', '/voice/recognize', formData);
    const clientTiming = {
        ...(options.timing || {}),
        pwa_request_ms: Date.now() - requestStartedAt,
    };
    if (result && typeof result === 'object') {
        result._timing = mergeRecognitionTiming(result._timing || {}, clientTiming);
    }
    return result;
```

- [ ] **Step 6: Run tests to verify green**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant"
npm run test:voice
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add "Mobile Picking und Voice Assistant/pwa/js/voice-helpers.mjs" `
        "Mobile Picking und Voice Assistant/pwa/js/api.js" `
        "Mobile Picking und Voice Assistant/pwa/js/tests/voice-helpers.test.mjs" `
        "Mobile Picking und Voice Assistant/pwa/js/tests/api.test.mjs"
git commit --only -m "feat(voice): add pwa recognition timing contract" -- `
        "Mobile Picking und Voice Assistant/pwa/js/voice-helpers.mjs" `
        "Mobile Picking und Voice Assistant/pwa/js/api.js" `
        "Mobile Picking und Voice Assistant/pwa/js/tests/voice-helpers.test.mjs" `
        "Mobile Picking und Voice Assistant/pwa/js/tests/api.test.mjs"
```

---

### Task 6: PWA Capture Timing and Mocked-STT Playwright Coverage

**Files:**
- Modify: `Mobile Picking und Voice Assistant/pwa/js/voice.js`
- Modify: `Mobile Picking und Voice Assistant/e2e/helpers/pwa-api.js`
- Create: `Mobile Picking und Voice Assistant/e2e/helpers/voice.js`
- Create: `Mobile Picking und Voice Assistant/e2e/voice-mocked-stt.spec.js`

**Interfaces:**
- Hands-free and push-to-talk calls pass `timing.capture_mode` and `timing.recording_ms`.
- Playwright tests exercise the real PWA push-to-talk recognition path with fake `MediaRecorder` and mocked `/api/voice/recognize`.

- [ ] **Step 1: Write the failing Playwright helper and spec**

Create `e2e/helpers/voice.js`:

```javascript
async function installFakePushToTalk(page) {
  await page.addInitScript(() => {
    class FakeMediaRecorder {
      static isTypeSupported() { return true; }

      constructor(stream, options = {}) {
        this.stream = stream;
        this.mimeType = options.mimeType || 'audio/webm;codecs=opus';
        this.state = 'inactive';
        this.ondataavailable = null;
        this.onstop = null;
      }

      start() {
        this.state = 'recording';
        window.setTimeout(() => {
          if (this.ondataavailable) {
            this.ondataavailable({
              data: new Blob(['voice'], { type: this.mimeType }),
            });
          }
        }, 20);
      }

      stop() {
        if (this.state !== 'recording') return;
        this.state = 'inactive';
        window.setTimeout(() => {
          if (this.onstop) this.onstop();
        }, 0);
      }
    }

    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: FakeMediaRecorder,
    });

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: async () => ({
          getTracks: () => [{ stop() {} }],
        }),
      },
    });
  });
}

async function runPushToTalk(page) {
  const button = page.locator('#btn-voice');
  await button.dispatchEvent('pointerdown');
  await page.waitForTimeout(450);
  await button.dispatchEvent('pointerup');
}

module.exports = {
  installFakePushToTalk,
  runPushToTalk,
};
```

Create `e2e/voice-mocked-stt.spec.js`:

```javascript
const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');
const { installFakePushToTalk, runPushToTalk } = require('./helpers/voice');

test('push-to-talk confirm goes through mocked STT and confirms exactly once', async ({ page }) => {
  await installFakePushToTalk(page);
  const api = await mockPwaApi(page, {
    voiceRecognitions: [
      {
        text: 'ja',
        intent: 'confirm',
        value: null,
        confidence: 0.95,
        normalized_text: 'ja',
        match_strategy: 'exact',
        _timing: { backend_total_ms: 120, total_ms: 120, convert_ms: 10, stt_ms: 100, intent_ms: 2 },
      },
    ],
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Lena Lager' }).click();
  await page.getByText('LEGO Ente').click();

  await runPushToTalk(page);

  expect(api.getConfirmCalls()).toBe(1);
  expect(api.getVoiceRecognizeCalls()).toBe(1);
  const fields = api.getLastVoiceRecognizeFields();
  expect(fields.context).toBe('awaiting_command');
  expect(fields.surface).toBe('detail');
  expect(fields.active_line_present).toBe('true');
  expect(fields.recording_ms).toBeTruthy();
});

test('short confirm feedback does not call backend Piper TTS', async ({ page }) => {
  await installFakePushToTalk(page);
  const api = await mockPwaApi(page, {
    voiceRecognitions: [
      {
        text: 'ja',
        intent: 'confirm',
        value: null,
        confidence: 0.95,
        normalized_text: 'ja',
        match_strategy: 'exact',
        _timing: { backend_total_ms: 120, total_ms: 120 },
      },
    ],
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Lena Lager' }).click();
  await page.getByText('LEGO Ente').click();

  await runPushToTalk(page);

  expect(api.getConfirmCalls()).toBe(1);
  expect(api.getVoiceTtsCalls()).toBe(0);
});
```

- [ ] **Step 2: Run Playwright to verify red**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant"
npx.cmd playwright test e2e/voice-mocked-stt.spec.js --project=mobile-chromium --reporter=list
```

Expected: FAIL because `mockPwaApi` does not handle `/api/voice/recognize` and does not expose voice call counters.

- [ ] **Step 3: Extend `mockPwaApi`**

In `e2e/helpers/pwa-api.js`, add this helper near the top:

```javascript
function extractMultipartFields(request) {
  const raw = request.postData() || '';
  const fields = {};
  for (const name of [
    'context',
    'surface',
    'remaining_line_count',
    'active_line_present',
    'capture_mode',
    'recording_ms',
    'speech_ms',
    'silence_wait_ms',
    'upload_ms',
    'correlation_id',
  ]) {
    const pattern = new RegExp(`name="${name}"\\r\\n\\r\\n([^\\r\\n]*)`);
    const match = pattern.exec(raw);
    if (match) fields[name] = match[1];
  }
  return fields;
}
```

Inside `mockPwaApi`, add state variables:

```javascript
  const voiceRecognitions = options.voiceRecognitions || [];
  let voiceRecognizeCalls = 0;
  let voiceTtsCalls = 0;
  let lastVoiceRecognizeFields = null;
```

Inside the route handler, before the final 404:

```javascript
    if (path === '/api/voice/recognize' && request.method() === 'POST') {
      lastVoiceRecognizeFields = extractMultipartFields(request);
      const response = voiceRecognitions[Math.min(voiceRecognizeCalls, voiceRecognitions.length - 1)] || {
        text: '',
        intent: 'unknown',
        value: null,
        confidence: 0,
        normalized_text: '',
        match_strategy: 'unknown',
        _timing: { backend_total_ms: 1, total_ms: 1 },
      };
      voiceRecognizeCalls += 1;
      return jsonResponse(route, 200, response);
    }

    if (path === '/api/voice/tts' && request.method() === 'POST') {
      voiceTtsCalls += 1;
      return route.fulfill({
        status: 200,
        contentType: 'audio/wav',
        body: Buffer.from('RIFF0000WAVE', 'ascii'),
      });
    }
```

Add returned accessors:

```javascript
    getVoiceRecognizeCalls() {
      return voiceRecognizeCalls;
    },
    getLastVoiceRecognizeFields() {
      return lastVoiceRecognizeFields;
    },
    getVoiceTtsCalls() {
      return voiceTtsCalls;
    },
```

- [ ] **Step 4: Add capture timing to `voice.js`**

In `startListeningCycle()`, when resolving a capture, include timing:

```javascript
            const stoppedAt = Date.now();
            resolve({
                blob: new Blob(audioChunks, { type: mimeType }),
                startedAt,
                generation: cycleGeneration,
                timing: {
                    capture_mode: 'hands_free',
                    recording_ms: stoppedAt - startedAt,
                    speech_ms,
                    silence_wait_ms: silenceStart ? Math.max(0, stoppedAt - silenceStart) : null,
                },
            });
```

When calling `recognizeVoice`, pass timing:

```javascript
            const result = await recognizeVoice(capture.blob, {
                ...getRecognitionOptions(),
                timing: capture.timing,
            });
```

In `startRecording()`, store a push-to-talk start timestamp:

```javascript
    const startedAt = Date.now();
```

In `stopRecording()`, resolve an object instead of only a blob:

```javascript
            const stoppedAt = Date.now();
            const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType });
            mediaRecorder.stream.getTracks().forEach((track) => track.stop());
            isRecording = false;
            setVoiceState('deactivate', { voiceModeActive: false });
            resolve({
                blob,
                timing: {
                    capture_mode: 'push_to_talk',
                    recording_ms: stoppedAt - startedAt,
                },
            });
```

In `captureAndRecognize().stop`, adjust:

```javascript
            const capture = await stopRecording();
            if (!capture?.blob) return { intent: 'unknown', text: '', confidence: 0 };
            try {
                return await recognizeVoice(capture.blob, {
                    ...getRecognitionOptions(),
                    timing: capture.timing,
                });
```

- [ ] **Step 5: Run tests to verify green**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant"
npm run test:voice
npx.cmd playwright test e2e/voice-mocked-stt.spec.js --project=mobile-chromium --reporter=list
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add "Mobile Picking und Voice Assistant/pwa/js/voice.js" `
        "Mobile Picking und Voice Assistant/e2e/helpers/pwa-api.js" `
        "Mobile Picking und Voice Assistant/e2e/helpers/voice.js" `
        "Mobile Picking und Voice Assistant/e2e/voice-mocked-stt.spec.js"
git commit --only -m "test(voice): add mocked stt playwright coverage" -- `
        "Mobile Picking und Voice Assistant/pwa/js/voice.js" `
        "Mobile Picking und Voice Assistant/e2e/helpers/pwa-api.js" `
        "Mobile Picking und Voice Assistant/e2e/helpers/voice.js" `
        "Mobile Picking und Voice Assistant/e2e/voice-mocked-stt.spec.js"
```

---

### Task 7: Local LLM Shadow Scaffold

**Files:**
- Modify: `Mobile Picking und Voice Assistant/backend/app/config.py`
- Create: `Mobile Picking und Voice Assistant/backend/app/models/voice_llm.py`
- Create: `Mobile Picking und Voice Assistant/backend/app/services/voice_llm.py`
- Modify: `Mobile Picking und Voice Assistant/backend/app/dependencies.py`
- Modify: `Mobile Picking und Voice Assistant/backend/app/routers/voice.py`
- Test: `Mobile Picking und Voice Assistant/backend/tests/test_voice_llm.py`
- Test: `Mobile Picking und Voice Assistant/backend/tests/test_voice_routes.py`

**Interfaces:**
- Defaults:
  - `pwr_voice_llm_shadow = False`
  - `pwr_voice_llm_active = False`
  - `pwr_voice_llm_model = ""`
- LLM candidate schema allows only assist-safe intents/actions.
- `/api/voice/recognize` response remains deterministic and unchanged by shadow mode.

- [ ] **Step 1: Write failing LLM unit tests**

Create `backend/tests/test_voice_llm.py`:

```python
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models.voice_llm import VoiceLLMCandidate
from app.services.voice_llm import OllamaVoiceLLMClient


def test_voice_llm_settings_default_off(monkeypatch):
    for key in (
        "PWR_VOICE_V2_ENABLED",
        "PWR_VOICE_LLM_SHADOW",
        "PWR_VOICE_LLM_ACTIVE",
        "PWR_VOICE_LLM_URL",
        "PWR_VOICE_LLM_MODEL",
        "PWR_VOICE_LLM_TIMEOUT_MS",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None)
    assert settings.pwr_voice_v2_enabled is False
    assert settings.pwr_voice_llm_shadow is False
    assert settings.pwr_voice_llm_active is False
    assert settings.pwr_voice_llm_url == "http://ollama:11434"
    assert settings.pwr_voice_llm_model == ""
    assert settings.pwr_voice_llm_timeout_ms == 1200


def test_candidate_rejects_unknown_intent_candidate():
    with pytest.raises(ValidationError):
        VoiceLLMCandidate.model_validate({
            "status": "ok",
            "intent_candidate": "confirm",
            "action": "none",
            "tts_text": "",
            "confidence": 0.9,
        })


def test_candidate_rejects_ids_outside_context():
    with pytest.raises(ValidationError):
        VoiceLLMCandidate.model_validate(
            {
                "status": "ok",
                "intent_candidate": "stock_query",
                "action": "explain_context",
                "tts_text": "Bestand erklaert.",
                "confidence": 0.9,
                "referenced_product_id": 99,
            },
            context={"allowed_product_ids": {5}, "allowed_location_ids": set(), "min_confidence": 0.7},
        )


def test_candidate_rejects_direct_write_instruction():
    with pytest.raises(ValidationError):
        VoiceLLMCandidate.model_validate(
            {
                "status": "ok",
                "intent_candidate": "problem",
                "action": "suggest_replenishment",
                "tts_text": "Ich schreibe direkt in Odoo.",
                "confidence": 0.95,
            },
            context={"allowed_product_ids": set(), "allowed_location_ids": set(), "min_confidence": 0.7},
        )


@pytest.mark.anyio
async def test_ollama_disabled_returns_not_enabled(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "pwr_voice_v2_enabled", False, raising=False)
    monkeypatch.setattr(config.settings, "pwr_voice_llm_shadow", False, raising=False)
    monkeypatch.setattr(config.settings, "pwr_voice_llm_model", "", raising=False)
    client = OllamaVoiceLLMClient()
    result = await client.propose_shadow(text="was ist offen", deterministic_intent="unknown", context={})
    assert result.status == "disabled"
    assert result.fallback_reason == "disabled"


@pytest.mark.anyio
async def test_ollama_timeout_returns_fallback(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "pwr_voice_v2_enabled", True, raising=False)
    monkeypatch.setattr(config.settings, "pwr_voice_llm_shadow", True, raising=False)
    monkeypatch.setattr(config.settings, "pwr_voice_llm_model", "llama3.2", raising=False)
    client = OllamaVoiceLLMClient()
    client._client.post = AsyncMock(side_effect=httpx.TimeoutException("slow"))
    result = await client.propose_shadow(text="was ist offen", deterministic_intent="unknown", context={})
    assert result.status == "fallback"
    assert result.fallback_reason == "timeout"
```

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant\backend"
$env:PYTHONPATH = ".deps;."
python -m pytest -p pytest_asyncio tests/test_voice_llm.py -q
```

Expected: FAIL because config fields, models, and service do not exist.

- [ ] **Step 3: Add config flags**

In `backend/app/config.py`, inside `class Settings`, add these fields if Task 4 did not already add the first one:

```python
    pwr_voice_v2_enabled: bool = False
    pwr_voice_llm_shadow: bool = False
    pwr_voice_llm_active: bool = False
    pwr_voice_llm_url: str = "http://ollama:11434"
    pwr_voice_llm_model: str = ""
    pwr_voice_llm_timeout_ms: int = 1200
    pwr_voice_llm_max_concurrency: int = 1
    pwr_voice_llm_min_confidence: float = 0.70
```

- [ ] **Step 4: Add LLM model schema**

Create `backend/app/models/voice_llm.py`:

```python
"""Strict schema for local voice LLM shadow candidates."""
from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

_WRITE_TERMS = ("write", "execute_kw", "unlink", "create(", "direkt in odoo", "bestaetige", "confirm")


class VoiceLLMCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "fallback"]
    intent_candidate: Literal["stock_query", "problem", "unknown", "none"]
    action: Literal["none", "explain_context", "suggest_replenishment", "ask_supervisor"]
    tts_text: str = Field(max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)
    referenced_product_id: int | None = None
    referenced_location_id: int | None = None
    recommendation: dict[str, Any] | None = None

    @model_validator(mode="after")
    def enforce_voice_policy(self, info: ValidationInfo) -> Self:
        context = info.context or {}
        min_confidence = float(context.get("min_confidence", 0.0))
        if self.confidence < min_confidence:
            raise ValueError("confidence below configured minimum")

        allowed_product_ids = set(context.get("allowed_product_ids") or [])
        allowed_location_ids = set(context.get("allowed_location_ids") or [])
        if self.referenced_product_id is not None and self.referenced_product_id not in allowed_product_ids:
            raise ValueError("referenced_product_id is outside request context")
        if self.referenced_location_id is not None and self.referenced_location_id not in allowed_location_ids:
            raise ValueError("referenced_location_id is outside request context")

        payload_text = f"{self.tts_text} {self.recommendation or ''}".lower()
        if any(term in payload_text for term in _WRITE_TERMS):
            raise ValueError("candidate contains direct write instruction")
        return self


class VoiceLLMShadowResult(BaseModel):
    status: Literal["disabled", "ok", "fallback"]
    fallback_reason: str | None = None
    candidate: VoiceLLMCandidate | None = None
    latency_ms: int = 0
```

- [ ] **Step 5: Add Ollama shadow service**

Create `backend/app/services/voice_llm.py`:

```python
"""Local LLM shadow adapter for PWR Voice v2."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import settings
from app.models.voice_llm import VoiceLLMCandidate, VoiceLLMShadowResult

logger = logging.getLogger(__name__)


class OllamaVoiceLLMClient:
    def __init__(self):
        self._client = httpx.AsyncClient(
            timeout=max(0.1, settings.pwr_voice_llm_timeout_ms / 1000),
            limits=httpx.Limits(max_connections=max(1, settings.pwr_voice_llm_max_concurrency)),
        )
        self._semaphore = asyncio.Semaphore(max(1, settings.pwr_voice_llm_max_concurrency))

    def is_shadow_enabled(self) -> bool:
        return (
            settings.pwr_voice_v2_enabled
            and settings.pwr_voice_llm_shadow
            and bool((settings.pwr_voice_llm_model or "").strip())
        )

    async def propose_shadow(
        self,
        *,
        text: str,
        deterministic_intent: str,
        context: dict[str, Any],
    ) -> VoiceLLMShadowResult:
        if not self.is_shadow_enabled():
            return VoiceLLMShadowResult(status="disabled", fallback_reason="disabled")

        started_at = time.monotonic()
        try:
            async with self._semaphore:
                response = await self._client.post(
                    f"{settings.pwr_voice_llm_url.rstrip('/')}/api/generate",
                    json={
                        "model": settings.pwr_voice_llm_model,
                        "prompt": json.dumps(
                            {
                                "task": "Classify this German warehouse voice request for assist only.",
                                "text": text,
                                "deterministic_intent": deterministic_intent,
                                "context": context,
                            },
                            ensure_ascii=False,
                        ),
                        "stream": False,
                        "format": VoiceLLMCandidate.model_json_schema(),
                        "options": {"temperature": 0},
                    },
                )
            response.raise_for_status()
            payload = response.json()
            raw_candidate = payload.get("response") or "{}"
            candidate_data = json.loads(raw_candidate) if isinstance(raw_candidate, str) else raw_candidate
            candidate = VoiceLLMCandidate.model_validate(
                candidate_data,
                context={
                    "allowed_product_ids": set(context.get("allowed_product_ids") or []),
                    "allowed_location_ids": set(context.get("allowed_location_ids") or []),
                    "min_confidence": settings.pwr_voice_llm_min_confidence,
                },
            )
            latency_ms = round((time.monotonic() - started_at) * 1000)
            logger.info(
                "Voice LLM shadow: deterministic=%s candidate=%s action=%s conf=%.2f latency=%dms",
                deterministic_intent,
                candidate.intent_candidate,
                candidate.action,
                candidate.confidence,
                latency_ms,
            )
            return VoiceLLMShadowResult(status="ok", candidate=candidate, latency_ms=latency_ms)
        except httpx.TimeoutException:
            return VoiceLLMShadowResult(status="fallback", fallback_reason="timeout")
        except (httpx.HTTPError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            logger.info("Voice LLM shadow fallback: %s: %s", type(exc).__name__, exc)
            return VoiceLLMShadowResult(status="fallback", fallback_reason="schema_invalid")
```

- [ ] **Step 6: Add dependency**

In `backend/app/dependencies.py`, import and add:

```python
from app.services.voice_llm import OllamaVoiceLLMClient
```

```python
@lru_cache()
def get_voice_llm_client() -> OllamaVoiceLLMClient:
    return OllamaVoiceLLMClient()
```

- [ ] **Step 7: Wire shadow task without changing recognition response**

In `backend/app/routers/voice.py`, import:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
```

Add dependency import:

```python
from app.dependencies import get_n8n_client, get_odoo_client, get_picking_service, get_request_odoo_client, get_voice_llm_client, get_write_request_context
```

Add service import:

```python
from app.services.voice_llm import OllamaVoiceLLMClient
```

In `recognize_speech(...)`, place `background_tasks` before parameters with defaults, and add the LLM dependency after the form fields:

```python
    background_tasks: BackgroundTasks,
```

```python
    voice_llm: OllamaVoiceLLMClient = Depends(get_voice_llm_client),
```

Before returning the deterministic payload, add:

```python
    if voice_llm.is_shadow_enabled():
        background_tasks.add_task(
            voice_llm.propose_shadow,
            text=intent.raw_text,
            deterministic_intent=intent.action,
            context={
                "surface": ui_surface.value,
                "remaining_line_count": remaining_line_count,
                "active_line_present": active_line_present,
                "allowed_product_ids": [],
                "allowed_location_ids": [],
                "correlation_id": timing.get("correlation_id"),
            },
        )
```

Do not add `llm_*` fields to the response.

- [ ] **Step 8: Add route regression tests**

Append to `backend/tests/test_voice_routes.py`:

```python
class FakeVoiceLLM:
    def __init__(self, enabled):
        self.enabled = enabled
        self.calls = []

    def is_shadow_enabled(self):
        return self.enabled

    async def propose_shadow(self, **kwargs):
        self.calls.append(kwargs)


def test_voice_recognize_does_not_call_llm_when_defaults_off(monkeypatch):
    monkeypatch.setattr(voice_router, "convert_to_wav", AsyncMock(return_value=b"wav-bytes"))
    monkeypatch.setattr(voice_router.whisper_client, "transcribe_audio", AsyncMock(return_value="ja"))
    fake_llm = FakeVoiceLLM(enabled=False)
    from app.dependencies import get_voice_llm_client

    app.dependency_overrides[get_voice_llm_client] = lambda: fake_llm
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/voice/recognize",
                data={"surface": "detail", "active_line_present": "true"},
                files={"audio": ("voice.webm", b"1234", "audio/webm")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["intent"] == "confirm"
    assert fake_llm.calls == []


def test_voice_recognize_shadow_keeps_deterministic_response(monkeypatch):
    monkeypatch.setattr(voice_router, "convert_to_wav", AsyncMock(return_value=b"wav-bytes"))
    monkeypatch.setattr(voice_router.whisper_client, "transcribe_audio", AsyncMock(return_value="ja"))
    fake_llm = FakeVoiceLLM(enabled=True)
    from app.dependencies import get_voice_llm_client

    app.dependency_overrides[get_voice_llm_client] = lambda: fake_llm
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/voice/recognize",
                data={"surface": "detail", "active_line_present": "true", "correlation_id": "corr-shadow"},
                files={"audio": ("voice.webm", b"1234", "audio/webm")},
            )
    finally:
        app.dependency_overrides.clear()

    payload = response.json()
    assert payload["intent"] == "confirm"
    assert "llm_intent_candidate" not in payload
    assert fake_llm.calls[0]["deterministic_intent"] == "confirm"
    assert fake_llm.calls[0]["context"]["correlation_id"] == "corr-shadow"
```

- [ ] **Step 9: Run tests to verify green**

Run:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant\backend"
$env:PYTHONPATH = ".deps;."
python -m pytest -p pytest_asyncio tests/test_voice_llm.py tests/test_voice_routes.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```powershell
git add "Mobile Picking und Voice Assistant/backend/app/config.py" `
        "Mobile Picking und Voice Assistant/backend/app/models/voice_llm.py" `
        "Mobile Picking und Voice Assistant/backend/app/services/voice_llm.py" `
        "Mobile Picking und Voice Assistant/backend/app/dependencies.py" `
        "Mobile Picking und Voice Assistant/backend/app/routers/voice.py" `
        "Mobile Picking und Voice Assistant/backend/tests/test_voice_llm.py" `
        "Mobile Picking und Voice Assistant/backend/tests/test_voice_routes.py"
git commit --only -m "feat(voice): add local llm shadow scaffold behind flags" -- `
        "Mobile Picking und Voice Assistant/backend/app/config.py" `
        "Mobile Picking und Voice Assistant/backend/app/models/voice_llm.py" `
        "Mobile Picking und Voice Assistant/backend/app/services/voice_llm.py" `
        "Mobile Picking und Voice Assistant/backend/app/dependencies.py" `
        "Mobile Picking und Voice Assistant/backend/app/routers/voice.py" `
        "Mobile Picking und Voice Assistant/backend/tests/test_voice_llm.py" `
        "Mobile Picking und Voice Assistant/backend/tests/test_voice_routes.py"
```

---

## Final Verification

After all tasks:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant\backend"
$env:PYTHONPATH = ".deps;."
python -m pytest -p pytest_asyncio tests/test_voice_routes.py tests/test_voice_corpus.py tests/test_voice_eval_routes.py tests/test_voice_llm.py tests/test_voice_eval_odoo_models_static.py -q
```

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant"
npm run test:voice
npx.cmd playwright test e2e/voice-mocked-stt.spec.js e2e/voice-commands.spec.js --project=mobile-chromium --reporter=list
```

If the branch is clean enough to run the wider gates:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant\backend"
$env:PYTHONPATH = ".deps;."
python -m pytest -p pytest_asyncio tests -q
```

## Handoff Notes

- Active LLM fallback needs its own plan after shadow metrics exist.
- Fake microphone audio-file smoke needs its own plan because it introduces browser launch config and audio fixture management.
- Confirm-line/Odoo performance optimization needs its own plan after evaluation data identifies the real p95 contributors.
- Push only after the mixed worktree is resolved and the scoped commits are reviewed.
