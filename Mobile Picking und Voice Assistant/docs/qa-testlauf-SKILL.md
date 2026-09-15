---
name: qa-testlauf
description: Führt einen dokumentierten End-to-End-Testlauf der Qualitätsmeldung durch — Picking-PWA (Problem melden mit Fotos) → Backend → n8n "Quality Assessment v2" → lokale Bilderkennung (ollama) → Odoo Quality Alert. Erzeugt Schadensfotos über ChatGPT aus dem echten Produktbild, misst die Laufzeiten pro Stufe und legt ein Protokoll unter docs/testlaeufe/ ab. Verwenden, wenn der Nutzer einen QA-Testlauf, Bilderkennungs-Test, Schadensmeldungs-Test, Quality-Alert-Test oder eine Messung der Modelllaufzeiten verlangt.
---

# QA-Testlauf: Schadensmeldung mit Bilderkennung

Ziel: einen reproduzierbaren, für die Bachelorarbeit zitierfähigen Testlauf erzeugen. Jeder Lauf hinterlässt einen Ordner mit Bildern, Logs, Zeitmessungen und einem Protokoll.

## Voraussetzungen prüfen

```powershell
docker ps --format "{{.Names}} {{.Status}}"
```

Erwartet: `backend`, `pwa`, `n8n`, `odoo`, `odoo-lager-2`, `caddy`, `db`, `ollama` laufen (Präfix `mobilepickingundvoiceassistant-`).

Browser-Tabs, die in derselben Claude-Tabgruppe liegen müssen:

| Zweck | URL |
|---|---|
| Picking Assistant | `https://localhost/` |
| ChatGPT (Bildgenerierung) | `https://chatgpt.com/` |
| Odoo Quality Alerts | `http://127.0.0.1:8069/odoo/action-307` |
| n8n Executions | `http://127.0.0.1:5678/workflow/<id>/executions` |

## Browser-Besonderheiten (wichtig, sonst blockiert der Lauf)

Der Picking Assistant und ChatGPT kollabieren ihr Layout, sobald ihr Tab `document.visibilityState === "hidden"` ist: Elemente haben dann `getBoundingClientRect().width === 0`. Folgen:

- **Screenshots** und **Klicks/Tastatur über Koordinaten** funktionieren auf diesen Tabs nur, wenn der Tab sichtbar ist. `Page.captureScreenshot` läuft sonst in einen 30-s-Timeout, weil ohne `requestAnimationFrame` kein Compositor-Frame entsteht.
- **JavaScript funktioniert immer**, auch auf versteckten Tabs. Deshalb den ganzen Lauf per `javascript_tool` fahren, nicht per Maus.
- Der aktive Tab lässt sich nicht selbst umschalten: `window.focus()` wird von Chrome blockiert, und neu erstellte Tabs übernehmen den Fokus nicht. Odoo und n8n rendern auch versteckt normal und sind blind bedienbar.

Bewährte Bausteine:

```js
// Text in ein React-kontrolliertes <textarea> schreiben
const ta = document.querySelector('textarea');
const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
setter.call(ta, 'Meldungstext');
ta.dispatchEvent(new Event('input', { bubbles: true }));
```

```js
// Text in ChatGPTs contenteditable-Composer schreiben und absenden
const t = document.querySelector('#prompt-textarea');
t.focus();
document.execCommand('selectAll');
document.execCommand('insertText', false, 'Prompt-Text');
document.querySelector('#composer-submit-button, [data-testid="send-button"]').click();
```

Direktes Tippen (`computer: type`) in den ChatGPT-Composer zerschießt den Inhalt — immer `execCommand` verwenden.

```js
// Bild aus der Seite heraus auf die Platte laden (umgeht fehlende Session im Shell-Kontext)
const r = await fetch(url);                // url = img.src, gleiche Origin-Session
const b = await r.blob();
const u = URL.createObjectURL(b);
const a = document.createElement('a');
a.href = u; a.download = 'datei.png';
document.body.appendChild(a); a.click(); a.remove();
```

Die Datei landet in `C:\Users\endri\Downloads`. Das funktioniert auch bei verstecktem Tab.

