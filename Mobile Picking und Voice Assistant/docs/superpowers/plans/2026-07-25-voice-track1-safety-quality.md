# Voice Track 1 — Safety & Quality (Phase A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the voice assistant a safe, concise hands-free helper: no silent Odoo writes from a misrecognition, reliable recognition of natural commands, quiet-by-default with on-command queries, and terse natural speech.

**Architecture:** Recognition stays server-side (`intent_engine.py`, Whisper). The act/read-back/echo decision and all TTS text live client-side (`voice-runtime.mjs` pure logic, consumed by `app.js`). Backend returns intent + confidence; the frontend owns the safety gate using its own threshold constants — so there is no cross-language constant to keep in sync.

**Tech Stack:** Python 3 / FastAPI (backend, pytest), vanilla ES modules (PWA, `node --test`).

## Global Constraints

- Backend test command: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q` — baseline **288/288 green must stay green**.
- Node test command: `node --test pwa/js/tests/<file>.test.mjs` — existing suites must stay green.
- Deterministic & offline only. **No LLM / Ollama in Phase A.**
- Do not change auth wiring. `/voice/recognize` stays read-only; `/voice/assist` keeps its existing `get_write_request_context` dependency.
- German normalization already strips umlauts/ß (`normalize_text`); write all aliases/patterns in normalized ASCII form (e.g. `bestaetigen`, `naechste`).
- Write intents = `{"confirm", "confirm_all"}`. Query intents (read-only) = `{"whats_next", "where", "how_many_left"}`.
- Threshold constants (frontend, `voice-runtime.mjs`): `VOICE_ACT_THRESHOLD = 0.73`, `VOICE_CONFIRM_DIRECT_THRESHOLD = 0.90`, `VOICE_UNCERTAIN_THRESHOLD = 0.55`. The old `VOICE_AUTOMATION_THRESHOLD = 0.78` is removed (it created the [0.73, 0.78) dead band).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `backend/app/services/intent_engine.py` | intent matching | negation generalized, English aliases removed, query intents added |
| `backend/app/services/whisper_client.py` | STT call | `initial_prompt` + `no_speech_prob` hallucination filter |
| `backend/tests/test_intent_engine.py` | backend intent tests | new cases (create if absent) |
| `backend/tests/test_whisper_client.py` | whisper tests | new (create) |
| `pwa/js/voice-runtime.mjs` | act/read-back decision + TTS text (pure) | new threshold model, `classifyVoiceResult` rewrite, `buildSpeechPrompt`, `formatLocationForSpeech` |
| `pwa/js/tests/voice-runtime.test.mjs` | frontend logic tests | new cases |
| `pwa/js/app.js` | DOM wiring | consume new classify result: read-back flow, quiet-after-book, query handlers, STT-empty feedback |

App.js stays a thin consumer: every testable decision is a pure function in `voice-runtime.mjs`.

---

## Task 1: Generalize negation so "nicht ok" / "nicht gut" never confirm

**Files:**
- Modify: `backend/app/services/intent_engine.py` (`NEGATION_TERMS` area, `recognize_intent`, `_contains_negated_confirmation` → replace)
- Test: `backend/tests/test_intent_engine.py` (create if absent)

**Interfaces:**
- Produces: `_has_negation(normalized_text: str) -> bool`; `recognize_intent(...)` unchanged signature. When a negation term is present AND the resolved action is a write intent (`confirm`/`confirm_all`), the returned action becomes `"problem"`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intent_engine.py
import pytest
from app.services.intent_engine import recognize_intent, PickingContext, VoiceSurface

@pytest.mark.parametrize("phrase", ["nicht ok", "nicht gut", "nicht bestaetigen", "nicht richtig", "kein ok"])
def test_negated_confirmation_never_confirms(phrase):
    intent = recognize_intent(
        phrase, PickingContext.AWAITING_COMMAND,
        surface=VoiceSurface.DETAIL, remaining_line_count=1, active_line_present=True,
    )
    assert intent.action != "confirm"
    assert intent.action != "confirm_all"

def test_plain_confirmation_still_confirms():
    intent = recognize_intent(
        "ok", PickingContext.AWAITING_COMMAND,
        surface=VoiceSurface.DETAIL, remaining_line_count=1, active_line_present=True,
    )
    assert intent.action == "confirm"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_intent_engine.py -q`
