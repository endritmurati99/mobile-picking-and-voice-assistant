# Bildgestützte Qualitätsbewertung — Entwurf

**Datum:** 2026-08-06
**Branch:** `integration/foundation-remediation`
**Status:** Entwurf, vom Auftraggeber abgenommen; Umsetzungsplan folgt separat

## 1. Ausgangslage

Die v2-Qualitätskette bewertet Meldungen ausschließlich nach dem Text des
Kommissionierers. Fotos werden gespeichert und nie angesehen. Das ist kein
Fehler in der Umsetzung, sondern so gebaut — der Prompt sagt es dem Modell
wörtlich:

```python
# backend/app/services/llm_client.py:85
lines.append("Wichtig: Es stehen keine Bildinhalte zur Verfuegung, nur der Text.")
```

Der Envelope, den Odoo signiert und über die Outbox an n8n stellt, trägt vom
Foto nur die Anzahl (`quality_event.py:44-46`, Feld `photo_count`). Live
gemessen an QA/0014: 967 Bytes — darin kann kein Bild stecken.

### Belegte Wirkung

Fünf Meldungen vom 2026-08-06, alle mit Foto, alle in der Datenbank
nachlesbar:

| Alert | Text | Foto | Urteil |
|---|---|---|---|
| QA/0010 | Artikel beschädigt | gerissener Stein | `scrap` 0.95 |
| QA/0011 | Artikel beschädigt | gerissener Stein | `scrap` 0.95 |
| QA/0012 | Artikel beschädigt | anderes Foto | `scrap` 0.85 |
| QA/0013 | Verpackung defekt, **Artikel beschädigt**, Menge falsch | makelloses LEGO | `scrap` 0.90 |
| QA/0014 | Verpackung defekt | **Hund am Strand** | `sellable` 0.90 |

QA/0014 ist der Beleg, der die Aufgabe ausgelöst hat: ein Hundefoto wurde
„verkaufbar". Nicht trotz, sondern wegen des Textes — „Verpackung defekt"
bedeutet in der Taxonomie „Produkt selbst in Ordnung". Das Modell hat sauber
gearbeitet; es hatte kein Bild.

Der Prompt wurde 1:1 nachgespielt und liefert byteidentische Antworten. Das
Verhalten ist deterministisch, nicht zufällig.

## 2. Entschiedene Fragen

| Frage | Entscheidung |
|---|---|
| Rolle des Bildes | Das Bild **prüft** das Texturteil. Der Text liefert weiterhin die Einstufung. |
| Zeitbudget | Bis rund zwei Minuten je Meldung. Die Kette ist asynchron, der Kommissionierer wartet nicht. |
| Wer holt die Bilder | Das **Backend**, im Bewertungsschritt. Nicht n8n. |
| Melder sagt beschädigt, Foto zeigt nichts | Texturteil bleibt stehen, der Widerspruch wird **vermerkt**, nicht blockiert. |
| WSL-Speicher | Entwurf setzt `memory=20GB`, `processors=12` voraus. |

## 3. Hardware-Voraussetzung

Der Rechner hat 33 GB RAM und 16 Kerne (Intel Core Ultra 7 255H). WSL ist auf
`memory=12GB`, `processors=4` begrenzt. Daraus folgt der heutige Zustand:
Swap zu 92 % belegt, derselbe Modellaufruf einmal 21 s und einmal 135 s, und
Text- und Bildmodell passen nicht gleichzeitig in den Speicher (5,1 GB +
5,8 GB bei 12 GB Gesamtbudget, in dem außerdem zwei Odoo-Instanzen, Postgres,
n8n, Whisper und Piper liegen — zusammen allerdings nur 0,93 GB).

```ini
[wsl2]
memory=20GB      # war 12GB
processors=12    # war 4
swap=4GB
pageReporting=true
```

Ohne diese Änderung müsste der Entwurf um Modellwechsel herumgebaut werden:
30–60 s Ladezeit, zweimal je Meldung. Mit ihr bleiben beide Modelle resident
und der Entwurf einfach. Die Änderung ist Voraussetzung, nicht Beiwerk.

Eine GPU steht nicht zur Verfügung; die Arc-iGPU ist für Ollama nicht
nutzbar. Alle Zahlen sind CPU-Zahlen.

## 4. Modellwahl

Zwei Modelle, jedes bei dem, was es nachweislich kann:

