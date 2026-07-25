# Voice Track 1 — LLM Intent Fallback (Phase B)

**Datum:** 2026-07-25 · **HEAD:** 66952a6 · **Track:** Baustellen-Analyse Track 1 (Voice)
**Baut auf:** Phase A (2026-07-25-voice-track1-safety-quality-design.md, commits a50495f..66952a6).
**Scope:** deterministische Erkennung bleibt primär; ein lokales LLM (Ollama) fängt nur die Fälle ab, die Regex/Fuzzy nicht sicher trifft.

## Ziel

Freie, nicht vorhersehbare Formulierungen zuverlässig auf einen bekannten Intent abbilden — ohne die Latenz der häufigen Kommandos zu erhöhen und ohne die Sicherheitsgarantien aus Phase A aufzuweichen.

## Nicht-Ziele

- Kein Bildpfad (Vision bleibt eigener Track).
- Kein LLM für die häufigen Kommandos (die bleiben deterministisch/instant).
- Keine Änderung am Frontend-Sicherheitsmodell — das Read-back-Gate aus Phase A bleibt unverändert und greift auch für LLM-Ergebnisse.

## Auslöser (Trigger)

In `/voice/recognize`, nach `recognize_intent(...)`: der LLM-Fallback läuft, wenn das deterministische Ergebnis
- `action == "unknown"`, ODER
- `confidence < FUZZY_SINGLE_THRESHOLD` (0.73).

Bereits vorhanden und **vorher** ausgeführt bleibt der Segment-Fallback (`recognize_intent_from_segments`). Der LLM-Fallback läuft erst danach und nur, wenn danach immer noch unknown/unter Schwelle. Reihenfolge: deterministisch → Segment-Fallback → LLM-Fallback.

## VoiceIntentClassifier (neuer Service)

Spiegelt `LlmClient` (llm_client.py): Ollama `/api/chat`, `stream:false`, `format:"json"`, `options.temperature:0`, `httpx`-Transport injizierbar für Tests, **jeder** Fehler/Timeout/ungültige Antwort → `ok=False`.

Signatur:

```python
@dataclass(frozen=True)
class VoiceIntentResult:
    ok: bool
    model: str
    intent: str | None = None      # ein Label aus ALLOWED_INTENTS oder None
    confidence: float | None = None

class VoiceIntentClassifier:
    def __init__(self, *, endpoint: str, model: str, timeout_ms: int = 4000,
                 transport: httpx.AsyncBaseTransport | None = None) -> None: ...
    async def classify(self, text: str) -> VoiceIntentResult: ...
```

`ALLOWED_INTENTS` = die sicheren Aktionen des Intent-Engines:
`{"confirm", "confirm_all", "next", "previous", "next_order", "problem", "photo", "pause", "done", "whats_next", "where", "how_many_left", "status", "repeat", "help"}`.

System-Prompt: knappe deutsche Beschreibung jedes Labels; Anweisung, **ausschließlich** JSON `{"intent": <label|unknown>, "confidence": <0..1>}` zu liefern und bei Unsicherheit `"unknown"` zu wählen. `_parse`: JSON laden, `intent` gegen `ALLOWED_INTENTS` prüfen (sonst `ok=False`), `confidence` clampen auf `[0,1]`.

## Zusammenführung im Router

Nach erfolgreichem `classify` (ok=True, intent gültig), wird das LLM-Ergebnis in ein `Intent` überführt und durch **dieselben** Nachbearbeitungsschritte geschickt wie ein deterministischer Treffer:

1. **Confidence-Klemme für Schreib-Intents:** ist `intent in {"confirm","confirm_all"}`, wird die LLM-Confidence auf höchstens `LLM_WRITE_CONFIDENCE_CAP = 0.85` begrenzt (< 0.90 Direkt-Schwelle) → das Frontend erzwingt immer Read-back.
2. **Negations-Guard:** `_apply_negation_guard(intent, normalized_text)` — ein „nicht ..." das das LLM trotzdem als confirm labelt wird zu `problem` heruntergestuft.
3. **Surface-Gating:** `_resolve_with_context(intent, surface=..., remaining_line_count=..., active_line_present=...)` — das LLM kann keine Route freischalten, die der Kontext verbietet.