Expected: FAIL — `nicht ok` currently resolves to `confirm` @ 0.95.

- [ ] **Step 3: Write minimal implementation**

Replace `_contains_negated_confirmation` (lines ~604-608) with a general negation check, and apply it to write-intent matches inside `recognize_intent`.

```python
# near line 604 — replace _contains_negated_confirmation
def _has_negation(normalized_text: str) -> bool:
    return any(term in normalized_text.split() for term in NEGATION_TERMS)
```

In `recognize_intent`, delete the old `if _contains_negated_confirmation(normalized_text): ...` block (lines ~414-427). After each successful match is resolved, downgrade negated write intents. Simplest: wrap the final resolution. Replace the three `_resolve_with_context(<match>, ...)` returns for exact/regex/fuzzy with a single helper call:

```python
WRITE_ACTIONS = frozenset({"confirm", "confirm_all"})

def _apply_negation_guard(intent: Intent, normalized_text: str) -> Intent:
    if intent.action in WRITE_ACTIONS and _has_negation(normalized_text):
        return Intent(
            action="problem", value=None, confidence=EXACT_MATCH_CONFIDENCE,
            raw_text=intent.raw_text, normalized_text=normalized_text, match_strategy="negation",
        )
    return intent
```

Then in each match branch, wrap before `_resolve_with_context`, e.g.:

```python
    exact_match = _match_exact(text, normalized_text)
    if exact_match is not None:
        return _resolve_with_context(
            _apply_negation_guard(exact_match, normalized_text),
            surface=surface, remaining_line_count=remaining_line_count,
            active_line_present=active_line_present,
        )
```

Apply the same wrap to the `regex_match` and `fuzzy_match` branches.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_intent_engine.py -q`
Expected: PASS.

- [ ] **Step 5: Run full backend suite (no regression)**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q`
Expected: PASS (≥288, note any pre-existing negation tests that changed meaning).

- [ ] **Step 6: Commit**

```bash
git add "Mobile Picking und Voice Assistant/backend/app/services/intent_engine.py" "Mobile Picking und Voice Assistant/backend/tests/test_intent_engine.py"
git commit -m "fix(voice): negation suppresses any confirm intent, not just 3 terms"
```

---

## Task 2: Remove English aliases that pollute German confirm matching

**Files:**
- Modify: `backend/app/services/intent_engine.py` (`REGEX_PATTERNS["confirm"]` line ~312; `ALIASES["confirm"]` if English entries exist)
- Test: `backend/tests/test_intent_engine.py`

**Interfaces:**
- Consumes: Task 1's `recognize_intent`.
- Produces: nothing new; `confirm` no longer matches `fine/yep/yes/mhm`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.parametrize("phrase", ["fine", "yes", "yep"])
def test_english_words_do_not_confirm(phrase):
    intent = recognize_intent(
        phrase, PickingContext.AWAITING_COMMAND,
        surface=VoiceSurface.DETAIL, remaining_line_count=1, active_line_present=True,
    )
    assert intent.action != "confirm"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_intent_engine.py::test_english_words_do_not_confirm -q`
Expected: FAIL — `fine/yep/yes` match `confirm` via regex line 312.

- [ ] **Step 3: Write minimal implementation**

In `REGEX_PATTERNS["confirm"]`, delete the English line:

```python
        # REMOVE this line:
        r"\b(fine|yep|yes|mhm)\b",
```

Scan `ALIASES["confirm"]` for any English tokens and remove them too (keep German `jep/jup/jo/joa/jupp` — those are German colloquial yes). Keep `"gut"`? `"gut"` alone is a legit German confirm; leave it. The concrete removal for Phase A is only the English regex line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_intent_engine.py -q`
Expected: PASS.

