# Voice Track 1 — LLM Intent Fallback (Phase B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the deterministic engine can't place an utterance, a local Ollama model classifies it into a known intent — safely (writes always read-back) and without slowing the common commands.

**Architecture:** New `VoiceIntentClassifier` (mirrors `LlmClient`) calls Ollama. The router calls it only when the deterministic result is `unknown` or `<0.73`. The LLM label is finalized through a new public `finalize_external_intent` in `intent_engine.py` that reuses the existing negation guard + surface gating and clamps write-intent confidence.

**Tech Stack:** Python 3 / FastAPI, httpx, Ollama (`/api/chat`, `format:"json"`), pytest.

## Global Constraints

- Backend test command: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q` — baseline **296/296 must stay green**.
- Deterministic engine stays primary; LLM is fallback only.
- LLM writes must never book directly: clamp write-intent confidence to `LLM_WRITE_CONFIDENCE_CAP = 0.85` (< the frontend 0.90 direct threshold).
- Any classifier error/timeout/invalid output → `ok=False` → deterministic result stands.
- Reuse `settings.llm_endpoint`. New settings: `llm_voice_model = "qwen2.5:1.5b"`, `llm_voice_timeout_ms = 4000`.
- Allowed intent labels = `{"confirm","confirm_all","next","previous","next_order","problem","photo","pause","done","whats_next","where","how_many_left","status","repeat","help"}`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `backend/app/config.py` | settings | add `llm_voice_model`, `llm_voice_timeout_ms` |
| `backend/app/services/intent_engine.py` | intent vocabulary + finalize | add `EXTERNAL_INTENT_LABELS`, `LLM_WRITE_CONFIDENCE_CAP`, `finalize_external_intent()` |
| `backend/app/services/voice_intent_classifier.py` | Ollama call | new |
| `backend/app/routers/voice.py` | wire fallback into `/voice/recognize` | modify |
| `backend/tests/test_intent_engine.py` | finalize tests | add |
| `backend/tests/test_voice_intent_classifier.py` | classifier unit | new |
| `backend/tests/test_voice_llm_fallback.py` | router integration | new |
| `Mobile Picking und Voice Assistant/README` or docs | ops note | add `ollama pull` step |

---

## Task 1: Config settings for the voice model

**Files:**
- Modify: `backend/app/config.py` (near `llm_model` line ~38)
- Test: `backend/tests/test_voice_intent_classifier.py` (created in Task 3; config asserted there indirectly). For this task, a direct import check.

**Interfaces:**
- Produces: `settings.llm_voice_model: str`, `settings.llm_voice_timeout_ms: int`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_config_voice.py
from app.config import settings

def test_voice_model_settings_exist():
    assert settings.llm_voice_model == "qwen2.5:1.5b"
    assert settings.llm_voice_timeout_ms == 4000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_config_voice.py -q`
Expected: FAIL — attributes do not exist.

- [ ] **Step 3: Write minimal implementation**

In `config.py`, after `llm_timeout_ms: int = 30000`:

```python
    # Kleines, schnelles Modell nur fuer Voice-Intent-Fallback (nicht Qualitaet).
    llm_voice_model: str = "qwen2.5:1.5b"
    llm_voice_timeout_ms: int = 4000
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_config_voice.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add "Mobile Picking und Voice Assistant/backend/app/config.py" "Mobile Picking und Voice Assistant/backend/tests/test_config_voice.py"
git commit -m "feat(voice): add llm_voice_model/llm_voice_timeout_ms settings"
```

---

## Task 2: finalize_external_intent in intent_engine

**Files:**
- Modify: `backend/app/services/intent_engine.py`
- Test: `backend/tests/test_intent_engine.py`

**Interfaces:**
- Consumes: existing `WRITE_ACTIONS`, `_apply_negation_guard`, `_resolve_with_context`, `_unknown_intent`, `Intent`, `VoiceSurface`, `normalize_text`.
- Produces:
  - `EXTERNAL_INTENT_LABELS: frozenset[str]` (the allowed labels).
  - `LLM_WRITE_CONFIDENCE_CAP: float = 0.85`.
  - `finalize_external_intent(action, confidence, *, raw_text, normalized_text, surface, remaining_line_count, active_line_present) -> Intent`.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_intent_engine.py