| Aufgabe | Modell | Beleg |
|---|---|---|
| Urteil aus dem Text | `qwen2.5:7b` | heute im Einsatz, trifft die Taxonomie sauber |
| Artikelabgleich und Schadensprüfung | `qwen2.5vl:7b` | Messungen in Abschnitt 10 |

**Ein Modell für beides scheidet aus.** `qwen2.5vl:7b` wurde auf denselben
Textprompt losgelassen: „Verpackung defekt" ergab `scrap` mit der Begründung
„Verpackungsdefekt deutet auf Totalschaden hin" — `qwen2.5:7b` sagt hier
korrekt `sellable`. Bei QA/0011 begründete es das Urteil mit „keine Bilder
verfügbar, daher als Totalschaden eingestuft".

**`qwen2.5vl:3b` scheidet aus.** Es antwortete auf alle vier Prüfbilder
identisch „smooth and continuous everywhere", auch auf den offensichtlichen
Bruch. Kleiner ist hier weder schneller noch brauchbar.

## 5. Architektur

n8n ruft weiterhin **genau einen** Endpunkt auf:
`POST /api/internal/n8n/v2/assessments/quality`. Der Envelope bleibt
unverändert, die Signatur bleibt unberührt, es entsteht keine zusätzliche
Nonce, und die Lease-Regeln werden nicht angefasst.

```
Odoo  api_create_alert
        │  Job + Outbox in einer Transaktion, Envelope 967 Bytes
        ▼
Backend Outbox-Dispatcher (Takt 2 s)
        │  signiert
        ▼
n8n     Webhook → Signature Gate → Acceptance → 202 → If Process
        │
        ▼
Backend POST /v2/assessments/quality          ← hier liegt das Neue
        │
        ├─ 1. Bilder besorgen (Odoo)
        ├─ 2. Artikelabgleich   qwen2.5vl:7b   (Katalogbild + Meldefoto)
        ├─ 3. Schadensprüfung   qwen2.5vl:7b   (nur Meldefoto)
        ├─ 4. Texturteil        qwen2.5:7b     (nur Text)
        └─ 5. Abgleich          reines Python, kein Modell
        │
        ▼
n8n     If Assessment OK → If Contradiction → Success- oder Review-Callback
        │
        ▼
Backend POST /v2/callbacks/status → Odoo api_apply_callback → ai_*-Felder
```

Der Bildbefund steht im Ergebnis des Bewertungsknotens und ist damit in der
n8n-Execution sichtbar. Nur die Bilddaten selbst wandern nicht durch n8n.

## 6. Datenfluss im Bewertungsschritt

### 6.1 Bilder besorgen

Der Rumpf der Bewertungsanfrage trägt bereits `job_id`, `odoo_instance`,
`delivery_generation` und `processing_lease_token` (`backend/app/models/events.py:116-126`).
Das Backend braucht nichts Zusätzliches, um zwei Bilder zu lesen:

**Meldefoto** — der Anhang des Alerts mit `res_field IS NULL`, in
Anlagereihenfolge. Das ist die Unterscheidung, die zählt: Odoo legt je Foto
**zwei** `ir.attachment`-Zeilen an. Die eine trägt `res_field = 'photo'` und
ist die Ablage des Binärfeldes — Odoo hat sie neu kodiert (bei QA/0011:
3,5 MB statt 377 KB), und es gibt sie nur einmal, auch wenn mehrere Fotos
gemeldet wurden. Die andere trägt `res_field IS NULL`, den ursprünglichen
Dateinamen und die ursprünglichen Bytes. Nur diese wird gelesen.

**Katalogbild** — `product.template.image_1920` des gemeldeten Produkts.

**Bei mehreren Fotos:** der Artikelabgleich läuft nur auf dem ersten. Die
Schadensprüfung läuft auf jedem, höchstens auf dreien; sobald eines Schaden
zeigt, gilt `damaged`. Sind es mehr als drei, nennt `ai_photo_analysis` die
Zahl der ungeprüften. Stillschweigend Beweismaterial zu übergehen wäre die
schlechtere Wahl.

Beide laufen durch das vorhandene `validate_image`
(`backend/app/services/binary_validation.py`): nur JPEG, PNG oder WebP, nur
Einzelbilder, MIME gegen die tatsächlichen Bytes.

