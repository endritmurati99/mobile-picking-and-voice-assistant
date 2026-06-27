# PWR Voice v2 Hybrid NLU and Evaluation Design

Status: design draft  
Date: 2026-06-27  
Scope: PWR / Mobile Picking und Voice Assistant voice recognition, command execution, local assist, testability, and evaluation data.

## Executive Decision

PWR Voice v2 uses a hybrid architecture:

1. Command Fast Lane for standard picking commands.
2. Assist Lane for unclear, explanatory, stock, and exception questions.
3. Odoo evaluation storage for reproducible test and field data.
4. Local LLM only behind a backend gate, first in shadow mode.

The local LLM must not sit in the critical confirm/next path and must not execute writes. It can propose structured JSON for unclear cases; FastAPI remains the gatekeeper.

## Current Facts

Current voice path:

```text
PWA MediaRecorder
-> FastAPI /api/voice/recognize
-> backend/app/utils/audio.py ffmpeg conversion
-> backend/app/services/whisper_client.py
-> backend/app/services/intent_engine.py
-> PWA handleVoiceIntent()
-> existing FastAPI picking commands when needed
```

Current assist path:

```text
PWA /api/voice/assist
-> FastAPI loads picking/stock/Obsidian context
-> n8n voice-exception-query
-> FastAPI local fallback
-> TTS response
```

Current TTS path:

```text
PWA speak()
-> short responses: browser TTS
-> longer responses: /api/voice/tts
-> backend/app/services/piper_client.py
-> local Piper service
```

Important clarification: there is no Wispr integration in the current codebase. The current STT component is Whisper via the local Whisper ASR service. Piper is TTS only.

## Problem

The user experience is not only a phrase-matching problem. The perceived delay is a combined pipeline delay:

1. Browser waits for speech and silence.
2. Browser uploads recorded audio.
3. Backend converts audio via ffmpeg.
4. Whisper transcribes.
5. Intent engine resolves the command.
6. PWA executes the UI or backend action.
7. Backend confirm calls Odoo and may trigger follow-up workflows.
8. Piper/browser TTS blocks the next listening cycle through the audio interlock.

Adding more aliases alone will not fix this. v2 must measure each segment, reduce the hot path, and make real test inputs reproducible.

## Goals

- Make standard commands faster and safer.
- Expand natural German command coverage without making false writes more likely.
- Add local intelligence for unclear questions without putting LLM latency into the standard command path.
- Store evaluation data in Odoo so recognition quality and latency can be compared across versions.
- Make voice testable without always needing a real microphone, Whisper, Piper, or Odoo.
- Keep every implementation slice small enough to test, commit, and push safely.

## Non-Goals

- No LLM direct writes to Odoo.
- No n8n or LLM in the standard confirm/next command path.
- No optimistic business confirmation before backend success.
- No raw audio storage by default.
- No broad rewrite of the picking flow in this spec.
- No implementation work before this design is reviewed.

## Product Semantics

The following meanings are fixed for v2:

| Spoken phrase family | Intent | Execution rule |
| --- | --- | --- |
| `bestaetigen`, `ja`, `ok`, `passt`, `stimmt`, `richtig` | `confirm` | Confirms only the active line in detail view. |
| `ich moechte den auftrag bestaetigen` | `confirm` by default | Natural phrase means current active line unless the user says an explicit bulk phrase. |
| `paket erledigt`, `karton erledigt`, `position erledigt`, `artikel erledigt` | `confirm` | Confirms active line/package/carton context, not the whole order. |
| `naechster auftrag`, `gib mir den naechsten auftrag` | `next_order` | Allowed from list, complete view, or no active line. |
| `weiter`, `naechste position` | `next` | Moves within the current picking detail. |
| `auftrag erledigt`, `auftrag fertig`, `auftrag komplett`, `alles bestaetigen` | `confirm_all` | Allowed only in safe detail context and must use a confirmation prompt before bulk writes. |
| `fertig`, `erledigt`, `komplett` | `done` | Only allowed after no active line remains. |
| `passt nicht`, `stimmt nicht`, `fehlt`, `falscher artikel` | `problem` | Never treated as confirm. |

Bulk confirmation is intentionally harder than line confirmation. The system must prefer asking once more over silently confirming too much.

## Target Architecture