from app.services.intent_engine import finalize_external_intent, EXTERNAL_INTENT_LABELS

class TestFinalizeExternalIntent:
    def _finalize(self, action, confidence, text, **kw):
        params = dict(
            raw_text=text, normalized_text=normalize_text(text),
            surface=VoiceSurface.DETAIL, remaining_line_count=1, active_line_present=True,
        )
        params.update(kw)
        return finalize_external_intent(action, confidence, **params)

    def test_unknown_label_becomes_unknown(self):
        assert self._finalize("teleport", 0.9, "beam mich hoch").action == "unknown"

    def test_write_confidence_is_clamped(self):
        intent = self._finalize("confirm", 0.99, "jawohl bitte")
        assert intent.action == "confirm"
        assert intent.confidence <= 0.85

    def test_non_write_confidence_not_clamped(self):
        intent = self._finalize("next", 0.95, "geh weiter")
        assert intent.action == "next"
        assert intent.confidence == 0.95

    def test_negation_downgrades_llm_confirm(self):
        assert self._finalize("confirm", 0.99, "nicht ok").action == "problem"

    def test_surface_gating_applies(self):
        intent = self._finalize("confirm", 0.99, "jawohl", surface=VoiceSurface.LIST, active_line_present=False)
        assert intent.action == "unknown"

    def test_labels_cover_the_engine_actions(self):
        assert "confirm" in EXTERNAL_INTENT_LABELS
        assert "whats_next" in EXTERNAL_INTENT_LABELS
```

Note: `normalize_text` and `VoiceSurface` are already imported at the top of `test_intent_engine.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_intent_engine.py::TestFinalizeExternalIntent -q`
Expected: FAIL — `finalize_external_intent`/`EXTERNAL_INTENT_LABELS` not defined.

- [ ] **Step 3: Write minimal implementation**

Add near `WRITE_ACTIONS` (after `_apply_negation_guard`):

```python
EXTERNAL_INTENT_LABELS = frozenset({
    "confirm", "confirm_all", "next", "previous", "next_order", "problem",
    "photo", "pause", "done", "whats_next", "where", "how_many_left",
    "status", "repeat", "help",
})
LLM_WRITE_CONFIDENCE_CAP = 0.85