- [ ] **Step 5: Run full backend suite**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add "Mobile Picking und Voice Assistant/backend/app/services/intent_engine.py" "Mobile Picking und Voice Assistant/backend/tests/test_intent_engine.py"
git commit -m "fix(voice): drop English confirm aliases that misfired on German audio"
```

---

## Task 3: Add read-only query intents (whats_next / where / how_many_left)

**Files:**
- Modify: `backend/app/services/intent_engine.py` (`Intent` action space via `ALIASES`, `REGEX_PATTERNS`, `PRIORITY_ORDER`, `_resolve_with_context`)
- Test: `backend/tests/test_intent_engine.py`

**Interfaces:**
- Produces: `recognize_intent` can return actions `"whats_next"`, `"where"`, `"how_many_left"`. All read-only; gated to `VoiceSurface.DETAIL` with an active line (except `how_many_left`, allowed on DETAIL always).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.parametrize("phrase,expected", [
    ("was jetzt", "whats_next"),
    ("was muss ich picken", "whats_next"),
    ("wo", "where"),
    ("wo ist das", "where"),
    ("wie viele noch", "how_many_left"),
])
def test_query_intents_recognized(phrase, expected):
    intent = recognize_intent(
        phrase, PickingContext.AWAITING_COMMAND,
        surface=VoiceSurface.DETAIL, remaining_line_count=3, active_line_present=True,
    )
    assert intent.action == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_intent_engine.py::test_query_intents_recognized -q`
Expected: FAIL — these actions do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add to `ALIASES`:

```python
    "whats_next": (
        "was jetzt", "was nun", "was muss ich picken", "was muss ich holen",
        "was als naechstes", "naechste position bitte", "was ist dran",
    ),
    "where": ("wo", "wohin", "welcher platz", "welches fach", "welches regal"),
    "how_many_left": ("wie viele noch", "wie viel noch", "wieviele offen", "wie viele offen"),
```

Add to `REGEX_PATTERNS`:

```python
    "whats_next": (
        r"\b(was jetzt|was nun|was als naechstes|was ist dran)\b",
        r"\bwas muss ich (picken|holen|nehmen)\b",
    ),
    "where": (r"\b(wo|wohin)\b", r"\b(welches (fach|regal)|welcher platz)\b"),
    "how_many_left": (r"\bwie ?viele? (noch|offen)\b", r"\bwie ?viel noch\b"),
```

Add the three actions to `PRIORITY_ORDER` (place `whats_next`, `where`, `how_many_left` after `status`, before `repeat`). In `_resolve_with_context`, add before the final `return intent`:

```python
    if intent.action in {"whats_next", "where"}:
        if surface == VoiceSurface.DETAIL and active_line_present:
            return intent
        return _unknown_intent(intent.raw_text, intent.normalized_text)
    if intent.action == "how_many_left":
        if surface == VoiceSurface.DETAIL:
            return intent
        return _unknown_intent(intent.raw_text, intent.normalized_text)
```

Note: `where`'s bare `wo` regex must sit at low priority so it never shadows a more specific intent; `PRIORITY_ORDER` after `status` achieves that.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_intent_engine.py -q`
Expected: PASS.

