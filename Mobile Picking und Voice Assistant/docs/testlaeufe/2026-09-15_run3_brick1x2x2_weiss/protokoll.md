# Testlauf 3 — Schadensmeldung mit lokaler Bilderkennung, Threadzahl als Variable

**Datum:** 15.09.2026
**Auftrag:** L1/OUT/00304, Position 1 von 5
**Artikel:** Brick 1x2x2 weiß, SKU 6101121, Regal A-02, 8 Stück, Fischer Techniklabor AG
**Zweck:** Nachweis, ob die Threadzahl von llama.cpp die Ursache der Zeitüberschreitungen
in den Läufen 1 und 2 ist.

Alle Zeitangaben stammen aus den Container-Logs und sind in UTC notiert, wie dort protokolliert.
Die Ortszeit liegt zwei Stunden davor (06:45:44 UTC = 08:45:44 MESZ).

## 1. Aufbau

| Komponente | Wert |
|---|---|
| Picking-PWA | `https://localhost/`, Auftrag L1/OUT/00304, Position 1 von 5 |
| Backend | `mobilepickingundvoiceassistant-backend` |
| Workflow | n8n „Quality Assessment v2", published |
| Odoo | Quality Alerts (`action-307`) |
| Inferenz | ollama/ollama:latest, CPU-Betrieb |
| Modelle | `qwen2.5:7b` (Textbewertung), `gemma4:12b` (Artikelabgleich und Schadensprüfung) |

Der Lauf besteht aus zwei Versuchen mit **identischem Eingangsmaterial** — gleicher Auftrag,
gleiche Position, dasselbe Foto, derselbe Meldungstext. Verändert wurde allein die Threadzahl,
mit der llama.cpp rechnet.

| | Versuch A | Versuch B |
|---|---|---|
| Threadzahl | 14 (Vorgabe aus der Docker-CPU-Zahl) | 8 (`options.num_thread` im Request) |
| Alert | QA/0367 | siehe Abschnitt 5 |
| n8n-Execution | #139 | siehe Abschnitt 5 |

## 2. Eingangsdaten

Vorlage war das echte Produktbild aus der PWA
(`https://localhost/api/products/72/image?size=1024`, 1 224 Byte PNG), abgelegt als
`run3_brick_1x2x2_weiss_p72.png`.

Daraus erzeugte ChatGPT ein Schadensfoto: schräg von oben, eine Noppe abgebrochen, Riss in der
Seitenwand, Lagerhintergrund aus Karton und Regalboden. Das Original liegt als
`fotos_original/run3_damage_01.png` (1 884 186 Byte), die auf 1 024 px skalierte Fassung als
`fotos/qa_photo_01.jpg` (128 410 Byte). Prüfsummen in `pruefsummen.txt`.

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Artikel beschaedigt: Brick 1x2x2 weiss (SKU 6101121), Regal A-02.
              Noppe abgebrochen, Riss in der Seitenwand. Nicht versandfaehig.
              Foto angehaengt.
