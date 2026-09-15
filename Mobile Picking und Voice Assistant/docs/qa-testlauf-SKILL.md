---
name: qa-testlauf
description: Führt einen dokumentierten End-to-End-Testlauf der Qualitätsmeldung durch — Picking-PWA (Problem melden mit Fotos) → Backend → n8n "Quality Assessment v2" → lokale Bilderkennung (ollama) → Odoo Quality Alert. Erzeugt Schadensfotos über ChatGPT aus dem echten Katalogbild, misst die Laufzeiten pro Stufe und legt ein Protokoll unter docs/testlaeufe/ ab. Verwenden, wenn der Nutzer einen QA-Testlauf, Bilderkennungs-Test, Schadensmeldungs-Test, Quality-Alert-Test, eine Messung der Modelllaufzeiten oder einen Vergleich von Bild- oder Textmodellen verlangt.
---

# QA-Testlauf: Schadensmeldung mit Bilderkennung

Ziel: ein reproduzierbarer, für die Bachelorarbeit zitierfähiger Testlauf. Jeder Lauf hinterlässt
einen Ordner mit Bildern, Logs, Zeitmessungen und einem Protokoll.

**Vor jeder Änderung an der Kette `docs/KOMPROMISSE.md` lesen.** Dort steht jede Entscheidung, die
schon einmal Messzeit gekostet hat, mit ihrem Messwert — und welche Codekommentare überholt sind.

---

## 0. Was soll dieser Lauf messen?

Ein Lauf ohne Frage ist verschwendete Rechenzeit. Lege vorher fest, was **eine** Variable ist:

| Frage | Was variieren | Was konstant halten |
|---|---|---|
| Wirkt eine Codeänderung? | die Änderung | Auftrag, Artikel, Foto (gleiche MD5), Text |
| Was kostet ein weiteres Foto? | Fotoanzahl | Artikel, Bildwelt, Modelle warm |
| Trägt die Artikelachse? | Artikel bzw. Formfamilie | Bildwelt weiß, Fotoanzahl |
| Taugt ein anderes Modell? | Modell | **nicht die Kette fahren** — Skript nehmen, siehe Abschnitt 6 |

Stand 15.09.2026 bereits gemessen und **nicht zu wiederholen**: Threadzahl, Fotoanzahl 1 bis 5,
Textmodellvergleich, Hintergrund freigestellt gegen Lager, Länge der Schadensbefunde.

---

## 1. Voraussetzungen

```powershell
docker ps --format "{{.Names}} {{.Status}}"
```

Erwartet: `backend`, `pwa`, `n8n`, `odoo`, `odoo-lager-2`, `caddy`, `db`, `ollama`, `embed`
(Präfix `mobilepickingundvoiceassistant-`).

Browser-Tabs in derselben Claude-Tabgruppe:

| Zweck | URL |
|---|---|
| Picking Assistant | `https://localhost/` |
| ChatGPT | `https://chatgpt.com/` |
| Odoo Quality Alerts | `http://127.0.0.1:8069/odoo/action-307` |
| n8n Executions | `http://127.0.0.1:5678/home/executions` |

### Die vier Prüfungen vor dem Start

Alle vier, jedes Mal. Jede hat schon einmal einen Lauf unbrauchbar gemacht.

```powershell
# 1. Mountet der Container den Code, den du aenderst?
docker inspect mobilepickingundvoiceassistant-backend-1 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'

# 2. Liegt Fremdlast auf ollama? Ueber 100 % heisst: da laeuft noch etwas.
docker stats --no-stream mobilepickingundvoiceassistant-ollama-1

# 3. Sind beide Modelle geladen?
docker exec mobilepickingundvoiceassistant-ollama-1 ollama ps

# 4. Wieviele Fotos nimmt Odoo an?
docker exec mobilepickingundvoiceassistant-odoo-1 sh -c 'echo $QA_MAX_ASSESSMENT_PHOTOS'
```

Fehlt ein Modell oder stimmt die Kontextgröße nicht:

```powershell
docker cp .claude/skills/qa-testlauf/scripts/warmlaufen.py mobilepickingundvoiceassistant-backend-1:/tmp/
docker exec mobilepickingundvoiceassistant-backend-1 python /tmp/warmlaufen.py
```

---

## 2. Ablauf

### 2.1 Auftrag und Artikel wählen

