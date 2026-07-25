# Voice Track 1 — Safety & Quality (Phase A)

**Datum:** 2026-07-25 · **HEAD:** 9c08ad8 · **Track:** Baustellen-Analyse Track 1 (Voice)
**Scope:** Phase A — deterministisch, offline, voll testbar. Ollama-Intent-Fallback ist **Phase B** (eigene Spec, später).

## Ziel

Voice als **hands-free Helfer** zum visuellen Picking, nicht als Vorleser. Drei Nutzerziele, aus dem Brainstorming:

1. **Sicher** — eine Fehlerkennung darf nie still eine echte Odoo-Buchung auslösen.
2. **Reagiert zuverlässig** — natürliche Kommandos („was jetzt", „passt", „auftrag fertig") greifen verlässlich; kein totes Schwellenband.
3. **Knapp** — redet nur auf Kommando, liest nie die ganze Liste, spricht Orte natürlich statt Codes zu buchstabieren.

## Interaktionsmodell (verbindlich)

**Still by default.** Nach einer Buchung sagt das System nichts. Der Picker steuert das Tempo per Kommando.

| Nutzer sagt | System tut | System sagt |
|---|---|---|
| „was jetzt?" / „was muss ich picken?" | liest aktuelle Position | „Pink Brick, 2 Stück, Regal 3." |
| „wo?" | — | „Regal 3." |
| „wieviel?" | — | „2 Stück." |
| „wie viele noch?" | — | „Noch 8." |
| „passt" / „ja" / „gebucht" (hohe Sicherheit) | bucht aktuelle Position | „Gebucht." (Echo, dann still) |
| „passt" (mittlere/niedrige Sicherheit) | **bucht NICHT sofort** | „Pink Brick, richtig?" → zweites Ja nötig |
| „auftrag fertig" / „alles gebucht" | **bucht NICHT sofort** | „12 Positionen buchen?" → zweites Ja nötig |
| „nicht ok" / „nein" / „falsch" | nichts gebucht | (keine Confirm-Auslösung) |
| unverständlich / STT leer | nichts | „Nicht verstanden, bitte nochmal." |

Das **20-Bricks-Problem** ist damit gelöst: nie Listen-Vorlesen. Immer nur die *eine* aktuelle bzw. nächste Position, und nur auf Kommando.

## Sicherheitsmodell für Schreib-Intents (der 💀-Fix)

Heute: `voice-confirm` simuliert einen Barcode-Scan (`app.js:2508-2509`) und bucht ab Confidence 0.78 still. `confirm_all` bucht alle Positionen. Eine 0.95-Fehlerkennung (siehe Negations-Bug) schreibt echte Odoo-Daten.

Neu — zwei Schreib-Intents, beide read-back-gated:

- **`confirm` (Einzelposition):**
  - Confidence ≥ `CONFIRM_DIRECT_THRESHOLD` (0.90) → buchen, danach hörbares Echo „Gebucht." (Picker hört sofort *was* passierte).
  - Confidence darunter (bis Fuzzy-Minimum) → **kein Buchen**, stattdessen Read-back „<Produkt>, richtig?"; erst ein folgendes `confirm` im hohen Band bucht.
- **`confirm_all` (Batch):** **immer** Read-back „<N> Positionen buchen?" unabhängig von Confidence; erst ein folgendes `confirm`/„ja" bucht.

Der simulierte-Scan-Pfad wird durch einen expliziten Confirm-Flow ersetzt, der immer echot was gebucht wurde. Ein „pending confirmation" bekommt eine TTL (z. B. 8 s), damit ein spätes beiläufiges „ja gut" nichts auslöst (Baustellen-Finding 🟡 Echo/Pending-TTL).

## Erkennung (Phase A, deterministisch)

### Negation reparieren
`_contains_negated_confirmation` feuert heute nur bei stimmt/richtig/passt (`intent_engine.py:60`). Verallgemeinern: **jede** Confirm-Klasse (alle `confirm`/`confirm_all`-Aliasse), wenn ein Negationsterm (`NEGATION_TERMS`) im selben Äußerungsfenster steht, wird unterdrückt — nicht als Confirm @ 0.95 gewertet, sondern als `uncertain`/Nachfrage. „nicht ok", „nicht gut", „nicht bestätigen" → kein Confirm.

### Totband schließen
Backend-Recovery endet 0.73 (`FUZZY_SINGLE_THRESHOLD`), Frontend-Automation ab 0.78 (`voice-runtime.mjs`). Ein **einheitliches Schwellenmodell**:
- Non-Write-Intents (Navigation/Abfrage): ausführen ab Fuzzy-Minimum (0.68/0.73), keine Rückfrage nötig.
- Write-Intents: hohes Band (≥0.90) → direkt mit Echo; Band [Fuzzy, 0.90) → Read-back. Kein Bereich fällt mehr durch beide Netze.
Konstanten an **einer** Stelle definiert (Backend intent_engine als Quelle, Frontend importiert/spiegelt via geteiltem Konstanten-Modul), damit sie nicht wieder driften.

### Whisper härten
`whisper_client.py` — `initial_prompt` mit Domänenvokabular (Produkt-/Brick-Namen aus dem aktiven Auftrag, „Regal", „Fach", „bestätigen", „Auftrag fertig", Zahlwörter). `no_speech_prob`/`avg_logprob` aus der Whisper-Antwort auswerten und Halluzinationen unter Schwelle verwerfen (→ „nicht verstanden").

### STT-Ausfall hörbar
Leeres Transkript oder Whisper-Fehler → `intent="unclear"` mit definierter UX: Toast **und** TTS „Nicht verstanden, bitte nochmal." Nie stiller Drop (`app.js:2479` erweitern).

### Englische Aliasse entschärfen
Aliasse/Fuzzy-Einträge entfernen, die deutsches Matching verschmutzen („eine"→„fine"→confirm 0.75; „gut" allein). Deutsche Bestätigung bleibt, englische Fehlpaare raus (Baustellen 🟡, live verifiziert).

## Knappe, natürliche TTS

`getLineSpeechPrompt` (`app.js:280`) und `formatLocationForSpeech` (`app.js:85`) neu:
- Ausgabe: **Produkt, Menge, kurzer Ort** — „Pink Brick, 2 Stück, Regal 3."
- Ort: Zone/Regal-Kurzform (`location_src_zone`/`location_src_short`), **nicht** der rohe Fach-Code. `formatLocationForSpeech` buchstabiert nie mehr Ziffernketten (heute „A3-8848" → „A 3 8848"). Wenn nur ein roher Code vorliegt, wird er sinnvoll gekürzt/weggelassen statt digit-by-digit gesprochen.
- Ein `voice_instruction_short`-Feld vom Backend hat weiterhin Vorrang (bereits im Payload).

## Neue/erweiterte Intents

- `whats_next` (Abfrage): liest aktuelle Position via neuer knapper TTS. Nicht-schreibend, keine Rückfrage.
- `where` / `how_many` / `how_many_left` (Abfragen): gezielte Teil-Antworten.
- Bestehende `status`/`repeat` ggf. auf dieses Modell mappen statt Duplikate.
Alle Abfrage-Intents sind read-only und lösen nie eine Buchung aus.

## Architektur / betroffene Einheiten

| Einheit | Datei | Änderung |
|---|---|---|
| Intent-Matching | `backend/app/services/intent_engine.py` | Negation generalisieren, Schwellenmodell, Abfrage-Intents, engl. Aliasse raus, Konstanten zentralisieren |
| Voice-Route | `backend/app/routers/voice.py` | Schreib-Intents mit Read-back-State, STT-unclear-Pfad, Abfrage-Intents beantworten |
| Whisper | `backend/app/services/whisper_client.py` | initial_prompt, no_speech_prob-Filter |
| Voice-Runtime | `pwa/js/voice-runtime.mjs` | Schwellen aus geteiltem Modell, Write vs. Non-Write-Routing |
| App-Voice-Handler | `pwa/js/app.js` | Read-back-Flow statt simuliertem Scan, Pending-TTL, still-nach-Buchung, STT-Feedback |
| TTS-Text | `pwa/js/app.js` | `getLineSpeechPrompt`/`formatLocationForSpeech` knapp + natürlich |

**Grenze zu Foundation:** Voice-Write-Pfad läuft über `get_write_request_context`/`get_request_odoo_client_or_grace` (bereits verdrahtet). Diese Spec ändert Auth **nicht**. `/voice/recognize` bleibt read-only.

## Testing (TDD, RED→GREEN)

- **Backend (pytest):** Negation-Matrix („nicht ok/gut/richtig/bestätigen" → kein confirm), Schwellenband (jeder Bereich hat definiertes Verhalten, kein Loch), Abfrage-Intents, whisper unclear→„unclear". Neue Tests zuerst rot.
- **Node (voice-runtime.test.mjs):** Write-Intent unter 0.90 → Read-back statt Buchung; confirm_all → immer Read-back; non-write ab Fuzzy ausführen.
- **PWA-Verhalten (api.test.mjs / app-Tests):** kein Buchen ohne zweites Ja bei Batch; Echo „gebucht" bei Einzel-Buchung; still nach Buchung; STT-leer → Feedback; TTS-Text enthält keine buchstabierte Ziffernkette.
- Baseline: Backend 288/288 muss grün bleiben, Node-Suites grün.

## Abgrenzung (NICHT in Phase A)

- Ollama-Intent-Fallback für freie Sätze → **Phase B**.
- Piper-Robustheit/Stimmen-Konsistenz, Latenz-Metriken-Persistenz, Voice-für-Serial (Track 5) → separat.
- Sprach-Mengeneingabe/Check-Digit-Reaktivierung → optional in Phase B (Kontext-Verdrahtung nötig).

## Offene Punkte

- Genaue Werte `CONFIRM_DIRECT_THRESHOLD` (Vorschlag 0.90) und Read-back-TTL (Vorschlag 8 s) — in der Umsetzung an echten Whisper-Confidences justieren.
- Mechanik der geteilten Schwellen-Konstanten Backend↔Frontend (generiertes JSON vs. dupliziert-mit-Test) — im Plan festlegen.