Warten auf ChatGPT: `document.querySelector('[data-testid="stop-button"]')` existiert, solange generiert wird. Bilder werden aus dem DOM entladen, wenn der Tab lange versteckt ist — dann vor dem Download neu einlesen (`main img`, letztes Element ist das neueste).

## Ablauf

### 1. Lauf anlegen und Referenzbild holen

Auftrag im Picking Assistant öffnen, Artikel und SKU notieren. Produktbild-URL aus dem DOM lesen und herunterladen:

```js
[...document.images].map(i => ({ src: i.currentSrc, w: i.naturalWidth }));
// -> https://localhost/api/products/<id>/image?size=1024
```

Dieses Bild ist die Vorlage für ChatGPT. Ein Download per PowerShell scheitert mit
`{"detail": "Ungueltige oder abgelaufene Sitzung."}` — nur der Weg über die Seite funktioniert.

### 2. Schadensfotos erzeugen

Vorlagebild an ChatGPT anhängen (`file_upload` auf das sichtbare `input[type=file]` mit `accept="image/*"`), dann pro Perspektive einen Prompt senden. Bewährte Serie:

1. schräg von oben, abgebrochene Noppe + Riss
2. strenge Draufsicht, Noppe komplett abgebrochen
3. Nahaufnahme von der Seite, langer Riss
4. schräg von hinten/unten, abgeplatzte Ecke, Kratzer
5. im geöffneten Karton im Regal, Blitzlicht

Jedes Bild direkt nach Fertigstellung herunterladen (`damage_01.png` … `damage_05.png`).

### 3. Bilder aufbereiten

```powershell
pwsh -File .claude/skills/qa-testlauf/scripts/prepare-photos.ps1 -Quelle "$HOME\Downloads" -Ziel "<laufordner>"
```

Skaliert auf 1024 px JPEG (entspricht `DAMAGE_MAX_EDGE`), baut einen Kontaktabzug und schreibt MD5-Summen. Nötig, weil fünf PNG-Originale zusammen das 10-MB-Limit von `file_upload` sprengen.

### 4. Meldung absenden

Im Picking Assistant: „Problem" → „Artikel beschädigt" → Beschreibung setzen → `file_upload` der fünf JPEGs auf `input[type=file]` → „Absenden" per `.click()`.

Vor dem Absenden prüfen:

```js
const fi = document.querySelector('input[type=file]');
({ files: [...fi.files].map(f => f.name),
   chip: [...document.querySelectorAll('button.qa-chip--active')].map(b => b.textContent.trim()),
   desc: document.querySelector('textarea').value });
```

Die Textarea zieht Diktat-Eingaben an, wenn der Tab den Fokus hat — Inhalt immer gegenprüfen.

### 5. Kette verifizieren

```powershell
docker logs --since 5m mobilepickingundvoiceassistant-backend-1 2>&1 |
  Select-String "quality-alerts|webhook/quality-assessment"
```

Erwartet: `POST /api/quality-alerts ... 200 OK` und `POST http://n8n:5678/webhook/quality-assessment-v2 ... 200 OK`.

Danach n8n-Execution-Nummer und Odoo-Alert-Referenz (`QA/xxxx`) notieren.

### 6. Laufzeiten messen

```powershell
pwsh -File .claude/skills/qa-testlauf/scripts/collect-evidence.ps1 -Laufordner "<laufordner>"
```

Sammelt Logs von backend, n8n, ollama, odoo und zieht die Modell-Zeitmarken heraus.

Relevante Werte für die Arbeit:

- Modell-Ladezeit (Kaltstart) aus `srv llama_server: model loaded` bzw. `msg="loaded runners"`
- Laufzeit je Inferenz aus den `prompt eval time` / `eval time` / `total time`-Zeilen
- Gesamtlaufzeit der n8n-Execution aus der Executions-Liste

### 7. Protokoll schreiben

`protokoll.md` im Laufordner, Abschnitte: Aufbau, Eingangsdaten, Zeitmarken, Ergebnis der Systembewertung, Abweichungen, Bewertung. Immer absolute Uhrzeiten, keine relativen Angaben.

## Bekannte Zeitschranken