Im Picking Assistant einen Auftrag öffnen. Für Varietät eine andere Position als Position 1
nehmen — die Positionsliste ist anklickbar:

```js
[...document.querySelectorAll('button')].find(x => x.innerText.includes('<SKU>')).click();
```

SKU, Produkt-ID, Regal und Auftragsnummer notieren.

### 2.2 Katalogbild holen

**Nicht** über den Browser-Download — der schlägt still fehl, wenn Chrome mehrere Downloads
hintereinander blockt. Direkt aus Odoo:

```powershell
docker cp .claude/skills/qa-testlauf/scripts/hol_katalogbild.py mobilepickingundvoiceassistant-backend-1:/tmp/
docker exec mobilepickingundvoiceassistant-backend-1 python /tmp/hol_katalogbild.py <SKU> /tmp/vorlage.png
docker cp mobilepickingundvoiceassistant-backend-1:/tmp/vorlage.png "<laufordner>/<name>.png"
```

### 2.3 Schadensfotos erzeugen

Vorlage an ChatGPT anhängen (`file_upload` auf das `input[type=file]` im `form`), dann **je
Ansicht einen Prompt**, nacheinander. Alle auf einmal anzufordern liefert nur ein Bild.

**Immer freigestellt auf weißem Hintergrund.** Gemessen: dasselbe Teil mit demselben Schaden
erreicht freigestellt 0,8723 auf Platz 1 des Artikelabgleichs, im Lagerfoto 0,393 auf Platz 5.
Lagerfotos sind nur sinnvoll, wenn der Domänensprung selbst die Frage ist.

Bewährte Ansichten:

1. schräg von oben wie die Vorlage
2. strenge Draufsicht auf die Noppen
3. Nahaufnahme der Bruchstelle von der Seite
4. Ansicht von hinten
5. Ansicht von unten

Jedes Bild direkt nach Fertigstellung herunterladen, `run<N>_damage_01.png` und so fort.

### 2.4 Bilder aufbereiten

```powershell
pwsh -File .claude/skills/qa-testlauf/scripts/prepare-photos.ps1 -Quelle "$HOME\Downloads" -Muster "run<N>_damage_*.png" -Ziel "docs\testlaeufe\<laufordner>"
```

Skaliert auf 1 024 px JPEG (entspricht `DAMAGE_MAX_EDGE`), baut einen Kontaktabzug, schreibt
MD5-Summen. Den Kontaktabzug ansehen, bevor der Lauf startet — ein Bild ohne sichtbaren Schaden
misst nichts.

### 2.5 Meldung absenden

Im Picking Assistant: „Problem" → „Artikel beschädigt" → Beschreibung → `file_upload` der JPEGs →
`button.qa-submit` per `.click()`.

Vorher prüfen:

```js
const fi = document.querySelector('input[type=file]');
({ files: [...fi.files].map(f => f.name),
   chip: [...document.querySelectorAll('button.qa-chip--active')].map(b => b.textContent.trim()),
   desc: document.querySelector('textarea').value });
```

Absendezeit notieren — sie ist der Nullpunkt aller Zeitmessungen.

### 2.6 Kette beobachten

Einen Subagenten mitlaufen lassen (Vorlage in Abschnitt 5). Selbst zusätzlich:

```powershell
docker logs --since 15m mobilepickingundvoiceassistant-backend-1 2>&1 |
  Select-String "embed_abgleich|vision_probe|assessments/quality|callbacks/status|Zeitbudget|llm_"
```

### 2.7 Ergebnis auslesen

Das Odoo-Formular rendert im versteckten Tab oft leer. Zuverlässig per RPC:

```powershell
docker cp .claude/skills/qa-testlauf/scripts/lies_alert.py mobilepickingundvoiceassistant-backend-1:/tmp/
docker exec mobilepickingundvoiceassistant-backend-1 python /tmp/lies_alert.py QA/0374
```

(Das Skript liest `quality.alert.custom` — **nicht** `quality.alert`, das Modell heißt anders.)

### 2.8 Belege einsammeln und Protokoll schreiben

```powershell
pwsh -File .claude/skills/qa-testlauf/scripts/collect-evidence.ps1 -Laufordner "docs\testlaeufe\<laufordner>"
```

Protokoll als `protokoll.md` im Laufordner. Abschnitte: Was der Lauf prüft, Eingangsdaten,
Zeitlicher Ablauf mit Quelle je Zeile, Inferenzzeiten, Ergebnis der Systembewertung, Vergleich mit
den Vorläufen, Abweichungen, Belege. **Immer absolute Uhrzeiten in UTC**, wie im Log.