### 1. Command Fast Lane

```text
PWA audio
-> /api/voice/recognize
-> audio normalization
-> Whisper
-> deterministic intent engine
-> context gate
-> response to PWA
-> existing PWA dispatcher
-> existing FastAPI picking command, if action writes
```

Rules:

- Handles `confirm`, `confirm_all`, `next`, `previous`, `next_order`, `done`, `pause`, `repeat`, `photo`, `help`, numeric check/quantity commands.
- No Odoo reads inside recognition.
- No n8n.
- No Ollama/local LLM.
- No free-form reasoning.
- Context gates are authoritative: surface, active line, remaining line count, and current dialog state.
- Intent engine remains deterministic and fast.

This lane optimizes speed and safety.

### 2. Assist Lane

```text
PWA assist request
-> /api/voice/assist
-> FastAPI loads bounded picking/stock/context
-> optional local LLM adapter
-> strict JSON schema validation
-> FastAPI policy gate
-> local answer, n8n event, or safe fallback
```

Allowed use cases:

- `unknown` with useful transcript.
- `stock_query`.
- shortage/problem explanation.
- context explanations such as "was baue ich hier".
- supervisor/help escalation.

Disallowed use cases:

- Standard command execution.
- Confirming lines or orders.
- Overriding deterministic context gates.
- Creating Odoo writes directly.

This lane optimizes understanding and flexibility.

## Local LLM Design

Recommended placement: FastAPI, not n8n.

Reason: FastAPI already owns the voice contract, context gates, timing, idempotency, and response validation. n8n can still receive validated events, but it should not be the safety boundary for voice commands.

### Provider

Initial local provider: Ollama-compatible HTTP adapter.

Required backend flags:

```text
PWR_VOICE_V2_ENABLED=false
PWR_VOICE_LLM_SHADOW=false
PWR_VOICE_LLM_ACTIVE=false
PWR_VOICE_LLM_URL=http://ollama:11434
PWR_VOICE_LLM_MODEL=
PWR_VOICE_LLM_TIMEOUT_MS=1200
PWR_VOICE_LLM_MAX_CONCURRENCY=1
```

Defaults stay disabled.

### Structured Output Contract

The LLM may return only a schema-constrained candidate:

```json
{
  "status": "ok",
  "intent_candidate": "stock_query",
  "action": "explain_context",
  "tts_text": "Am aktuellen Platz ist kein verfuegbarer Bestand mehr sichtbar.",
  "confidence": 0.82,
  "referenced_product_id": null,
  "referenced_location_id": null,
  "recommendation": null
}
```

Allowed enum values:

- `status`: `ok`, `fallback`
- `intent_candidate`: `stock_query`, `problem`, `unknown`, `none`
- `action`: `none`, `explain_context`, `suggest_replenishment`, `ask_supervisor`

Validation rules:

- Reject unknown enum values.
- Reject missing required fields.
- Reject IDs that are not present in the request context.
- Reject text that contains instructions to bypass validation.
- Reject any direct write instruction.
- Reject responses above the timeout budget.
- Reject confidence below the configured threshold.

Rejected LLM responses become local FastAPI fallback answers.

### Shadow Mode

Shadow mode runs after Whisper and deterministic intent resolution.

Behavior:

- The deterministic response is returned to the PWA.
- The LLM candidate is logged only.
- No UI action is triggered.
- No TTS is generated from the LLM.
- No Odoo/n8n write is executed because of the LLM.

Logged comparison:

- deterministic intent
- deterministic confidence
- LLM candidate
- LLM confidence
- latency
- disagreement category
- whether the LLM would have violated a context gate

### Active Fallback Mode

Active mode is a later canary only.

Rules:

- Allowed only when deterministic result is `unknown` or low confidence.
- Never allowed for direct `confirm`, `confirm_all`, or `done`.
- Never allowed to override context gates.
- Requires confirmation prompt before any follow-up action.
- Must be disabled instantly by flag.

## Latency Model

v2 must measure before optimizing.

Minimum timing fields:

| Field | Meaning |
| --- | --- |
| `recording_ms` | PWA time from capture start to capture stop. |
| `speech_ms` | Detected speech time where available. |
| `silence_wait_ms` | Time waiting after final speech before stop. |
| `upload_ms` | PWA upload/request overhead. |
| `convert_ms` | Backend audio conversion. |
| `stt_ms` | Whisper call. |
| `intent_ms` | Deterministic intent matching. |
| `llm_ms` | Local LLM call, if any. |
| `backend_total_ms` | Backend endpoint total. |
| `pwa_action_ms` | PWA time to dispatch action. |
| `odoo_ms` | Business write duration. |
| `n8n_ms` | n8n duration, if called. |
| `tts_synthesis_ms` | Piper or browser setup time. |
| `tts_playback_ms` | Spoken response duration. |
| `time_to_next_listening_ms` | End of action/TTS to next listening-ready state. |
| `end_to_end_ms` | User speech end to observable action completion. |

Initial targets:

- Standard command hot path must not regress against v1 baseline by more than 10 percent p95.
- Lab target for short standard commands: backend `/voice/recognize` p95 <= 1500 ms after warm-up.
- User-perceived speech-end-to-action target: p50 <= 900 ms, p95 <= 1800 ms.
- Intent engine target: p95 <= 20 ms.
- LLM assist timeout: default <= 1200 ms, with local fallback.

These are starting targets. The first implementation slice must record the real baseline and then tighten budgets with data.

## Evaluation Storage

Evaluation data should be stored additively in Odoo because Odoo is already the system of record for picking context and user/device assignment.

Raw audio is not stored by default. Store hashes and asset references. Attach raw audio only for explicit evaluation sessions.

### Model: `pwr.voice.eval.session`

Suggested fields:

- `name`
- `spec_version`
- `corpus_version`
- `app_git_sha`
- `backend_git_sha`
- `mode`: `golden_transcript`, `audio_corpus`, `playwright_mock`, `manual_device`, `live_shadow`
- `started_at`
- `ended_at`
- `operator_user_id`
- `evaluator_user_id`
- `device_id_hash`
- `device_label`
- `browser`
- `os`
- `microphone_type`
- `environment_profile`
- `noise_db_avg`
- `noise_db_peak`
- `event_count`
- `intent_accuracy`
- `command_success_rate`
- `false_positive_rate`
- `p50_end_to_end_ms`
- `p95_end_to_end_ms`
- `p95_stt_ms`
- `notes`

### Model: `pwr.voice.eval.event`

Suggested fields:

- `session_id`
- `sequence`
- `case_id`
- `correlation_id`
- `occurred_at`
- `event_type`
- `surface`
- `context`
- `picking_id`
- `move_line_id`
- `product_id`
- `location_id`
- `source`: `transcript`, `mock_stt`, `audio_corpus`, `manual_device`, `live_shadow`
- `audio_asset_ref`
- `audio_sha256`
- `audio_bytes`
- `speech_ms`
- `expected_transcript`
- `whisper_transcript`
- `normalized_text`
- `expected_intent`
- `recognized_intent`
- `expected_value`
- `recognized_value`
- `confidence`
- `match_strategy`
- `requires_confirmation`
- `llm_enabled`
- `llm_shadow`
- `llm_model`
- `llm_intent_candidate`
- `llm_confidence`
- `llm_disagreement_category`
- `intent_correct`
- `context_gate_correct`
- `action_executed`
- `backend_success`
- `odoo_write_success`
- `n8n_called`
- `piper_used`
- `browser_tts_used`
- `false_positive`
- `false_negative`
- `failure_stage`
- `error_message`
- latency fields from the latency model
- `config_snapshot_json`

## Test Strategy

### 1. Golden Transcript Corpus

Create a versioned corpus, for example:

```text
backend/tests/voice/golden_transcripts.v2.jsonl
```

Each case contains:

- `case_id`
- `transcript`
- `surface`
- `context`
- `remaining_line_count`
- `active_line_present`
- `expected_intent`
- `expected_value`
- `expected_match_allowed`
- `must_not_execute`

Required coverage:

- `confirm`
- `confirm_all`
- `done`
- `next_order`
- `next`
- `previous`
- `problem`
- `stock_query`
- `pause`
- `repeat`
- `help`
- location check numbers
- quantity numbers
- negative/safety cases

Critical negative cases:

- `ja` in list view must not confirm.
- `fertig` with active final line must not finish.
- `komplett` outside safe detail context must not bulk-confirm.
- TTS prompt echo must not execute.
- `passt nicht` must become problem, not confirm.