| Schranke | Wert | Quelle |
|---|---|---|
| Ollama-Timeout je Aufruf | 200 s | `backend/app/config.py:187` (`vision_timeout_ms`) |
| Budget aller Vergleiche einer Meldung | 240 s | `backend/app/config.py:192` (`vision_budget_ms`) |
| Wartezeit auf die Assessment-Sperre | 150 s | `backend/app/config.py:235` (`assessment_wait_ms`) |
| n8n-Node-Timeout des Rückrufs | 270 s | `n8n/workflows/quality-assessment-v2.json:251` |

Nur **eine** Bewertung gleichzeitig (`_ASSESSMENT_GATE = asyncio.Semaphore(1)`, `backend/app/routers/n8n_v2.py:115`). Warten (bis 150 s) plus Laufzeit (bis 240 s) übersteigt das n8n-Timeout von 270 s. Deshalb Testmeldungen **nicht** kurz hintereinander absetzen, sondern erst absenden, wenn die vorherige Execution abgeschlossen ist.

Modelle: Artikelabgleich und Schadensprüfung beide `gemma4:12b`, Textbewertung `qwen2.5:7b`
(`backend/app/config.py:116,150,178`). Gemessen am 15.09.2026 mit `num_thread: 8` und warmen
Modellen: Textbewertung 71,0 s, Bildprüfung 56,7 s, Kette gesamt 2 min 23 s.

## Stolperfallen der Umgebung — vor jedem Lauf prüfen

**1. Mountet der Container den Code, den du änderst?** Der Stack lief am 15.09.2026 aus einem
Worktree, Änderungen im Projektverzeichnis erreichten den Container nie:

```powershell
docker inspect mobilepickingundvoiceassistant-backend-1 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
```

Zeigt das eine andere Quelle als das Projektverzeichnis, `docker compose up -d` aus dem
Projektverzeichnis ausführen. Gegenprobe im Container, nicht auf der Platte:

```powershell
docker exec mobilepickingundvoiceassistant-backend-1 grep -c num_thread /app/app/services/vision_client.py
```

**2. Threadzahl prüfen.** Ohne `options.num_thread` startet llama.cpp mit 14 Threads und die Kette
reißt jedes Zeitbudget. Der ollama-Log sagt es je Modell-Ladevorgang:

```powershell
docker logs --since 10m mobilepickingundvoiceassistant-ollama-1 2>&1 | Select-String "n_threads ="
```

Erwartet: `n_threads = 8 (n_threads_batch = 8) / 14`. Die Umgebungsvariable `OLLAMA_NUM_THREAD`
am ollama-Dienst wirkt **nicht** — gemessen 1,21 tok/s mit Variablen gegen 7,40 tok/s mit der
Option im Request.

**3. Modelle vor dem Lauf warmlaufen lassen**, sonst misst du Ladezeiten statt Inferenz
(`gemma4:12b` lädt 87–93 s). Wichtig: mit der **Produktiv-Kontextgröße**, sonst lädt ollama das
Modell beim ersten echten Aufruf neu. `vision_client` benutzt `num_ctx: 8192`, `llm_client` die
Vorgabe 4096.

**4. CSRF-Token fehlt in jedem neuen Tab.** Er liegt im `sessionStorage` (`pwa/js/api.js:223`).
Ohne ihn kommt `POST /api/pickings/<id>/claim` mit 403 zurück, und die PWA meldet irreführend
„Profil bitte neu wählen." Vorher setzen:

```js
const j = await fetch('/api/auth/csrf', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}).then(r=>r.json());
sessionStorage.setItem('picking-assistant-csrf', j.csrf_token);
```

**5. `gemma4:12b` lädt nicht immer.** Am 15.09.2026 wurde der Ladeprozess abgeschossen, während
`qwen2.5:7b` im Speicher lag; ollama lief danach in einen Nil-Pointer-Absturz und startete neu:

```
msg="Load failed" error="llama-server process has terminated: signal: killed"
panic: runtime error: invalid memory address or nil pointer dereference
```