**Der MIME wird aus den Bytes bestimmt, nicht aus dem gespeicherten Wert.**
`api_create_alert` schreibt jedem Anhang, den es selbst anlegt, hart
`"mimetype": "image/jpeg"` (`quality_alert.py:248-256`) — also genau denen,
die hier gelesen werden. Das Hundefoto steht so als `image/jpeg` in der
Datenbank und ist in Wahrheit WebP. Würde der gespeicherte Wert geglaubt,
liefe jeder Bestandsanhang in 422. Auf der Leseseite zu entscheiden
folgt demselben Grundsatz, nach dem auf den signierten Routen ein
deklarierter Content-Type nie als Beweis gilt: er ist nicht signiert
(`n8n/nodes/.../signedRequest.ts` gegen `pwrSignature.ts`). Das Hartkodieren
in Odoo wird zusätzlich korrigiert, aber nichts hängt davon ab, und eine
Datenmigration entfällt.

**Verkleinern auf 512 px lange Kante.** Keine Sparmaßnahme: das
1920-px-Original lief gegen Ollama in `HTTP 400`, weil die Bildtoken das
Kontextfenster sprengen.

### 6.2 Artikelabgleich

Beide Bilder in einem Aufruf an `qwen2.5vl:7b`. Der Prompt benennt
ausdrücklich, welches Bild welches ist, und verlangt die Beschreibung **vor**
dem Urteil:

```
IMAGE 1 is the official catalogue photo of the article that SHOULD be in the box.
IMAGE 2 is the photo a warehouse worker just took.

JSON keys, in this order:
  image1_shows, image2_shows, same_article, same_article_reason
```

Die Reihenfolge ist Absicht. Wird zuerst nach dem Urteil gefragt, antwortet
das Modell aus dem Schema statt aus dem Bild — am 2026-08-05 gemessen.

Ergebnis: `match` | `mismatch` | `unavailable` (kein Katalogbild hinterlegt).

### 6.3 Schadensprüfung

Nur das Meldefoto, getrennter Aufruf. **Zwei Aufrufe statt einem, weil einer
messbar schlechter ist:** im Zwei-Bild-Aufruf stufte das Modell den Bruch als
„decorative element" ein und setzte `damaged: false`; im Einzelbild-Aufruf
mit geschärftem Prompt erkannte es ihn als „torn" und setzte `damaged: true`.

Der geschärfte Prompt trägt den entscheidenden Satz:

```
Decisive rule: a ragged, torn or gouged area on an otherwise smooth moulded
surface is DAMAGE, never decoration or a design feature. Printed logos,
smooth colour changes and reflections are NOT damage.
```

Ohne diesen Satz: null von vier Prüfbildern richtig. Mit ihm: drei von vier,
ohne Fehlalarm. Der Prompt gehört damit zur Spezifikation, nicht zur
Umsetzungsfreiheit.

Ergebnis: `damaged` | `intact` | `unavailable` (Prüfung gescheitert), dazu
die Liste der benannten Auffälligkeiten.

### 6.4 Texturteil

Unverändert `qwen2.5:7b`, mit einer Streichung: `llm_client.py:85` fällt weg.
Das Textmodell bekommt **keinen** Bildbefund. Es bleibt eine reine
Textbewertung — genau deshalb lässt sie sich im nächsten Schritt prüfen.

### 6.5 Abgleich

Reines Python, kein Modell. Ein Modell, das sich aus einem Widerspruch
herausreden kann, wäre keine Prüfung. Die Logik ist deterministisch und ohne
Modellaufruf testbar.

## 7. Widerspruchstabelle

Zuerst die Übersetzung der Dispositionen in eine Aussage — nur eine Aussage
kann einem Bild widersprechen:

| Disposition | Aussage über den Artikel |
|---|---|
| `scrap` | beschädigt, unbrauchbar |
| `rework` | mangelhaft, reparabel |
| `quarantine` | **keine Aussage** — verlangt ohnehin einen Menschen |
| `sellable` | kein relevanter Mangel |