- [ ] **Step 5: Run full backend suite**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add "Mobile Picking und Voice Assistant/backend/app/services/intent_engine.py" "Mobile Picking und Voice Assistant/backend/tests/test_intent_engine.py"
git commit -m "feat(voice): add read-only query intents whats_next/where/how_many_left"
```

---

## Task 4: Harden Whisper — domain prompt + hallucination filter

**Files:**
- Modify: `backend/app/services/whisper_client.py`
- Test: `backend/tests/test_whisper_client.py` (create)

**Interfaces:**
- Produces: `transcribe_audio(audio_bytes, mime_type) -> str` unchanged signature. Internally requests segments; drops the result to `""` when the dominant segment's `no_speech_prob` exceeds `NO_SPEECH_MAX = 0.6`. Sends `initial_prompt = DOMAIN_PROMPT`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_whisper_client.py
import pytest
import app.services.whisper_client as wc

class _FakeResp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p
    text = "fake"
    status_code = 200

class _FakeClient:
    def __init__(self, payload): self._p = payload; self.last = None
    async def post(self, url, params=None, files=None):
        self.last = {"url": url, "params": params}
        return _FakeResp(self._p)
    is_closed = False

@pytest.mark.asyncio
async def test_hallucination_dropped(monkeypatch):
    fake = _FakeClient({"text": "Untertitelung des ZDF", "segments": [{"no_speech_prob": 0.95, "text": "Untertitelung des ZDF"}]})
    monkeypatch.setattr(wc, "_get_client", lambda: fake)
    assert await wc.transcribe_audio(b"x", "audio/wav") == ""

@pytest.mark.asyncio
async def test_real_speech_kept_and_prompt_sent(monkeypatch):
    fake = _FakeClient({"text": "auftrag fertig", "segments": [{"no_speech_prob": 0.05, "text": "auftrag fertig"}]})
    monkeypatch.setattr(wc, "_get_client", lambda: fake)
    result = await wc.transcribe_audio(b"x", "audio/wav")
    assert result == "auftrag fertig"
    assert fake.last["params"].get("initial_prompt") == wc.DOMAIN_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_whisper_client.py -q`
Expected: FAIL — no `DOMAIN_PROMPT`, no filtering, `initial_prompt` not sent.

- [ ] **Step 3: Write minimal implementation**

```python
# top of whisper_client.py, after logger
NO_SPEECH_MAX = 0.6
DOMAIN_PROMPT = (
    "Kommissionierung im Lager. Befehle: bestaetigen, weiter, naechste, "
    "auftrag fertig, problem, foto, was jetzt. Orte: Regal, Fach, Zone."
)
```

In `transcribe_audio`, add `initial_prompt` to `params` and filter on segments:

```python
            params={
                "task": "transcribe",
                "language": "de",
                "output": "json",
                "encode": "false",
                "initial_prompt": DOMAIN_PROMPT,
            },
```

Replace the `return data.get("text", "").strip()` line with:

```python
        data = resp.json()
        text = data.get("text", "").strip()
        segments = data.get("segments") or []
        if segments:
            worst = max((s.get("no_speech_prob", 0.0) for s in segments), default=0.0)
            if worst >= NO_SPEECH_MAX:
                logger.info("Whisper: dropped likely hallucination (no_speech_prob=%.2f)", worst)
                return ""
        return text
```

Note: if the live ASR service does not return `segments` for `output=json`, the filter is a graceful no-op (segments empty). Verify the live response shape when running against the real container; if segments require a different `output` value, adjust `output` accordingly and keep the same filter.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest tests/test_whisper_client.py -q`
Expected: PASS.

- [ ] **Step 5: Run full backend suite**

Run: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add "Mobile Picking und Voice Assistant/backend/app/services/whisper_client.py" "Mobile Picking und Voice Assistant/backend/tests/test_whisper_client.py"
git commit -m "feat(voice): add Whisper domain prompt and no_speech_prob hallucination filter"
```

---

## Task 5: New frontend threshold model + write/read-back classification

**Files:**
- Modify: `pwa/js/voice-runtime.mjs` (constants lines 1-2, `classifyVoiceResult` lines 61-81)
- Test: `pwa/js/tests/voice-runtime.test.mjs`

**Interfaces:**
- Produces: constants `VOICE_ACT_THRESHOLD`, `VOICE_CONFIRM_DIRECT_THRESHOLD`, `VOICE_UNCERTAIN_THRESHOLD`; `WRITE_INTENTS` set. `classifyVoiceResult(result) -> { kind, canHandle, promptText }` where `kind ∈ {'error','unknown','uncertain','readback','recognized'}`. `'readback'` = a write intent that must be confirmed before booking; `'recognized'` = safe to act now (non-write above act threshold, or `confirm` at/above direct threshold).

- [ ] **Step 1: Write the failing test**