Ursache ungeklärt. Speichermangel liegt nahe (Docker-VM 25 GiB; `gemma4:12b` 9,2 GiB geladen plus
5,0 GiB Repack-Puffer, `qwen2.5:7b` 5,1 GiB), ist aber nicht belegt: `docker stats` zeigte zum
Zeitpunkt rund 25,3 GiB frei, `OOMKilled = false`, kein Speicherlimit am Container. Danach lud das
Modell auch allein nicht mehr innerhalb von acht Minuten, obwohl es vorher zweimal 87 s und 93 s
gebraucht hatte. Vor Modellmessungen deshalb `docker restart` auf ollama und die Ladezeit einzeln
messen, bevor der eigentliche Vergleich läuft. Prüfen mit:

```powershell
docker logs mobilepickingundvoiceassistant-ollama-1 2>&1 | Select-String "signal: killed|panic:"
```

**6. Idempotenz blockiert die Wiederholung.** Der Schlüssel besteht aus Auftrag, Position,
Priorität, Beschreibung und `Dateiname:Größe` (`pwa/js/app.js:3486`). Zweimal dieselbe Meldung
liefert denselben Alert zurück, ohne n8n anzustoßen — erkennbar daran, dass im backend-Log die
Zeile `POST http://n8n:5678/webhook/quality-assessment-v2` fehlt. Für einen Wiederholungslauf mit
identischem Bildinhalt: dieselbe Datei unter anderem Namen hochladen und die MD5-Gleichheit im
Protokoll belegen.

**7. Ein abgebrochener Client beendet keine Generierung in ollama.** Am 15.09.2026 lief eine per
`TaskStop` abgebrochene Modellmessung weiter, erzeugte 1 718 Token, belegte acht Kerne, verdrängte
`qwen2.5:7b` aus dem Speicher und trieb den nächsten Lauf in den 270-s-Abbruch. Vor **jedem** Lauf:

```powershell
docker stats --no-stream mobilepickingundvoiceassistant-ollama-1
```

Steht die CPU über 100 %, läuft noch etwas. Aufräumen nur über `docker restart` des Containers.

**8. Die Fotoanzahl ist in Odoo gedeckelt, nicht im Backend.** `QA_MAX_ASSESSMENT_PHOTOS`, Vorgabe
3 (`odoo/addons/quality_alert_custom/models/quality_alert.py`). Ein Lauf mit vier Fotos prüft drei
und schreibt `Fotos: 1 weitere ungeprüft.` ins Formular — das ist kein Fehler. Für Messungen mit
mehr Fotos die Variable setzen und odoo neu starten:

```powershell
$env:QA_MAX_ASSESSMENT_PHOTOS=5; docker compose up -d odoo
```

## Bevor du etwas an der Kette änderst

`docs/KOMPROMISSE.md` lesen. Dort steht jede Entscheidung, die schon einmal Messzeit gekostet hat,
mit dem Messwert und mit dem, was beim Zurückdrehen passiert. Dort steht auch, welche Angaben in
den Codekommentaren inzwischen **überholt** sind — sechs Stück, Stand 15.09.2026.

Wer eine dieser Entscheidungen ändern will, misst vorher. Für die beiden häufigsten Fälle gibt es
Skripte, die ohne die ganze Kette auskommen:

| Frage | Skript |
|---|---|
| Wie lang sind die Schadensbefunde? | `scripts/bench_anomalien.py <foto> ...` |
| Wie schnell ist ein Bildmodell? | `scripts/bench_vision_models.py <foto> <modell> ...` |
| Wie schnell ist ein Textmodell? | `scripts/bench_text_models.py <modell> ...` |

Alle drei laufen im Backend-Container mit `PYTHONPATH=/app` und benutzen die Produktiv-Prompts.
**Immer mehrere Fotos messen**: Das Bildmodell ist nicht stabil — dasselbe Foto lieferte bei
`temperature: 0` einmal fünf ganze Sätze und einmal zwei Wörter.

## Vorbelastung, die nicht zum Testlauf gehört

Odoo protokolliert alle 13–15 Sekunden
`RuntimeError: Couldn't bind the websocket. Is the connection opened on the evented port (8072)?`
gefolgt von `"GET /websocket?version=19.0-2 HTTP/1.1" 500`. Das ist unabhängig von der Meldungskette,
sollte im Protokoll aber als bekannte Vorbelastung erwähnt werden, falls die PWA auf Bus-Updates wartet.