Danach `docs/testlaeufe/GESAMTUEBERSICHT.md` nachziehen: Tabelle in Abschnitt 1, Artikelachse in
Abschnitt 3, offene Punkte.

---

## 3. Zeitschranken und was sie bedeuten

| Schranke | Wert | Quelle |
|---|---|---|
| Textbewertung je Aufruf | 90 s | `LLM_TIMEOUT_MS` |
| Bildaufruf einzeln | 200 s | `config.py:187` |
| Bildbudget für alle Bildaufrufe | 240 s | `config.py:192` |
| Warten auf die Bewertungssperre | 150 s | `config.py:235` |
| **n8n-Knoten** | **270 s** | `quality-assessment-v2.json` |
| Fotos je Meldung | 3 | `QA_MAX_ASSESSMENT_PHOTOS` (Odoo) |

**Die Summe der Backend-Budgets erreicht 510 s, der Knoten wartet 270 s.** Das Backend misst
gegen einen festen Wert, nicht gegen die Restzeit — in Lauf 9 lief es weiter, als n8n längst
aufgegeben hatte. Die Fotoobergrenze in Odoo ist derzeit das Einzige, was das verdeckt.

Gemessene Kosten je Stufe (warme Modelle, `num_thread: 8`):

| Stufe | Dauer |
|---|---|
| Textbewertung | 20–74 s |
| Einbettungsabgleich | unter 1 s |
| Schadensprüfung je Foto | 42–60 s |
| Katalogbildvergleich | 18–33 s |
| Artikelvergleich im Text | 5–22 s |

Nur **eine** Bewertung gleichzeitig (`_ASSESSMENT_GATE`). Nächste Meldung erst absetzen, wenn die
vorherige Execution abgeschlossen ist.

---

## 4. Stolperfallen — jede hat schon einen Lauf gekostet

**1. Falscher Codepfad gemountet.** Der Stack lief aus einem Worktree; Änderungen im
Projektverzeichnis erreichten den Container nie. Gegenprobe im Container, nicht auf der Platte:
`docker exec ... grep -c <neues_symbol> /app/app/services/<datei>.py`.

**2. Threadzahl.** Ohne `options.num_thread` startet llama.cpp mit 14 Threads. Der ollama-Log
sagt es je Ladevorgang: `n_threads = 8 (n_threads_batch = 8) / 14`. Die Umgebungsvariable
`OLLAMA_NUM_THREAD` am ollama-Dienst wirkt **nicht** — 1,21 tok/s gegen 7,40 tok/s.

**3. Modelle mit falscher Kontextgröße gewärmt.** `vision_client` ruft mit `num_ctx 8192`,
`llm_client` mit 4096. Wärmt man anders, lädt ollama beim ersten echten Aufruf neu.

**4. CSRF fehlt im neuen Tab.** Er liegt im `sessionStorage`. Ohne ihn kommt `claim` mit 403, und
die PWA meldet irreführend „Profil bitte neu wählen":

```js
const j = await fetch('/api/auth/csrf', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}).then(r=>r.json());
sessionStorage.setItem('picking-assistant-csrf', j.csrf_token);
```

**5. Ein abgebrochener Client beendet keine Generierung in ollama.** Eine per `TaskStop`
abgebrochene Messung lief weiter, erzeugte 1 718 Token, belegte acht Kerne und trieb den nächsten
Lauf in den Abbruch. Aufräumen nur über `docker restart` des ollama-Containers.

**6. Idempotenz.** Der Schlüssel besteht aus Auftrag, Position, Priorität, Beschreibung und
`Dateiname:Größe` (`pwa/js/app.js:3486`). Zweimal dieselbe Meldung liefert denselben Alert zurück,
ohne n8n anzustoßen — erkennbar am fehlenden `POST .../webhook/quality-assessment-v2` im Log. Für
eine Wiederholung mit identischem Bildinhalt: dieselbe Datei unter anderem Namen hochladen und die
MD5-Gleichheit protokollieren.

**7. `gemma4:12b` lädt nicht immer.** Am 15.09.2026 dreimal gescheitert, einmal mit
`llama-server process has terminated: signal: killed` und Nil-Pointer-Absturz im Scheduler.
`docker stats` zeigte dabei 25,3 GiB frei — Ursache ungeklärt. Neustart hilft.