Fotos:        1
```

Ein Foto, wie in Lauf 2 — damit sind die drei Läufe untereinander vergleichbar.

## 3. Vorbereitende Messung: wirkt `OLLAMA_NUM_THREAD`?

Aus Lauf 1 und 2 stand die Frage offen, ob die Umgebungsvariable `OLLAMA_NUM_THREAD`
die Threadzahl von llama.cpp überhaupt beeinflusst. Gemessen auf leerem Ollama,
`qwen2.5:7b`, 60 Token Ausgabelänge, identischer Prompt, `temperature: 0`:

| Variante | Ladezeit | eval | Durchsatz |
|---|---|---|---|
| nur Umgebungsvariable gesetzt, kalt | 47,4 s | 59,5 s | 1,01 tok/s |
| nur Umgebungsvariable gesetzt, warm | 0,2 s | 49,6 s | 1,21 tok/s |
| `options.num_thread: 8` im Request | 23,5 s | 8,1 s | **7,40 tok/s** |

Der ollama-Log belegt die Ursache direkt: die ersten beiden Anfragen starteten mit
`n_threads = 14 (n_threads_batch = 14) / 14`, die dritte mit `n_threads = 8 (n_threads_batch = 8) / 14`.

**Ergebnis: Die Umgebungsvariable wirkt nicht.** Sie wurde deshalb aus dem ollama-Dienst
in `docker-compose.yml` entfernt; der Kommentar dort hält den Messwert fest. Der wirksame Hebel
ist `num_thread` in den `options` des Requests und steht jetzt in
`backend/app/services/vision_client.py`, `llm_client.py` und `voice_intent_classifier.py`.

## 4. Versuch A — 14 Threads

Versuch A lief **vor** dem Wirksamwerden der Änderung. Der Grund ist selbst ein Befund:
Der Stack mountete den Backend-Code nicht aus dem Projektverzeichnis, sondern aus dem
Worktree `C:/Users/endri/Desktop/Bachelor/.worktrees/voice-latency/Mobile Picking und Voice Assistant/backend/app`.
Die Änderung im Projektverzeichnis erreichte den Container also nicht. Belegt ist das doppelt:
die Datei im Container enthielt `num_thread` nicht, und der ollama-Log zeigt für beide
Produktivanfragen `n_threads = 14`.

| Zeit (UTC) | Δ zum Start | Ereignis | Quelle |
|---|---|---|---|
| 06:45:44,508 | 0 s | `POST /api/quality-alerts` → 200 OK | backend.log |
| 06:45:44,956 | 0,4 s | `POST http://n8n:5678/webhook/quality-assessment-v2` → 200 OK | backend.log |
| 06:45:44,847 | 0,3 s | n8n-Execution #139 startet | n8n `/rest/executions` |
| 06:45:53,582 | 9,1 s | ollama lädt Runner `qwen2.5:7b`, `n_threads = 14` | ollama.log |
| 06:47:14,959 | 90,5 s | `llm_quality_disposition_failed`, Modell `qwen2.5:7b`, `error` leer | backend.log |
| 06:47:30,264 | 105,8 s | `embed_katalog`: 47 Artikel, **14 052 ms** | backend.log |
| 06:47:30,519 | 106,0 s | `embed_abgleich`: Urteil **mismatch**, **254 ms** | backend.log |
| 06:49:04,118 | 199,6 s | ollama lädt Runner `gemma4:12b`, Ladezeit **92,8 s**, `n_threads = 14` | ollama.log |
| 06:50:50,492 | 306,0 s | `vision_probe_failed`, `gemma4:12b`, `ReadTimeout`, **200 014 ms** | backend.log |

Der Bildaufruf lief exakt in den konfigurierten Grenzwert `vision_timeout_ms = 200000`
(`backend/app/config.py:187`). Ollama selbst brauchte laut Log rund 202 s (Laden 92,8 s,
Bilddekodierung 27,1 s, Prompt-Verarbeitung 55,8 s) und gab den Slot 1,7 s nach dem
clientseitigen Abbruch frei — im ollama-Log als `[GIN] 500 3m20s POST /api/generate`
mit anschließendem `srv stop: cancel task`.

Der Einbettungsabgleich ordnete das Foto wieder dem Artikel `301124` zu:

```json
{"event_type": "embed_abgleich", "urteil": "mismatch", "grund_art": "anderer_artikel",
 "erwartet": "6101121",
 "rang": [["301124", 0.4957], ["4183780", 0.4186], ["4159527", 0.401]],
 "abstand": 0.0772, "duration_ms": 254}
```

Damit gewinnt `301124` (Brick 2x2 hellgrün) zum **dritten** Mal in Folge — in Lauf 1 gegen ein
gelbes 2x2-Foto (0,7634), in Lauf 2 gegen ein weißes 1x2x2-Foto (0,514), hier gegen dasselbe
Motiv (0,4957). Der erwartete Artikel steht nicht unter den ersten drei.

**Versuch A ist damit die Wiederholung von Lauf 2, nicht dessen Gegenprobe.**
Er dient als Referenzpunkt unter gleichen Bedingungen am selben Tag.

### Nebenbefund: irreführende Fehlermeldung in der PWA

Beim Öffnen des Auftrags meldete die PWA „Profil bitte neu wählen." Die tatsächliche Ursache war
ein fehlender CSRF-Token: er liegt im `sessionStorage` und überlebt keinen neuen Tab
(`pwa/js/api.js:223`). `POST /api/pickings/302/claim` kam mit 403 und `{"detail":"CSRF-Token fehlt."}`
zurück, die Oberfläche deutet 403 aber pauschal als Profilproblem
(`pwa/js/app.js:2031`). Behoben für diesen Lauf durch einen Aufruf von `POST /api/auth/csrf`.
Der Fehlertext gehört nachgezogen, sonst führt er bei jedem Lauf in die falsche Richtung.