Übernahme nur, wenn das aufbereitete LLM-Ergebnis eine höhere Confidence hat als das deterministische (analog zur bestehenden Segment-Fallback-Logik `if seg.confidence > intent.confidence`). Das Response-Feld `match_strategy` wird `"llm"`, damit Logs/Telemetrie den Pfad erkennen.

Bei `ok=False` (Timeout, Fehler, ungültig): keine Änderung, das deterministische Ergebnis (i. d. R. `unknown`) steht — das Frontend gibt dann das Phase-A-Feedback „Nicht verstanden".

## Config

```python
llm_voice_model: str = "qwen2.5:1.5b"
llm_voice_timeout_ms: int = 4000
# llm_endpoint wird wiederverwendet
```

Der Classifier wird einmalig (Modul-Singleton wie `whisper_client`) mit `settings.llm_endpoint`, `settings.llm_voice_model`, `settings.llm_voice_timeout_ms` konstruiert. In Tests wird er über einen injizierten Transport bzw. Monkeypatch ersetzt.

## Latenz-Schutz

- Häufige Kommandos matchen deterministisch → LLM wird nie gerufen.
- `llm_voice_timeout_ms = 4000` als harte Obergrenze (httpx read-timeout). Bei Überschreitung → `ok=False` → deterministisches Ergebnis.
- Kein Streaming; eine einzige Chat-Anfrage.

## Betroffene Einheiten

| Einheit | Datei | Änderung |
|---|---|---|
| Classifier | `backend/app/services/voice_intent_classifier.py` | neu |
| Config | `backend/app/config.py` | 2 Settings |
| Router | `backend/app/routers/voice.py` | LLM-Fallback nach Segment-Fallback verdrahten |
| Tests | `backend/tests/test_voice_intent_classifier.py` | neu |
| Tests | `backend/tests/test_voice_routes.py` (o. bestehende voice-Routen-Tests) | Integration: LLM-Fallback-Pfad |

## Testing (TDD)

- **Classifier-Unit** (mocked `httpx` transport): valides JSON → `VoiceIntentResult(ok=True, intent="next", confidence=...)`; Müll/kein JSON/unbekanntes Label → `ok=False`; Timeout/Exception → `ok=False`.
- **Router-Integration** (Classifier gemonkeypatcht):
  - deterministisch `unknown` + LLM `"next"@0.8` → Response `intent="next"`, `match_strategy="llm"`.
  - LLM `"confirm"@0.99` → Response-Confidence ≤ 0.85 (Write-Klemme) → Frontend würde Read-back erzwingen.
  - LLM „confirm" bei negiertem Text („nicht ok") → `problem` (Negations-Guard).
  - LLM `"confirm"` auf Surface LIST/ohne aktive Zeile → `unknown` (Surface-Gating).
  - `ok=False` → deterministisches `unknown` bleibt.
  - deterministischer Treffer ≥ 0.73 → LLM wird **nicht** gerufen (Classifier-Spy zählt 0 Aufrufe).
- Baseline: Backend 296/296 muss grün bleiben.

## Ops (kein Code, dokumentieren)

Einmalig im Ollama-Container das Modell laden:

```bash
docker compose exec ollama ollama pull qwen2.5:1.5b
```

Ohne das Modell liefert der Classifier `ok=False` (Fallback bleibt sauber) — Voice funktioniert weiter rein deterministisch, nur ohne LLM-Auffangnetz.

## Offene Punkte

- Exaktwerte `LLM_WRITE_CONFIDENCE_CAP` (0.85) und `llm_voice_timeout_ms` (4000) am echten 1.5b-Modell justieren.
- Modellwahl 1.5b vs 0.5b nach Live-Messung final bestätigen (Setting macht den Tausch trivial).