| Artikelabgleich | Schaden | Text | Ergebnis |
|---|---|---|---|
| `mismatch` | — | beliebig | `review_required`, Grund: Foto zeigt nicht den gemeldeten Artikel |
| `match` | `damaged` | `scrap` / `rework` | Texturteil bestätigt |
| `match` | `damaged` | `sellable` | `review_required`, Grund: Foto zeigt Schaden, Meldung stuft als verkaufsfähig |
| `match` | `intact` | `sellable` | Texturteil bestätigt |
| `match` | `intact` | `scrap` / `rework` | **Texturteil bestätigt, Widerspruch vermerkt** |
| `match` | beliebig | `quarantine` | Texturteil bleibt, Bildbefund angehängt |
| `unavailable` | wie oben | wie oben | wie oben, Artikelzeile entfällt, Vermerk „kein Katalogbild hinterlegt" |

Das Ergebnis trägt ein Feld `contradiction`. Es steht **nur** in den beiden
Zeilen auf `true`, die `review_required` ergeben — `mismatch` und
„Schaden sichtbar bei `sellable`". Der vermerkte Widerspruch der vorletzten
Zeile setzt es ausdrücklich **nicht**, sonst liefe er über denselben Zweig
und würde doch blockieren. n8n verzweigt allein auf dieses Feld.

### Begründung der vorletzten Zeile

Der Kommissionierer hatte den Artikel in der Hand. Ein 7B-Modell auf einem
512-px-Foto ist der schwächere Zeuge — es hat einen sichtbaren Riss
übersehen. Das Texturteil wird deshalb nicht gekippt. Es wird auch nicht
blind übernommen: die Abweichung steht im Klartext in `ai_photo_analysis`
und ist für das Qualitätsteam in der Liste sichtbar.

Eine Konfidenzschwelle wäre hier Scheinsicherheit: das Modell war sich beim
übersehenen Riss zu 95 % sicher. Modellkonfidenz wird deshalb weder als
Schwelle noch als Gewicht verwendet.

### Randfälle

**Kein Katalogbild** — 23 von 70 Produkten haben keines. Der Artikelabgleich
entfällt ersatzlos, die Schadensprüfung läuft. Kein Fehler, keine Blockade.

**Kein Foto** — Texturteil wie heute, Vermerk „ohne Bildprüfung".

**Zeitgrenze.** Der Knoten `PWR Signed Assessment` steht heute auf
`timeoutMs: 120000`. Bei drei Fotos sind es vier Bildaufrufe — rund 84 s
resident, plus Texturteil. Das ist zu knapp; die Grenze wird auf 180 000
angehoben. Der Kommissionierer wartet nicht darauf, n8n hat nach 202 längst
geantwortet.

**Bildprüfung gescheitert** (Ollama nicht erreichbar, Zeitüberschreitung,
unlesbare Datei) — das Texturteil bleibt stehen, `ai_photo_analysis` nennt
den Grund wörtlich. **Nie** ein erfundener Bildbefund. Ein Ausfall der
Zweitmeinung darf die Erstmeinung nicht löschen; das ist die Entsprechung
zur bestehenden Regel, dass ein LLM-Ausfall `review_required` erzeugt statt
eines Ersatzurteils.

## 8. Was in Odoo landet