```javascript
// pwa/js/tests/voice-runtime.test.mjs — add cases
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classifyVoiceResult } from '../voice-runtime.mjs';

test('confirm_all always needs read-back even at high confidence', () => {
    const c = classifyVoiceResult({ intent: 'confirm_all', confidence: 0.99 });
    assert.equal(c.kind, 'readback');
    assert.equal(c.canHandle, false);
});

test('single confirm books directly at/above direct threshold', () => {
    const c = classifyVoiceResult({ intent: 'confirm', confidence: 0.95 });
    assert.equal(c.kind, 'recognized');
    assert.equal(c.canHandle, true);
});

test('single confirm in mid band needs read-back', () => {
    const c = classifyVoiceResult({ intent: 'confirm', confidence: 0.80 });
    assert.equal(c.kind, 'readback');
});

test('non-write intent acts from 0.73 (no dead band)', () => {
    const c = classifyVoiceResult({ intent: 'next', confidence: 0.74 });
    assert.equal(c.kind, 'recognized');
    assert.equal(c.canHandle, true);
});

test('below act threshold is uncertain', () => {
    const c = classifyVoiceResult({ intent: 'next', confidence: 0.60 });
    assert.equal(c.kind, 'uncertain');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test pwa/js/tests/voice-runtime.test.mjs`
Expected: FAIL — old `classifyVoiceResult` has no `readback` kind and uses 0.78.

- [ ] **Step 3: Write minimal implementation**

Replace lines 1-2 and `classifyVoiceResult`:

```javascript
export const VOICE_ACT_THRESHOLD = 0.73;
export const VOICE_CONFIRM_DIRECT_THRESHOLD = 0.90;
export const VOICE_UNCERTAIN_THRESHOLD = 0.55;
export const WRITE_INTENTS = new Set(['confirm', 'confirm_all']);

export function classifyVoiceResult(result) {
    const confidence = Number(result?.confidence ?? 0);
    const intent = result?.intent;

    if (!result || intent === 'error') {
        return { kind: 'error', canHandle: false, promptText: null };
    }
    if (intent === 'unknown' || confidence < VOICE_UNCERTAIN_THRESHOLD) {
        return { kind: 'unknown', canHandle: false, promptText: null };
    }
    if (confidence < VOICE_ACT_THRESHOLD) {
        return { kind: 'uncertain', canHandle: false, promptText: 'Unsicher, bitte wiederholen oder tippen.' };
    }
    // confirm_all always confirms first; confirm below direct threshold confirms first.
    if (intent === 'confirm_all' ||
        (intent === 'confirm' && confidence < VOICE_CONFIRM_DIRECT_THRESHOLD)) {
        return { kind: 'readback', canHandle: false, promptText: null };
    }
    return { kind: 'recognized', canHandle: true, promptText: null };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test pwa/js/tests/voice-runtime.test.mjs`
Expected: PASS.

- [ ] **Step 5: Check dependent suites**

Run: `node --test pwa/js/tests/voice-helpers.test.mjs && node --test pwa/js/tests/api.test.mjs`
Expected: PASS. If any test imported `VOICE_AUTOMATION_THRESHOLD`, update it to the new constants.

- [ ] **Step 6: Commit**

```bash
git add "Mobile Picking und Voice Assistant/pwa/js/voice-runtime.mjs" "Mobile Picking und Voice Assistant/pwa/js/tests/voice-runtime.test.mjs"
git commit -m "feat(voice): threshold model with read-back gate, closes 0.73-0.78 dead band"
```

---

## Task 6: Concise natural TTS text (no spelled-out location codes)

**Files:**
- Modify: `pwa/js/voice-runtime.mjs` (add `formatLocationForSpeech`, `buildSpeechPrompt`)
- Modify: `pwa/js/app.js` (import + use them; delete the local `formatLocationForSpeech` at line 85 and `getLineSpeechPrompt` body at line 280 to delegate)
- Test: `pwa/js/tests/voice-runtime.test.mjs`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces: `formatLocationForSpeech(line) -> string` (returns a short natural location like `"Regal 3"` from `location_src_zone`/`location_src_short`, never a digit-by-digit code); `buildSpeechPrompt(line) -> string` returning `"<product>, <n> Stück, <shortLocation>"` with empty parts dropped.