### 2. Backend Route Tests

`/api/voice/recognize` tests mock:

- `convert_to_wav`
- `whisper_client.transcribe_audio`

Assertions:

- Empty audio returns HTTP 400.
- Empty STT returns `unknown`.
- Timing fields are present.
- `normalized_text`, `match_strategy`, `requires_confirmation`, and `confirmation_prompt` are correct.
- Local hot-path commands do not call n8n.
- Local hot-path commands do not call Odoo from recognition.

`/api/voice/assist` tests mock:

- Odoo client
- n8n client
- optional LLM adapter

Assertions:

- Local-only intents return `not_applicable`.
- Stock/problem questions use bounded context.
- LLM schema violations are fallbacked.
- LLM timeout is fallbacked.

### 3. PWA Unit Tests

Required checks:

- `voice-helpers.mjs` transition and cooldown behavior.
- Echo detection.
- Piper bypass for short responses.
- `api.js` `recognizeVoice()` sends `context`, `surface`, `remaining_line_count`, and `active_line_present`.
- Uncertain/unknown results do not execute business actions.
- Recovery confirmation executes only the pending stored action.

### 4. Playwright Mocked STT

For UI workflows, mock `/api/voice/recognize`.

Assertions:

- `confirm` calls exactly one `/confirm-line`.
- `confirm_all` requires safe context and user confirmation.
- `done` does not navigate away while an active line exists.
- Short TTS such as `Fertig.` does not call `/api/voice/tts`.
- TTS/cooldown interlock blocks stale STT results.
- `next_order` opens the next available picking from list/complete/no-active-line states.

### 5. Fake Microphone Smoke

Add one optional Playwright smoke path that exercises the real browser recording path.

Chromium launch requirements:

```text
--use-fake-device-for-media-stream
--use-fake-ui-for-media-stream
--use-file-for-fake-audio-capture=<wav>
```

This is not the main CI gate. It catches browser capture regressions that handler-level tests cannot see.

### 6. Audio Corpus Integration

Optional/live test flag:

```text
PWR_RUN_LIVE_AUDIO=1
```

Manifest fields:

- `audio_id`
- `speaker_profile`
- `noise_profile`
- `expected_transcript`
- `expected_intent`
- `duration_ms`
- `sample_rate`
- `device`

Measured:

- WER/CER
- intent accuracy
- empty transcript rate
- `stt_ms`
- `backend_total_ms`
- `end_to_end_ms`

### 7. Manual Device and Noise Runs

Manual evaluation sessions must record:

- device
- browser
- microphone/headset
- environment/noise profile
- command set
- expected intent
- actual result
- latency
- user fallback action

## Acceptance Criteria

Design acceptance:

- The two-lane architecture is approved.
- Product semantics for `confirm`, `confirm_all`, `done`, and `next_order` are approved.
- Odoo evaluation storage is approved.
- Local LLM shadow-first rollout is approved.

Implementation acceptance for v2 phase 1:

- Golden transcript corpus runs without Whisper, Odoo, n8n, Piper, or microphone.
- 100 percent of safety-gate corpus cases pass.
- 0 critical false positives for `confirm`, `confirm_all`, and `done`.
- `/api/voice/recognize` emits additive timing fields.
- Standard hot-path commands do not call `/voice/assist`, n8n, or Odoo during recognition.
- Playwright can test voice workflows deterministically without real microphone.
- Evaluation session and event data can be written and queried in Odoo.
- All v2 flags default off.

Implementation acceptance before active LLM fallback:

- Shadow mode has at least 95 percent agreement with deterministic safe commands.
- Shadow mode logs 0 cases where LLM would bypass a safety gate.
- Unknown rate improves in canary without safety regression.
- p95 standard command latency does not regress by more than 10 percent from v1 baseline.

## Rollout Plan

### Phase 0: Clean Git Baseline

Current repo state is mixed. Before v2 implementation:

- Finish or park existing Odoo instance switch changes.
- Commit voice v1 changes separately.
- Do not use `git add .`.
- Do not push from a mixed index.
- Start v2 on a clean branch, recommended `feat/pwr-voice-v2`.

### Phase 1: Measurement and Evaluation Scaffold

Add no behavior change except telemetry and evaluation writes.