## 5. Versuch B — 8 Threads

Für Versuch B wurde der Stack aus dem Projektverzeichnis neu gestartet, damit der Container den
geänderten Code mountet (`docker compose up -d`). Beide Modelle wurden vorher mit den
Produktiv-Kontextgrößen geladen (`gemma4:12b` mit `num_ctx 8192`, `qwen2.5:7b` mit 4 096), damit
Versuch B gegen Lauf 2 und Versuch A vergleichbar ist: warme Modelle, ein Foto.

Alert: **QA/0368** (Odoo-Datensatz-ID 369).

| Zeit (UTC) | Δ zum Start | Ereignis | Quelle |
|---|---|---|---|
| 06:59:53,2 | 0 s | Absenden in der PWA | Browser |
| 06:59:5x | ≈0,5 s | `POST /api/quality-alerts` → 200 OK | backend.log |
| 06:59:55,234 | 2,0 s | `POST http://n8n:5678/webhook/quality-assessment-v2` → 200 OK | backend.log |
| ≈07:00:07 | ≈14 s | Textbewertung `qwen2.5:7b` beginnt (Task 4) | ollama.log |
| ≈07:01:18 | ≈85 s | Textbewertung fertig: **70 952 ms**, 809 Prompt-Token, 120 erzeugte Token | ollama.log |
| 07:01:19,577 | 86,4 s | `embed_katalog`: 47 Artikel, **11 751 ms** | backend.log |
| 07:01:19,823 | 86,6 s | `embed_abgleich`: Urteil **mismatch**, **244 ms** | backend.log |
| 07:01:19,825 | 86,6 s | `article_compare`: `same_article = false` | backend.log |
| ≈07:01:20 | ≈87 s | Bildprüfung `gemma4:12b` beginnt (Task 6), Bilddekodierung **19 321 ms** | ollama.log |
| 07:02:16,474 | 143,3 s | `vision_probe`, `gemma4:12b`, **56 653 ms**, **`ok: true`** | backend.log |
| 07:02:16 | 143,3 s | `POST /api/internal/n8n/v2/callbacks/status` → 200 OK | backend.log |
| 09:02 MESZ | — | Odoo schreibt `ai_last_analyzed_at` | Odoo-Datensatz |

**Gesamtlaufzeit: rund 2 min 23 s.** Kein Grenzwert gerissen.

### 5.1 Inferenzzeiten im Einzelnen

| Aufgabe | Modell | Prompt | Erzeugte Token | Prompt-Durchsatz | Erzeugung | Gesamt |
|---|---|---|---|---|---|---|
| Textbewertung | `qwen2.5:7b` | 809 Token | 120 | 15,94 tok/s | 5,94 tok/s | **70,95 s** |
| Bildprüfung | `gemma4:12b` | 439 Token + 1 Bild | 77 | 11,65 tok/s | 4,34 tok/s | **55,42 s** |

Die Bilddekodierung kostete zusätzlich 19,3 s und ist in den 56,7 s enthalten, die der Backend-Client
gemessen hat. Der ollama-Log weist für beide Aufrufe `n_threads = 8 (n_threads_batch = 8) / 14` aus.

### 5.2 Ergebnis der Systembewertung

Beide Stufen lieferten erstmals ein Ergebnis:

```
Analyse-Status: Manuelle Pruefung noetig
Fotoanalyse:
  Artikel: FALSCHES TEIL -- Foto passt zu 301124 (0.496), nicht zum bestellten
           Artikel 6101121 (dort Platz 5).
  Artikel: nächste Treffer im Katalog -- 301124 0.496, 4183780 0.419, 4159527 0.401.
  Schaden: SICHTBAR -- torn/broken edge near the top right cylinder,
           crack/split along the side.
  Texturteil der Meldung (nicht wirksam): scrap, Konfidenz 0.95.
           Noppe abgebrochen und rissiger Bricks sind unbrauchbar.
Grund: Foto widerspricht der Meldung, siehe Fotoanalyse.
```