- [ ] **Step 1: Write the failing test**

```javascript
import { buildSpeechPrompt, formatLocationForSpeech } from '../voice-runtime.mjs';

test('speech prompt is product, qty, short location', () => {
    const line = { product_short_name: 'Pink Brick', quantity_demand: 2, location_src_zone: 'Regal 3' };
    assert.equal(buildSpeechPrompt(line), 'Pink Brick, 2 Stück, Regal 3');
});

test('location never spells out a raw fach code digit by digit', () => {
    const line = { product_short_name: 'Pink Brick', quantity_demand: 1, location_src: 'WH/Stock/A3-8848' };
    const spoken = buildSpeechPrompt(line);
    assert.ok(!/\bA 3 8 8 4 8\b/.test(spoken));
    assert.ok(!/8 8 4 8/.test(spoken));
});

test('voice_instruction_short wins when present', () => {
    const line = { voice_instruction_short: 'Pink Brick holen', product_short_name: 'x', location_src_zone: 'Regal 3' };
    assert.equal(buildSpeechPrompt(line), 'Pink Brick holen');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test pwa/js/tests/voice-runtime.test.mjs`
Expected: FAIL — functions not exported from voice-runtime.mjs.

- [ ] **Step 3: Write minimal implementation**

Add to `voice-runtime.mjs`:

```javascript
export function formatLocationForSpeech(line) {
    // Prefer a human zone/short label; never spell out a raw fach code.
    const zone = line?.location_src_zone;
    const short = line?.location_src_short;
    if (zone && !/\d{3,}/.test(zone)) return zone;
    if (short && !/\d{3,}/.test(short)) return short;
    // Fall back to the zone/short even with digits, but as a compact token,
    // not a spaced-out digit chain. If only a raw path exists, drop location.
    return zone || short || '';
}

export function buildSpeechPrompt(line) {
    if (!line) return '';
    if (line.voice_instruction_short) return line.voice_instruction_short;
    const product = line.ui_display || line.product_short_name || line.product_name || 'Produkt';
    const qty = line.quantity_demand != null ? `${line.quantity_demand} Stück` : '';
    const loc = formatLocationForSpeech(line);
    return [product, qty, loc].filter(Boolean).join(', ');
}
```

In `app.js`: add `buildSpeechPrompt` and `formatLocationForSpeech` to the existing `voice-runtime.mjs` import. Replace `getLineSpeechPrompt` (line 280) body with `return buildSpeechPrompt(line);` and delete the local `formatLocationForSpeech` (line 85), pointing its two call sites (line 283 area is now inside buildSpeechPrompt; line 306 `formatLocationForDisplay` is display-only and stays). Keep `getLineSpeechPrompt` as a thin wrapper so existing callers are untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test pwa/js/tests/voice-runtime.test.mjs`
Expected: PASS.

- [ ] **Step 5: Guard against broken app.js imports**

Run: `node --check pwa/js/app.js && node --test pwa/js/tests/voice-helpers.test.mjs`
Expected: PASS (syntax valid, helpers still green).

- [ ] **Step 6: Commit**

```bash
git add "Mobile Picking und Voice Assistant/pwa/js/voice-runtime.mjs" "Mobile Picking und Voice Assistant/pwa/js/app.js" "Mobile Picking und Voice Assistant/pwa/js/tests/voice-runtime.test.mjs"
git commit -m "feat(voice): concise natural TTS, stop spelling out location codes"
```

---

## Task 7: Read-back flow + quiet-after-book + query handlers in app.js

**Files:**
- Modify: `pwa/js/app.js` (`handleVoiceIntent` lines 2470-2530, add pending-confirm state + query handlers)
- Add pure helper: `pwa/js/voice-runtime.mjs` (`buildReadbackPrompt`)
- Test: `pwa/js/tests/voice-runtime.test.mjs`

**Interfaces:**
- Consumes: `classifyVoiceResult` (Task 5), `buildSpeechPrompt` (Task 6).
- Produces: `buildReadbackPrompt(intent, { line, remainingCount }) -> string`. `confirm` → `"<product>, richtig?"`; `confirm_all` → `"<N> Positionen buchen?"`.

- [ ] **Step 1: Write the failing test**

```javascript
import { buildReadbackPrompt } from '../voice-runtime.mjs';