def finalize_external_intent(
    action: str,
    confidence: float,
    *,
    raw_text: str,
    normalized_text: str,
    surface: VoiceSurface,
    remaining_line_count: int,
    active_line_present: bool,
) -> Intent:
    """Run an externally produced (LLM) label through the same safeguards as a
    deterministic match: reject unknown labels, clamp write confidence so writes
    always read-back downstream, apply the negation guard, then surface gating.
    """
    if action not in EXTERNAL_INTENT_LABELS:
        return _unknown_intent(raw_text, normalized_text)
    conf = max(0.0, min(1.0, float(confidence)))
    if action in WRITE_ACTIONS:
        conf = min(conf, LLM_WRITE_CONFIDENCE_CAP)
    intent = Intent(
        action=action,
        value=None,
        confidence=conf,
        raw_text=raw_text,
        normalized_text=normalized_text,
        match_strategy="llm",
    )
    intent = _apply_negation_guard(intent, normalized_text)
    return _resolve_with_context(
        intent,
        surface=surface,
        remaining_line_count=remaining_line_count,
        active_line_present=active_line_present,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_intent_engine.py -q`
Expected: PASS.

- [ ] **Step 5: Run full backend suite**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add "Mobile Picking und Voice Assistant/backend/app/services/intent_engine.py" "Mobile Picking und Voice Assistant/backend/tests/test_intent_engine.py"
git commit -m "feat(voice): finalize_external_intent reuses guards + clamps LLM writes"
```

---

## Task 3: VoiceIntentClassifier service

**Files:**
- Create: `backend/app/services/voice_intent_classifier.py`
- Test: `backend/tests/test_voice_intent_classifier.py`

**Interfaces:**
- Consumes: `EXTERNAL_INTENT_LABELS` from intent_engine.
- Produces:
  - `VoiceIntentResult` dataclass: `ok: bool, model: str, intent: str | None, confidence: float | None`.
  - `VoiceIntentClassifier(*, endpoint, model, timeout_ms=4000, transport=None)` with `async def classify(self, text) -> VoiceIntentResult`.
  - `get_classifier() -> VoiceIntentClassifier` module singleton reading `settings`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_voice_intent_classifier.py
import json
import httpx
import pytest

from app.services.voice_intent_classifier import VoiceIntentClassifier, VoiceIntentResult


def _transport(handler):
    return httpx.MockTransport(handler)


def _ok_response(content: dict):
    def handler(request):
        return httpx.Response(200, json={"message": {"content": json.dumps(content)}})
    return _transport(handler)


@pytest.mark.asyncio
async def test_valid_intent_parsed():
    clf = VoiceIntentClassifier(endpoint="http://ollama:11434", model="m",
                                transport=_ok_response({"intent": "next", "confidence": 0.8}))
    result = await clf.classify("mach mal weiter irgendwie")
    assert result == VoiceIntentResult(ok=True, model="m", intent="next", confidence=0.8)


@pytest.mark.asyncio
async def test_unknown_label_is_not_ok():
    clf = VoiceIntentClassifier(endpoint="http://o", model="m",
                                transport=_ok_response({"intent": "teleport", "confidence": 0.9}))
    result = await clf.classify("beam mich hoch")
    assert result.ok is False


@pytest.mark.asyncio
async def test_garbage_content_is_not_ok():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": "not json"}})
    clf = VoiceIntentClassifier(endpoint="http://o", model="m", transport=_transport(handler))
    result = await clf.classify("xyz")
    assert result.ok is False


@pytest.mark.asyncio
async def test_http_error_is_not_ok():
    def handler(request):
        return httpx.Response(500)
    clf = VoiceIntentClassifier(endpoint="http://o", model="m", transport=_transport(handler))
    result = await clf.classify("xyz")
    assert result.ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_voice_intent_classifier.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/voice_intent_classifier.py
"""Lokaler LLM-Fallback fuer die Voice-Intent-Erkennung (Ollama).

Wird nur gerufen, wenn die deterministische Erkennung nichts Sicheres liefert.
Jeder Fehler/Timeout/ungueltige Antwort => ok=False, damit der Aufrufer sauber
auf das deterministische Ergebnis zurueckfaellt.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from app.config import settings
from app.services.intent_engine import EXTERNAL_INTENT_LABELS

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Du ordnest eine deutsche Sprachaeusserung eines Lager-Kommissionierers genau "
    "einem Befehl zu. Erlaubte Befehle: "
    "confirm (Position bestaetigen), confirm_all (ganzen Auftrag buchen), "
    "next (naechste Position), previous (zurueck), next_order (naechster Auftrag), "
    "problem (Stoerung/Fehler melden), photo (Foto), pause, done (fertig), "
    "whats_next (was jetzt/was picken), where (wo/welcher Platz), "
    "how_many_left (wie viele noch), status, repeat (wiederholen), help. "
    "Bei Verneinung (nicht, kein, nein) niemals confirm. Wenn unklar: unknown. "
    'Antworte ausschliesslich mit JSON {"intent": <befehl|unknown>, "confidence": <0..1>}.'
)


@dataclass(frozen=True)
class VoiceIntentResult:
    ok: bool
    model: str
    intent: str | None = None
    confidence: float | None = None


class VoiceIntentClassifier:
    def __init__(self, *, endpoint: str, model: str, timeout_ms: int = 4000,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        seconds = max(1.0, timeout_ms / 1000.0)
        self._timeout = httpx.Timeout(connect=3.0, read=seconds, write=5.0, pool=3.0)
        self._transport = transport

    async def classify(self, text: str) -> VoiceIntentResult:
        payload = {
            "model": self._model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": (text or "").strip()},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(f"{self._endpoint}/api/chat", json=payload)
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content")
            return self._parse(content)
        except Exception as exc:  # noqa: BLE001 - jeder Fehler => Fallback
            logger.warning(json.dumps({"event_type": "voice_intent_llm_failed", "error": str(exc)}))
            return VoiceIntentResult(ok=False, model=self._model)

    def _parse(self, content: str | None) -> VoiceIntentResult:
        if not content or not isinstance(content, str):
            return VoiceIntentResult(ok=False, model=self._model)
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            return VoiceIntentResult(ok=False, model=self._model)
        if not isinstance(parsed, dict):
            return VoiceIntentResult(ok=False, model=self._model)
        intent = str(parsed.get("intent", "")).strip().lower()
        if intent not in EXTERNAL_INTENT_LABELS:
            return VoiceIntentResult(ok=False, model=self._model)
        try:
            confidence = max(0.0, min(1.0, round(float(parsed.get("confidence")), 2)))
        except (TypeError, ValueError):
            return VoiceIntentResult(ok=False, model=self._model)
        return VoiceIntentResult(ok=True, model=self._model, intent=intent, confidence=confidence)


_classifier: VoiceIntentClassifier | None = None


def get_classifier() -> VoiceIntentClassifier:
    global _classifier
    if _classifier is None:
        _classifier = VoiceIntentClassifier(
            endpoint=settings.llm_endpoint,
            model=settings.llm_voice_model,
            timeout_ms=settings.llm_voice_timeout_ms,
        )
    return _classifier
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_voice_intent_classifier.py -q`
Expected: PASS.

- [ ] **Step 5: Run full backend suite**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add "Mobile Picking und Voice Assistant/backend/app/services/voice_intent_classifier.py" "Mobile Picking und Voice Assistant/backend/tests/test_voice_intent_classifier.py"
git commit -m "feat(voice): add Ollama VoiceIntentClassifier with fail-closed fallback"
```

---

## Task 4: Wire the LLM fallback into /voice/recognize

**Files:**
- Modify: `backend/app/routers/voice.py` (after the segment fallback block, ~line 278-288)
- Test: `backend/tests/test_voice_llm_fallback.py` (new)

**Interfaces:**
- Consumes: `get_classifier` (Task 3), `finalize_external_intent`, `FUZZY_SINGLE_THRESHOLD` (already imported).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_voice_llm_fallback.py
import io
import pytest
from httpx import AsyncClient, ASGITransport

import app.routers.voice as voice_router
from app.main import app
from app.services.voice_intent_classifier import VoiceIntentResult


class _SpyClassifier:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def classify(self, text):
        self.calls += 1
        return self.result


def _wav_bytes():
    return b"RIFF....WAVEfmt "  # content irrelevant; whisper is monkeypatched


async def _post(text_for_whisper, monkeypatch, classifier, **form):
    async def fake_transcribe(audio_bytes, mime_type="audio/wav"):
        return text_for_whisper
    monkeypatch.setattr(voice_router.whisper_client, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(voice_router, "get_classifier", lambda: classifier)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        files = {"audio": ("a.wav", io.BytesIO(_wav_bytes()), "audio/wav")}
        data = {"context": "awaiting_command", "surface": "detail",
                "remaining_line_count": "2", "active_line_present": "true"}
        data.update(form)
        return await client.post("/voice/recognize", files=files, data=data)


@pytest.mark.asyncio
async def test_llm_fills_unknown(monkeypatch):
    spy = _SpyClassifier(VoiceIntentResult(ok=True, model="m", intent="next", confidence=0.8))
    resp = await _post("bewege dich mal vorwaerts irgendwie", monkeypatch, spy)
    body = resp.json()
    assert body["intent"] == "next"
    assert body["match_strategy"] == "llm"
    assert spy.calls == 1


@pytest.mark.asyncio
async def test_llm_confirm_is_confidence_capped(monkeypatch):
    spy = _SpyClassifier(VoiceIntentResult(ok=True, model="m", intent="confirm", confidence=0.99))
    resp = await _post("das kannst du gerne so uebernehmen", monkeypatch, spy)
    body = resp.json()
    assert body["intent"] == "confirm"
    assert body["confidence"] <= 0.85


@pytest.mark.asyncio
async def test_llm_not_called_on_confident_match(monkeypatch):
    spy = _SpyClassifier(VoiceIntentResult(ok=True, model="m", intent="next", confidence=0.9))
    resp = await _post("bestaetigen", monkeypatch, spy)
    body = resp.json()
    assert body["intent"] == "confirm"
    assert spy.calls == 0


@pytest.mark.asyncio
async def test_llm_failure_keeps_unknown(monkeypatch):
    spy = _SpyClassifier(VoiceIntentResult(ok=False, model="m"))
    resp = await _post("voelliger unsinn ohne befehl", monkeypatch, spy)
    body = resp.json()
    assert body["intent"] == "unknown"
    assert spy.calls == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_voice_llm_fallback.py -q`
Expected: FAIL — router does not call the classifier; `match_strategy` never `"llm"`.

- [ ] **Step 3: Write minimal implementation**

Add imports to `voice.py`:

```python
from app.services.intent_engine import finalize_external_intent  # add to existing intent_engine import group
from app.services.voice_intent_classifier import get_classifier
```

Insert the LLM fallback in `recognize_speech`, immediately after the existing segment-fallback block (after the `if seg.confidence > intent.confidence: intent = seg` lines) and before the recovery-dialog block:

```python
    # LLM fallback: only when the deterministic engine is still unsure. Runs the
    # LLM label through the same guards (negation, surface gating, write clamp)
    # as a deterministic match. Any failure keeps the deterministic result.
    if intent.action == "unknown" or intent.confidence < FUZZY_SINGLE_THRESHOLD:
        llm = await get_classifier().classify(text)
        if llm.ok and llm.intent is not None:
            candidate = finalize_external_intent(
                llm.intent,
                llm.confidence or 0.0,
                raw_text=text,
                normalized_text=intent.normalized_text or text,
                surface=ui_surface,
                remaining_line_count=remaining_line_count,
                active_line_present=active_line_present,
            )
            if candidate.action != "unknown" and candidate.confidence > intent.confidence:
                intent = candidate
```

`normalized_text`: when the deterministic result was `unknown`, `intent.normalized_text` is already the normalized transcript (see `_unknown_intent`), so it is safe to reuse for the negation guard.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_voice_llm_fallback.py -q`
Expected: PASS.

- [ ] **Step 5: Run full backend suite**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add "Mobile Picking und Voice Assistant/backend/app/routers/voice.py" "Mobile Picking und Voice Assistant/backend/tests/test_voice_llm_fallback.py"
git commit -m "feat(voice): LLM fallback in /voice/recognize for unsure utterances"
```

---

## Task 5: Ops note — pull the voice model

**Files:**
- Modify: `Mobile Picking und Voice Assistant/README.md` (or the infra/ops doc if one is canonical)

**Interfaces:** none (documentation only).

- [ ] **Step 1: Add the ops note**

Add a short subsection under the setup/LLM section:

```markdown
### Voice LLM fallback (optional)

The voice assistant classifies unclear commands with a small local model. Pull it
once into the Ollama container:

    docker compose exec ollama ollama pull qwen2.5:1.5b

Without it the classifier fails closed and voice stays fully deterministic
(no LLM safety net). Configure via `LLM_VOICE_MODEL` / `LLM_VOICE_TIMEOUT_MS`.
```

- [ ] **Step 2: Verify markdown renders (no broken fences)**

Run: `grep -n "ollama pull qwen2.5:1.5b" "Mobile Picking und Voice Assistant/README.md"`
Expected: the line is present.

- [ ] **Step 3: Commit**

```bash
git add "Mobile Picking und Voice Assistant/README.md"
git commit -m "docs: note ollama pull step for voice intent fallback"
```

---

## Final verification

- [ ] Backend: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q` → green (296 + new).
- [ ] `python -c "import app.routers.voice"` under PYTHONPATH=.deps → imports cleanly.
- [ ] Live smoke (stack up, after `ollama pull`): speak an off-script phrase ("beweg dich mal weiter") → recognized as `next` via `match_strategy=llm`; an off-script confirm ("das passt so für mich") → read-back prompt (never direct book).

---

## Self-Review (author checklist — completed)

- **Spec coverage:** trigger (T4), classifier fail-closed (T3), finalize with negation/surface/write-clamp (T2), config (T1), latency via timeout (T3 timeout + T4 only-when-unsure), tests at unit + integration, ops pull step (T5). All spec sections mapped.
- **Placeholder scan:** none — concrete code in every step.
- **Type consistency:** `VoiceIntentResult(ok, model, intent, confidence)` identical across T3 def and T4 use; `finalize_external_intent(action, confidence, *, raw_text, normalized_text, surface, remaining_line_count, active_line_present)` identical across T2 def and T4 call; `EXTERNAL_INTENT_LABELS` defined T2, consumed T3.
- **Ordering:** T1 (settings) → T2 (labels+finalize) → T3 (classifier imports labels) → T4 (router uses both) → T5 (docs). No forward references.