**Die Schadenserkennung traf zu.** `gemma4:12b` benannte beide Schäden des generierten Fotos —
die abgebrochene Noppe („torn/broken edge near the top right cylinder") und den Riss in der
Seitenwand („crack/split along the side"). Die Textbewertung kam unabhängig davon auf `scrap`.

Der Endzustand bleibt `review_required`, aber aus einem **anderen** Grund als in den Läufen 1, 2
und in Versuch A: dort lautete er `assessment unavailable` (kein Ergebnis), hier
„Foto widerspricht der Meldung" (Ergebnis vorhanden, Artikelachse widerspricht). Das ist die
dokumentierte Sollreaktion bei `same_article = false`.

## 6. Vergleich der drei Läufe

| | Lauf 2 (14.09.) | Versuch A (15.09.) | Versuch B (15.09.) |
|---|---|---|---|
| Threads | 14 | 14 | **8** |
| Modelle | warm | kalt (`gemma4` 92,8 s Ladezeit) | warm |
| Fotos | 1 | 1 | 1 |
| Textbewertung | Abbruch nach 90 s | Abbruch nach 90 s | **70,95 s, Ergebnis** |
| Bildprüfung | 189,5 s | `ReadTimeout` nach 200,0 s | **56,65 s, `ok: true`** |
| Gesamtlaufzeit | 4 min 30,5 s | rund 5 min 6 s | **2 min 23 s** |
| Endzustand | `assessment unavailable` | `assessment unavailable` | Bewertung vorhanden |

Der einzige Unterschied zwischen A und B ist die Threadzahl; Auftrag, Position, Foto (identische
MD5-Summe), Meldungstext und Priorität sind gleich. Die Bildprüfung wurde um **Faktor 3,5**
schneller (200,0 s Abbruch gegen 56,7 s Ergebnis), die Kette insgesamt um mehr als die Hälfte.

**Damit ist die Ursache der Zeitüberschreitungen belegt: die Threadzahl, nicht die Modellwahl.**

## 7. Abweichungen und Einschränkungen

1. Versuch B benutzte dasselbe Foto unter anderem Dateinamen
   (`qa_photo_01_versuch_b.jpg`, MD5 identisch mit `qa_photo_01.jpg`). Grund: Der
   Idempotenzschlüssel der PWA besteht aus Auftrag, Position, Priorität, Beschreibung und
   `Dateiname:Größe` (`pwa/js/app.js:3486`). Bei identischer Eingabe antwortete das Backend mit
   dem bereits angelegten Alert, ohne n8n erneut anzustoßen. Der Bildinhalt ist unverändert.
2. Versuch A lief mit kalten Modellen, Versuch B mit warmen. Der Vergleich der reinen
   Inferenzzeiten (200,0 s gegen 56,7 s) ist davon unberührt, die Gesamtlaufzeiten sind es nicht.
3. Der Einbettungsabgleich bleibt unverändert schwach: `301124` gewinnt zum dritten Mal in Folge,
   diesmal mit 0,4957 gegen einen erwarteten Artikel auf Platz 5. Der Gegentest mit dem
   unveränderten Katalogbild steht weiterhin aus.
4. Odoo protokolliert unverändert alle 13–15 s
   `RuntimeError: Couldn't bind the websocket. Is the connection opened on the evented port (8072)?`.
   Bekannte Vorbelastung, unabhängig von der Meldungskette.

## 8. Geänderte Dateien

| Datei | Änderung |
|---|---|
| `backend/app/services/vision_client.py` | `_NUM_THREAD` und `num_thread` in den `options` |
| `backend/app/services/llm_client.py` | dito, drei Aufrufstellen |
| `backend/app/services/voice_intent_classifier.py` | dito |
| `docker-compose.yml` | `OLLAMA_NUM_THREAD` aus dem ollama-Dienst entfernt, Messwert als Kommentar |

## 9. Belege im Laufordner

| Datei | Inhalt |
|---|---|
| `run3_brick_1x2x2_weiss_p72.png` | Produktbild aus der PWA, Vorlage für ChatGPT |
| `fotos_original/run3_damage_01.png` | von ChatGPT erzeugtes Schadensfoto |
| `fotos/qa_photo_01.jpg` | auf 1 024 px skalierte Fassung, Eingabe Versuch A |
| `fotos/qa_photo_01_versuch_b.jpg` | identische Kopie, Eingabe Versuch B |
| `pruefsummen.txt` | MD5-Summen |
| `logs/backend.log`, `logs/ollama.log`, `logs/n8n.log`, `logs/odoo.log` | Container-Logs Versuch B |
| `logs/versuch_a_backend_ausschnitt.log`, `logs/versuch_a_ollama_ausschnitt.log` | gesicherte Auszüge Versuch A (Container wurde danach neu erstellt) |

## 10. Angefangen, nicht abgeschlossen: Textmodell-Vergleich

Offen war die Frage, ob `gemma4:12b` die Textbewertung mit übernehmen kann und damit das zweite
Modell im Speicher überflüssig macht. Gemessen wurde mit dem Produktiv-Systemprompt und dem
Nutzerprompt aus `llm_client._build_user_prompt`, Meldungstext aus diesem Lauf,
`options.num_thread: 8` (`.claude/skills/qa-testlauf/scripts/bench_text_models.py`):

| Modell | Wanduhr | Erzeugung | Token | Rate | Urteil |
|---|---|---|---|---|---|
| `qwen2.5:7b`, warm | 19,9 s | 18,9 s | 119 | 6,30 tok/s | `scrap`, Konfidenz 0,95 |
| `gemma4:12b` | — | — | — | — | **nicht gemessen** |

`gemma4:12b` kam zweimal nicht zustande. Der erste Versuch endete nicht als Hänger, sondern als
Absturz — belegt im ollama-Log:

```
time=2026-09-15T07:04:40.797Z level=INFO source=sched.go:651 msg="Load failed"
  model=/root/.ollama/models/blobs/sha256-1278394b6936... (= gemma4:12b)
  error="llama-server process has terminated: signal: killed"
panic: runtime error: invalid memory address or nil pointer dereference
```

Der Ladeprozess wurde abgeschossen (`signal: killed`), während `qwen2.5:7b` im Speicher lag;
ollama lief anschließend in einen Nil-Pointer-Absturz (`Scheduler.load`, `sched.go:652`) und
startete neu.

**Warum der Prozess abgeschossen wurde, ist nicht geklärt.** Naheliegend wäre Speichermangel:
`gemma4:12b` belegt geladen 9,2 GiB und repackt zusätzlich 5,0 GiB
(`CPU_REPACK model buffer size = 5003.44 MiB`), `qwen2.5:7b` weitere 5,1 GiB, die Docker-VM hat
25 GiB. Dagegen spricht die Messung zum Absturzzeitpunkt: laut `docker stats` waren noch rund
25,3 GiB frei, und am Container ist kein Speicherlimit gesetzt (`HostConfig.Memory = 0`,
`OOMKilled = false`). Die Erklärung bleibt damit eine Vermutung.

Zwei weitere Ladeversuche nach einem Neustart von ollama, allein auf leerem Speicher, liefen
acht bzw. sechs Minuten in `load_tensors: CPU_REPACK` ohne weitere Logzeile. Beide enden im Log
als `timed out waiting for llama-server to start: context canceled` — das `context canceled`
stammt von **meinem** Abbruch, nicht von ollama. Sie belegen also kein Scheitern, sondern nur ein
Laden, das länger dauerte, als ich gewartet habe. Zum Vergleich: dasselbe Modell lud am selben
Tag über denselben Weg zweimal in 87 s und 93 s.

Der Modellvergleich steht aus.

Für die Wiederholung: ollama neu starten, mit `docker logs ... | Select-String "signal: killed|panic:"`
gegenprüfen und die Ladezeit von `gemma4:12b` einzeln messen, bevor der Vergleich gefahren wird.

Was aus dem Lauf trotzdem folgt: Beide Bildstufen laufen bereits auf `gemma4:12b`
(`vision_model` und `vision_article_model`, `backend/app/config.py:150,178`). Nur die
Textbewertung hängt an `qwen2.5:7b`. Würde sie auf `gemma4:12b` wechseln, entfiele ein
Modell-Ladevorgang — in Versuch A allein 92,8 s. Gegenrechnung: 12B statt 7B kostet je Token mehr.
Ohne die fehlende Messung ist die Frage nicht entschieden.