**8. Die Fotoanzahl deckelt Odoo, nicht das Backend.** Ein Lauf mit vier Fotos prüft drei und
schreibt `Fotos: 1 weitere ungeprüft.` — kein Fehler. Für Messungen mit mehr Fotos:

```powershell
$env:QA_MAX_ASSESSMENT_PHOTOS=5; docker compose up -d odoo
```

Danach **zurücksetzen**: `docker compose up -d odoo` ohne die Variable.

**9. Das Bildmodell ist nicht stabil.** Dasselbe Foto, derselbe Prompt, `temperature: 0` lieferte
einmal fünf ganze Sätze als Befunde und einmal zwei Wörter. Einzelmessungen taugen nicht — immer
eine Serie.

**10. Nicht jede Ansicht taugt für die Artikelachse.** Die Unteransicht einer Platte ergab
freigestellt ein `mismatch` mit dem erwarteten Artikel auf Platz 5. `_check_article` sieht nur das
**erste** Foto (`n8n_v2.py:322`) — die Reihenfolge des Hochladens entscheidet mit.

---

## 5. Subagenten für die Beobachtung

Ein Subagent je Lauf reicht. **Wichtig im Prompt**, sonst wartet er auf eine Benachrichtigung, die
nie kommt:

> Beobachte in DEINER EIGENEN Schleife. Starte KEINEN separaten Hintergrund-Watcher, auf dessen
> Benachrichtigung du wartest — die bekommst du nicht. Setze wiederholt EIN Vordergrund-Kommando
> der Form `sleep 45; docker logs --since 20m <container> 2>&1 | grep ... | tail -20` ab. Liefere
> den Bericht erst, wenn du `callbacks/status` gesehen hast oder 14 Minuten vergangen sind.

Ihm mitgeben: Absendezeit, Auftrag, Artikel, Fotoanzahl, die Zeitschranken aus Abschnitt 3 und die
Vergleichswerte der Vorläufe. Verlangen: Tabelle Zeitstempel | Komponente | Ereignis | Dauer,
dazu Bildaufrufzahl, Budgetauslastung, Endzustand und Verbesserungsvorschläge **mit Zahl aus
diesem Lauf**.

Subagentenberichte gegenprüfen. Sie haben mehrfach Aufrufe falsch zugeordnet — etwa das
Katalogbild als „Foto 4" gezählt. Die Token-Zahlen im ollama-Log entscheiden: Meldefotos gehen mit
439 Prompt- und 256 Bild-Token hinein, das 192-px-Katalogbild mit 232 und 49.

---

## 6. Messen ohne die ganze Kette

Eine Modell- oder Promptfrage braucht keinen Testlauf. Alle Skripte laufen im Backend-Container
mit `PYTHONPATH=/app` und benutzen die Produktiv-Prompts.

| Frage | Skript |
|---|---|
| Wie lang sind die Schadensbefunde? | `bench_anomalien.py <foto> ...` |
| Wie schnell ist ein Bildmodell? | `bench_vision_models.py <foto> <modell> ...` |
| Wie schnell ist ein Textmodell? | `bench_text_models.py <modell> ...` |
| Welche Artikelwerte liefert die Einbettung? | `probe_schwellen.py <liste.txt>` |

`bench_vision_models.py` führt eine **eigene Kopie** der Prompts. Wer `vision_client.py` ändert,
muss sie dort nachziehen, sonst misst er den alten Wortlaut.

Beispiel für die Liste von `probe_schwellen.py`, eine Zeile je Foto:

```
/tmp/foto1.jpg;6138111;frei
/tmp/foto2.jpg;6138111;lager
```

---

## 7. Vorbelastung, die nicht zum Testlauf gehört

Odoo protokolliert alle 13–15 Sekunden
`RuntimeError: Couldn't bind the websocket. Is the connection opened on the evented port (8072)?`
mit `"GET /websocket" 500`. Unabhängig von der Meldungskette, gehört aber als bekannte
Vorbelastung ins Protokoll.

---

## 8. Was bereits gemessen ist

`docs/testlaeufe/GESAMTUEBERSICHT.md` — alle Läufe, Befunde, offene Punkte auf einer Seite.
`docs/KOMPROMISSE.md` — jede bezahlte Entscheidung mit Messwert, und welche Codekommentare
überholt sind.