Deliverables:

- backend timing fields
- PWA timing fields
- Odoo evaluation session/event models
- export/query helpers
- tests for telemetry and model writes

### Phase 2: Transcript Corpus and Test Harness

Deliverables:

- golden transcript corpus
- backend corpus test runner
- PWA mocked-STT Playwright tests
- optional fake microphone smoke test

### Phase 3: LLM Adapter in Shadow Mode

Deliverables:

- Ollama adapter
- JSON schema model
- backend validator
- timeout/circuit breaker
- shadow comparison logs
- no active behavior change

### Phase 4: Command Fast Lane Optimization

Use measurements from phases 1 and 2.

Candidates:

- lower silence wait only if false starts stay stable
- avoid unnecessary ffmpeg conversion where the STT service can accept source audio safely
- tune Whisper/faster-whisper model and VAD settings
- keep short TTS on browser path
- cache/reuse Piper health and avoid blocking short acknowledgements

### Phase 5: Active LLM Fallback Canary

Only for unknown/assist cases.

Rules:

- backend flags only
- limited users/devices
- strict rollback
- confirmation prompt before follow-up action
- daily review of false positives and safety gate disagreements

### Phase 6: Confirm Path Optimization

This is related but large enough to isolate after measurement.

Candidates:

- reduce redundant Odoo reads after confirm
- atomize confirm-line response shape
- separate user feedback from slow follow-up workflow
- keep n8n post-confirm asynchronous when safe

## Commit Boundaries

Recommended commits after design approval:

1. `feat(voice): add structured recognition telemetry`
2. `feat(voice): add voice evaluation models`
3. `test(voice): add golden transcript corpus`
4. `test(voice): add mocked stt playwright coverage`
5. `feat(voice): add disabled local llm settings`
6. `feat(voice): add ollama shadow parser`
7. `feat(voice): log llm shadow comparisons`
8. `feat(voice): enable llm assist fallback behind canary flag`

Each commit must be independently testable. Do not mix Odoo models, PWA UX, LLM adapter, and E2E in one commit.

## Push Rules

Push only when:

- `git status --short` is intentionally clean or scoped to the exact commit.
- Existing ahead commits are reviewed.
- No `.env`, model weights, audio captures, `test-results`, or local artifacts are staged.
- Backend voice tests pass.
- PWA voice tests pass.
- Relevant Playwright voice tests pass.
- v2 behavior flags default off.
- Rollback is documented.

## Verification Commands

Existing fast gates:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant"
npm run test:voice
npx.cmd playwright test e2e/voice-commands.spec.js --reporter=list
```

Backend gates:

```powershell
cd "C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant\backend"
$env:PYTHONPATH = ".deps;."
python -m pytest -p pytest_asyncio tests/test_intent_engine.py tests/test_voice_routes.py -q
```

Future v2 gates:

```powershell
python -m pytest -p pytest_asyncio tests/test_voice_corpus.py -q
npx.cmd playwright test e2e/voice-mocked-stt.spec.js --project=mobile-chromium --reporter=list
$env:PWR_RUN_LIVE_AUDIO = "1"; python -m pytest -p pytest_asyncio tests/test_voice_audio_corpus.py -q
```

## External References

- Ollama structured outputs and JSON schema: https://docs.ollama.com/capabilities/structured-outputs
- Ollama API `format` parameter: https://github.com/ollama/ollama/blob/main/docs/api.md
- faster-whisper VAD and performance options: https://github.com/SYSTRAN/faster-whisper
- Whisper ASR webservice configuration: https://github.com/ahmetoner/whisper-asr-webservice
- Playwright launch options: https://github.com/microsoft/playwright/blob/main/docs/src/test-api/class-testoptions.md
- Chromium fake media capture flags: https://github.com/chromium/chromium/blob/main/media/base/media_switches.cc

## Open Decisions for Review

1. Should `confirm_all` require a spoken second confirmation every time, or only when more than one line remains?
2. Which local model should be used first for Ollama shadow mode?
3. Should `suggest_replenishment` create a follow-up event automatically after user confirmation, or only suggest a manual action first?
4. What is the acceptable privacy policy for saving transcripts from real picker sessions?
5. Should audio corpus files live in the repo as synthetic samples, outside the repo as local assets, or both?