`ai_photo_analysis` (Text, „Fotoanalyse", `quality_alert.py:79`) existiert
bereits, wird von niemandem beschrieben und steht in einer Gruppe mit
`invisible="True"` (`quality_alert_views.xml:98-101`).

Es bekommt deutschen Klartext, keinen JSON-Abzug:

```
Artikelabgleich: stimmt mit Katalogbild überein.
Schadensprüfung: aufgerissene Zone an der Seitenfläche.
Modell qwen2.5vl:7b.
```

```
Foto zeigt nicht den gemeldeten Artikel: ein Hund am Strand
statt [6023350] Brick 2x2x2 R=15 gelb.
```

```
Foto zeigt keinen sichtbaren Schaden, die Meldung nennt einen.
Bitte stichprobenartig prüfen.
```

Drei Eingriffe:

**Schreibpfad.** `api_apply_assessment` (`quality_alert.py:169`) baut seine
`values` aus benannten Schlüsseln; unbekannte verschwinden lautlos.
`photo_analysis` muss ausdrücklich aufgenommen werden.

**Die `succeeded`-Regel öffnet sich für die Beobachtung.** Heute werden
Ergebnisfelder nur bei `mapped == "completed"` geschrieben
(`quality_alert.py:181`); bei `review_required` bleibt alles leer. Beim
Hundefoto **ist** `review_required` das Ergebnis, und der Grund dafür ist der
wertvollste Teil des Vorgangs. `ai_photo_analysis` wird deshalb auch bei
`review_required` geschrieben.

Die gelockerte Regel schützt davor, dass ein **Urteil** ohne Modell entsteht.
Eine Fotoanalyse ist kein Urteil, sondern eine Beobachtung. `ai_disposition`
bleibt bei `review_required` weiterhin leer.

**Ansicht.** `ai_photo_analysis` verlässt die unsichtbare Gruppe und steht
unter „Empfohlene Aktion" mit `invisible="not ai_photo_analysis"`.

Der Callback-Transport bleibt unverändert: `result` ist bereits
`dict[str, Any]` (`backend/app/models/events.py:85-87`), und
`api_apply_callback` liest per `.get()`. Das Antwortmodell der
Bewertungsroute braucht neue Felder — es ist ein `StrictModel` mit
`extra="forbid"` (`events.py:19-21`), also muss jedes Feld ausdrücklich
zugelassen werden. Das ist gewollt.

## 9. Berührte Sicherheitszusagen

**Signatur:** unberührt. Der Envelope bekommt kein neues Feld, der
Fingerabdruck wird über genau die gesendeten Bytes gebildet
(`quality_event.py:87-95`).

**Lease und Nonce:** unberührt. Es entsteht kein zusätzlicher signierter
Aufruf, also auch keine zusätzliche Nonce. Die Reihenfolge billig → Nonce →
teuer auf den Binärrouten (`backend/app/routers/n8n_v2.py:290-296`) wird
nicht angefasst.

**16-MB-Trias** (Caddy, n8n, Backend): unberührt. Bilder wandern nicht durch
den Envelope. Das wäre der Bruch gewesen — `api_lease_due` liefert bis zu 200
Envelopes je Antwort (`outbox.py:55,96`).

**fail-closed:** bleibt. Neue Felder müssen einzeln zugelassen werden
(`extra="forbid"`), und ein Bildausfall erzeugt nie einen Ersatzbefund.

**Neu und zu benennen:** die Bewertungsroute liest jetzt aus Odoo. Bisher
galt für sie ausdrücklich „Kein Odoo-Aufruf, keine Lease-Prüfung: diese Route
entscheidet nichts und ändert nichts" (`n8n_v2.py`, Docstring von
`assess_quality`). Sie ändert weiterhin nichts, aber sie liest. Der Zugriff
ist an `job_id` gebunden — der Alert wird über den Job aufgelöst, nie über
eine mitgeschickte Alert-Kennung. Der Docstring ist entsprechend zu
korrigieren; eine stillschweigende Änderung dieser Zusage wäre die
gefährlichste Stelle des ganzen Umbaus.

## 10. Messungen

Alle Zahlen vom 2026-08-06 auf der beschriebenen Maschine, CPU, unter den
heutigen 12 GB WSL-Speicher (also mit Auslagerung).

### Zwei-Bild-Aufruf, Katalogbild + Meldefoto

| Meldefoto | `same_article` | `damaged` | Zeit |
|---|---|---|---|
| makelloses LEGO | `true` ✓ | `false` ✓ | 144 s |
| gerissener Stein | `true` ✓ | `false` ✗ | 306 s |
| Hund | **`false` ✓** | `false` ✓ | 141 s |

Wörtlich zum Hund: „Image 2 shows an animal, not a product like image 1
does." Zum Riss: „differing only by an additional decorative element in
image 2" — das Modell **sieht** die Stelle und benennt sie falsch.

### Einzelbild, unscharfer Prompt

Alle drei Bilder `damaged: false`, `visible_defects: []`. Der Riss wurde als
„feather-like design on its surface" beschrieben.

### Einzelbild, geschärfter Prompt

| Bild | erwartet | Urteil | Zeit |
|---|---|---|---|
| Gemini-Riss | beschädigt | **heil** ✗ | 21,6 s |
| synthetischer Bruch | beschädigt | beschädigt ✓ | 111,6 s |
| derselbe Stein, unbeschädigt | heil | heil ✓ | 135,6 s |
| makelloses LEGO | heil | heil ✓ | 21,1 s |

Drei von vier, keine Fehlalarme. Die Spannweite 21 s ↔ 136 s bei identischem
Modell und identischer Bildgröße ist Auslagerung, nicht Rechenzeit —
resident kostet ein Bildaufruf rund 21 s.