test('single confirm read-back names the product', () => {
    const p = buildReadbackPrompt('confirm', { line: { product_short_name: 'Pink Brick' }, remainingCount: 5 });
    assert.equal(p, 'Pink Brick, richtig?');
});

test('confirm_all read-back names the count', () => {
    const p = buildReadbackPrompt('confirm_all', { line: null, remainingCount: 12 });
    assert.equal(p, '12 Positionen buchen?');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test pwa/js/tests/voice-runtime.test.mjs`
Expected: FAIL — `buildReadbackPrompt` not defined.

- [ ] **Step 3: Write the helper**

Add to `voice-runtime.mjs`:

```javascript
export function buildReadbackPrompt(intent, { line, remainingCount } = {}) {
    if (intent === 'confirm_all') {
        return `${remainingCount ?? 0} Positionen buchen?`;
    }
    const product = line?.ui_display || line?.product_short_name || line?.product_name || 'Position';
    return `${product}, richtig?`;
}
```

- [ ] **Step 4: Run helper test to verify it passes**

Run: `node --test pwa/js/tests/voice-runtime.test.mjs`
Expected: PASS.

- [ ] **Step 5: Wire the flow into `handleVoiceIntent`**

Add module-scoped pending state near the top of the voice section:

```javascript
let pendingWriteConfirm = null; // { intent, expiresAt }
const READBACK_TTL_MS = 8000;
```

Import `buildReadbackPrompt` and `buildSpeechPrompt`. Rewrite the classification branches in `handleVoiceIntent` (lines 2470-2510) so:

```javascript
    const classification = classifyVoiceResult(result);
    // A pending read-back turns the NEXT affirmative into the actual booking.
    if (pendingWriteConfirm && Date.now() < pendingWriteConfirm.expiresAt
        && (result.intent === 'confirm' || result.intent === 'confirm_all')
        && classification.kind !== 'unknown') {
        const toRun = pendingWriteConfirm.intent;
        pendingWriteConfirm = null;
        if (toRun === 'confirm_all') { await triggerConfirmAll(); }
        else if (line) { await handleScan(line.product_barcode || ''); speak('Gebucht.'); }
        return;
    }
    pendingWriteConfirm = null;

    if (classification.kind === 'error' || classification.kind === 'unknown') {
        if (await maybeHandleVoiceAssist(result, currentPicking, currentLineIndex)) return;
        updateVoiceStatusIndicator('uncertain', { temporary: true });
        return;
    }
    if (classification.kind === 'uncertain') {
        updateVoiceStatusIndicator('uncertain', { temporary: true });
        showToast(classification.promptText, 'warning');
        speak(classification.promptText);
        return;
    }
    if (classification.kind === 'readback') {
        pendingWriteConfirm = { intent: result.intent, expiresAt: Date.now() + READBACK_TTL_MS };
        const prompt = buildReadbackPrompt(result.intent, {
            line, remainingCount: Math.max((currentPicking?.move_lines?.length || 0) - currentLineIndex, 0),
        });
        showToast(prompt, 'info');
        speak(prompt);
        return;
    }
```

Then in the existing `switch (result.intent)` (kind === 'recognized' path), change the `confirm` case to echo after booking, and add query cases:

```javascript
        case 'confirm':
            if (line) { await handleScan(line.product_barcode || ''); speak('Gebucht.'); }
            break;
        case 'whats_next':
            if (line) speak(buildSpeechPrompt(line));
            break;
        case 'where':
            if (line) speak(formatLocationForSpeech(line) || 'Kein Ort.');
            break;
        case 'how_many_left': {
            const remaining = Math.max((lines.length - currentLineIndex - 1), 0);
            speak(`Noch ${remaining}.`);
            break;
        }
```

Ensure `next`/`previous` still speak `buildSpeechPrompt(...)` (they already call `getLineSpeechPrompt`, which now delegates). **Do not** add any auto-speak after `confirm` beyond the `'Gebucht.'` echo — quiet-after-book is required.

- [ ] **Step 6: Verify syntax + full frontend suites**

Run: `node --check pwa/js/app.js && node --test pwa/js/tests/voice-runtime.test.mjs && node --test pwa/js/tests/voice-helpers.test.mjs && node --test pwa/js/tests/api.test.mjs`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add "Mobile Picking und Voice Assistant/pwa/js/voice-runtime.mjs" "Mobile Picking und Voice Assistant/pwa/js/app.js" "Mobile Picking und Voice Assistant/pwa/js/tests/voice-runtime.test.mjs"
git commit -m "feat(voice): read-back gate for writes, echo on book, on-command queries"
```

---

## Task 8: Audible STT-failure feedback (no silent drop)

**Files:**
- Modify: `pwa/js/app.js` (the empty-transcript / recognize path around line 2479)
- Test: manual + `node --check` (behavior lives in DOM path; keep logic minimal)

**Interfaces:**
- Consumes: `speak`, `showToast` (existing).

- [ ] **Step 1: Add the feedback branch**

At the start of `handleVoiceIntent`, before classification, handle an empty/failed transcript explicitly:

```javascript
    if (!result || (!result.text && (result.intent === 'unknown' || result.intent === 'error'))) {
        updateVoiceStatusIndicator('uncertain', { temporary: true });
        showToast('Nicht verstanden, bitte nochmal.', 'warning');
        speak('Nicht verstanden, bitte nochmal.');
        return;
    }
```

This runs when Whisper returned `""` (STT down or hallucination-dropped from Task 4), replacing today's silent skip at line 2479.

- [ ] **Step 2: Verify syntax + suites**

Run: `node --check pwa/js/app.js && node --test pwa/js/tests/voice-runtime.test.mjs`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add "Mobile Picking und Voice Assistant/pwa/js/app.js"
git commit -m "feat(voice): speak+toast on empty transcript instead of silent drop"
```

---

## Final verification

- [ ] Backend: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q` → all green (≥288 + new).
- [ ] Frontend: `node --test pwa/js/tests/voice-runtime.test.mjs && node --test pwa/js/tests/voice-helpers.test.mjs && node --test pwa/js/tests/api.test.mjs && node --test pwa/js/tests/pwa-assets.test.mjs` → all green.
- [ ] `node --check pwa/js/app.js` → valid.
- [ ] Manual smoke (if stack up): say "nicht ok" (no booking), "was jetzt" (speaks concise line), "auftrag fertig" (asks "N Positionen buchen?"), silence/garble (says "nicht verstanden").

---

## Self-Review (author checklist — completed)

- **Spec coverage:** negation (T1), English aliases (T2), query intents/on-command (T3,T7), Whisper prompt+hallucination (T4), threshold model/dead-band (T5), read-back safety incl. confirm_all + echo + TTL (T5,T7), concise TTS/no code-spelling (T6), STT-failure feedback (T8), quiet-after-book (T7). All spec sections mapped.
- **Placeholder scan:** none — every code step has concrete code.
- **Type consistency:** `classifyVoiceResult` kinds (`error/unknown/uncertain/readback/recognized`) used consistently in T5 and T7; `buildSpeechPrompt`/`formatLocationForSpeech`/`buildReadbackPrompt` signatures match between definition (T6/T7) and use (T7/T8). Constant names identical across tasks.
- **Deferred to Phase B:** Ollama fallback, dynamic per-order Whisper vocab, Piper robustness, voice metrics — explicitly out of scope.