### `qwen2.5vl:3b`

Vier von vier Bildern „smooth and continuous everywhere", `damaged: false` —
auch beim offensichtlichen Bruch. Nicht verwendbar.

### Referenzbilder im Bestand

47 von 70 Produktvorlagen haben ein `image_1920`, Median 2146 Bytes,
192 × 192 Pixel, WebP. Alle Größenvarianten sind byteidentisch. Für Produkt
85 ist es ein sauberer Katalogrender genau dieses Bausteins.

## 11. Verworfene Alternativen

**n8n holt die Bilder über `get_job_media`.** Die Route existiert und ist
sauber gebaut, aber `pwr_media_ref` wird von niemandem gesetzt: einziger
Schreiber ist `_bind_job_media` (`resources.py:429`), dessen eigener
Docstring festhält „Diese Methode hat heute keinen produktiven Aufrufer --
nur Tests rufen sie" (`resources.py:463-464`). Das Binden verlangt eine
aktive Lease (`resources.py:481`), die es beim Anlegen des Alerts noch nicht
gibt — der Job entsteht erst danach, das Token erst bei der Annahme. Live
sind null Anhänge gebunden. Dazu auf der n8n-Seite: eine Binärantwort leert
`item.json` und reißt die Signaturkette ab, Base64 im Item-JSON verbietet der
Workflow-Prüfer, und zwei Bilder passen nicht in einen `bodyMode: binary`-
Rumpf. Der Weg kostet das Aufweichen genau der Lease-Bindung, die einen im
Code benannten Angriff schließt (`resources.py:446-452`).

**Bilder in den Envelope.** `api_lease_due` liefert bis zu 200 Envelopes je
Antwort; jeder Zustellversuch überträgt den Envelope erneut. Sprengt die
16-MB-Grenze und die Outbox.

**Ein Modell für Text und Bild.** Siehe Abschnitt 4.

**Bildbefund in den Textprompt geben, das Modell entscheiden lassen.** Wäre
Verschmelzung statt Prüfung. Ein Modell, das beide Quellen sieht, kann einen
Widerspruch wegerklären; die Tabelle in Abschnitt 7 kann es nicht.

## 12. Tests

Die Widerspruchstabelle ist reines Python und wird mit erfundenen
Bildbefunden geprüft, ohne einen einzigen Modellaufruf:

- ein Test je Zeile der Tabelle, beide Randfälle eingeschlossen
- Bildmodell fällt aus → Texturteil überlebt, Grund steht in `ai_photo_analysis`
- `ai_photo_analysis` wird auch bei `review_required` geschrieben, `ai_disposition` bleibt dabei leer
- ein PNG, das als `image/jpeg` deklariert ist, kommt durch die Bildprüfung
- der bestehende Fingerabdruck-Paritätstest bleibt unverändert grün

**Abnahme von Hand**, nicht in der Testsuite, mit den vier Bildern vom
2026-08-06:

| Eingabe | Erwartung |
|---|---|
| Hund + „Verpackung defekt" | `review_required`, Grund im Klartext |
| makelloses LEGO + „Artikel beschädigt" | `scrap`, Vermerk „Foto zeigt keinen sichtbaren Schaden" |
| synthetischer Bruch + „Artikel beschädigt" | `scrap`, Bildbefund bestätigt |
| heiler Stein + „Verpackung defekt" | `sellable`, Bildbefund bestätigt |

## 13. Bewusst nicht Gegenstand

- Eigene Odoo-Felder für `same_article` und `damaged`. Auswertbar wäre
  schöner, gebraucht wird es nicht.
- Bessere Referenzbilder. 192 × 192 reicht für den Artikelabgleich; mehrere
  Ansichten je Produkt sind eine eigene Aufgabe.
- Die 23 Produkte ohne Katalogbild. Sie laufen ohne Artikelabgleich.
- Ein Bindeweg für `pwr_media_ref`. Bleibt ungenutzt und unangetastet.
- Der Kaltstart-Wettlauf zwischen Backend und Odoo (`main.py:66`,
  `docker-compose.yml:102`, `depends_on` ohne Bedingung, Odoo ohne
  Healthcheck). Eigener, unabhängiger Fehler; am 2026-08-06 hat er den
  Stack lahmgelegt. Gehört gefixt, aber nicht hier.
