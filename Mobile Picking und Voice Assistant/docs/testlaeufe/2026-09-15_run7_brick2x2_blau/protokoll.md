# Testlauf 7 — drei Fotos

**Datum:** 15.09.2026
**Auftrag:** L1/OUT/00243, Position 1 von 6
**Artikel:** Brick 2x2 blau, SKU 4166960, Produkt 73, Regal B-01, 1 Stück, Meyer Spielwaren KG
**Alert:** QA/0372 (Odoo-Datensatz-ID 373)
**Ergebnis:** `ai_evaluation_status = completed`, **4 min 17 s**

Zeitangaben aus den Container-Logs, UTC.

## 1. Was dieser Lauf prüft

Drei Fragen: Wie viel kostet ein drittes Foto? Reicht das Zeitbudget noch? Und liest sich die
Schadenszeile im Odoo-Formular jetzt sauber, nachdem `_schadensworte` Dopplungen entfernt und die
häufigen Begriffe übersetzt?

## 2. Eingangsdaten

Vorlage: Katalogbild aus Odoo (`default_code = 4166960`, `image_1920`, 2 100 Byte PNG). ChatGPT
erzeugte daraus drei Ansichten desselben beschädigten Steins, alle freigestellt auf weiß:
Schrägansicht, Draufsicht auf die Noppenseite, Nahaufnahme der beschädigten Seite. Schaden: eine
Noppe abgebrochen, Riss durch die Seitenwand, untere Ecke abgeplatzt.

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Artikel beschaedigt: Brick 2x2 blau (SKU 4166960), Regal B-01.
              Noppe abgebrochen, Riss durch die Seitenwand, untere Ecke abgeplatzt.
              Nicht versandfaehig. Drei Fotos angehaengt.
Fotos:        3  (fotos/qa_photo_01_v2.jpg bis _03_v2.jpg, je 1 024 px JPEG)
```

Die `_v2`-Dateien sind byteidentische Kopien von `qa_photo_01.jpg` bis `_03.jpg` (gleiche
MD5-Summen, siehe `pruefsummen.txt`). Nötig wegen des Idempotenzschlüssels, siehe Abschnitt 6.

## 3. Zeitlicher Ablauf

| Zeit (UTC) | Δ zum Start | Ereignis | Dauer |
|---|---|---|---|
| 08:12:39,9 | 0 s | Absenden in der PWA, `POST /api/quality-alerts` → 200 OK | — |
| ≈08:12:41 | 1,1 s | `POST http://n8n:5678/webhook/quality-assessment-v2` → 200 OK | — |
| ≈08:13:45 | 65 s | Textbewertung `qwen2.5:7b`, 938 Token | **59,41 s** |
| 08:13:46,1 | 66,2 s | `embed_abgleich`: Urteil **`match`**, Grund `treffer` | < 1 s |
| 08:14:32,6 | 112,7 s | `vision_probe` Foto 1 (Bilddekodierung 19,35 s), `ok: true` | **46,55 s** |
| 08:15:21,9 | 162,0 s | `vision_probe` Foto 2 (Bilddekodierung 16,87 s), `ok: true` | **49,28 s** |
| 08:16:10,3 | 210,4 s | `vision_probe` Foto 3 (Bilddekodierung 16,85 s), `ok: true` | **48,38 s** |
| 08:16:35,9 | 236,0 s | `vision_probe` Katalogbild (Bilddekodierung 3,56 s), `ok: true` | **25,65 s** |
| ≈08:16:56 | ≈256 s | Abschließender Textabgleich `qwen2.5:7b`, 445 Token | **20,43 s** |
| 08:16:57 | 257 s | `assessments/quality` → 200 OK, `callbacks/status` → 200 OK, Odoo geschrieben | — |

**Gesamtlaufzeit: 4 min 17 s.**

### 3.1 Inferenzzeiten

| Aufruf | Modell | Token | Bilddekodierung | Gesamt |
|---|---|---|---|---|
| Textbewertung | `qwen2.5:7b` | 938 | — | 59,41 s |
| Foto 1 | `gemma4:12b` | 492 | 19,35 s | 45,92 s |
| Foto 2 | `gemma4:12b` | 506 | 16,87 s | 47,99 s |
| Foto 3 | `gemma4:12b` | 498 | 16,85 s | 46,97 s |
| Katalogbild | `gemma4:12b` | 255 | 3,56 s | 24,11 s |
| Artikelvergleich (Text) | `qwen2.5:7b` | 445 | — | 20,43 s |

## 4. Ergebnis der Systembewertung

```
ai_evaluation_status:  completed
ai_disposition:        scrap
ai_confidence:         1.0
ai_summary:            Noppe abgebrochen und Riss - irreparabel.
ai_recommended_action: Ware sperren, aussondern und Schichtleitung informieren.
ai_photo_analysis:
  Schaden: SICHTBAR -- Riss, broken piece, aufgerissene Stelle.
  Zustand: Abgleich mit dem Katalogbild bestätigt den Befund
           (Ein großer Riss und ein abgebrochener Teil zeigen sich im IST-Bild,
            sind aber nicht im SOLL-Zustand enthalten.)
```

Der Einbettungsabgleich entschied mit `match`: 4166960 auf 0,8467, Zweiter 6346241 auf 0,8244,
Abstand 0,0223 — knapp über der Schwelle `EINBETT_KNAPP_SCHWELLE = 0.02`. Die 2x2-Formfamilie hat
im Katalog viele Nachbarn; beim Dachstein aus Lauf 6 lag der Abstand bei 0,2396.

## 5. Die aufgeräumte Schadenszeile

Vorher, QA/0370 mit zwei Fotos:

```
Schaden: SICHTBAR -- crack, broken edge, crack, split.
```

Jetzt, QA/0372 mit **drei** Fotos:

```
Schaden: SICHTBAR -- Riss, broken piece, aufgerissene Stelle.
```

Drei Fotos desselben Schadens liefern drei Begriffe statt neun. Die Dopplungen sind entfernt,
zwei Begriffe stehen auf Deutsch. `broken piece` steht nicht im Glossar von `_schadensworte` und
bleibt deshalb wörtlich stehen — ein falsch geratenes deutsches Wort wäre schlimmer als ein
englisches, das man nachschlagen kann.

## 6. Was das dritte Foto kostet

| | Lauf 5, **1** Foto | Lauf 6, **2** Fotos | **Lauf 7, 3 Fotos** |
|---|---|---|---|
| Bildaufrufe | 3 | 3 | **4** |
| Bildzeit gesamt | 121,6 s | 129,3 s | **169,9 s** |
| Gesamtlaufzeit | 3 min 15 s | 2 min 42 s | **4 min 17 s** |
| Auslastung Bildbudget (240 s) | 51 % | 54 % | **72 %** |
| Auslastung n8n-Knoten (270 s) | 71 % | 59 % | **94 %** |

Die Struktur ist in allen Läufen dieselbe: `_check_article` sieht nur das erste Foto,
`_check_damage` prüft jedes Foto einzeln, der Zustandsvergleich läuft einmal je Meldung. Drei
Fotos kosten also drei Schadensaufrufe plus einen Katalogbildaufruf.

**Die bindende Grenze ist nicht das Bildbudget, sondern das Knotenlimit.** Gemessen vom Webhook
(08:12:42,3) bis zur Antwort auf `/assessments/quality` (08:16:56,8): **254,5 s von 270 s, Reserve
15,5 s.** Das Bildbudget ist dagegen entspannter: von der Budget-Uhr ab 08:13:42,6 bis zum letzten
Bildaufruf 08:16:35,9 vergingen 173,3 s von 240 s, Reserve 66,7 s.

Der Grund für die Schieflage: Die beiden Textaufrufe kosten zusammen **79,9 s** (59,41 s + 20,43 s)
und zählen gegen das Knotenlimit, stecken aber in **keinem** Budget. Ein viertes Foto — rund 48 s —
würde das Bildbudget noch aushalten, das Knotenlimit aber um gut 30 s reißen. Die Hochrechnung aus Lauf 6 („bei vier Fotos noch 20–30 s Reserve") war
zu optimistisch: sie hatte den Zustandsvergleich mit 33 s angesetzt, er lief hier in 25,7 s,
dafür kostete jedes Foto rund 48 s statt der angenommenen 40 s.

**Damit ist die Obergrenze gemessen, nicht geschätzt: drei Fotos je Meldung sind das Maximum,
das die Kette in der jetzigen Konfiguration trägt.** Der Code zählt übersprungene Fotos bereits
(`n8n_v2.py:727-730`) — eine harte Grenze von drei geprüften Fotos macht das Verhalten
vorhersagbar, statt es vom Zeitbudget abhängen zu lassen.

## 7. Erster Versuch: abgebrochen durch Fremdlast

Ein erster Versuch desselben Laufs (Alert **QA/0371**, 08:04:26 UTC) endete nach exakt 270 s mit
`review_required` / `assessment unavailable`. Die Ursache lag nicht an den drei Fotos:

Eine abgebrochene Modellmessung lief in ollama weiter. Das Abbrechen des Clients beendet die
Generierung **nicht** — der Auftrag stand bei 1 718 erzeugten Token und belegte acht Kerne.
Folgen im Log:

| Zeit (UTC) | Ereignis |
|---|---|
| 08:06:00,3 | `llm_quality_disposition_failed`, `qwen2.5:7b` — Textbewertung reißt ihr 90-s-Limit |
| 08:06:27,4 | `embed_katalog`: 47 Artikel neu eingebettet, **25 859 ms** (Cache nach Backend-Neustart leer) |
| 08:06:28,1 | `embed_abgleich`: `match`, 4166960 auf 0,8467 |
| 08:09:00 | n8n-Knoten bricht nach 270 s ab, Odoo bekommt `assessment unavailable` |
| 08:09:40 | `vision_probe_failed` ×3, `RemoteProtocolError` und `ConnectError` — Folge des Ollama-Neustarts |

`qwen2.5:7b` war durch die Fremdlast aus dem Speicher verdrängt worden und musste neu laden,
während die 90 s bereits liefen.

**Lehre für den Skill:** Ein abgebrochener Client beendet keine laufende Generierung in ollama.
Vor jeder Messung `docker stats mobilepickingundvoiceassistant-ollama-1` prüfen — steht die CPU
über 100 %, läuft noch etwas. Aufräumen nur über `docker restart` des Containers.

## 8. Belege im Ordner

| Datei | Inhalt |
|---|---|
| `run7_brick2x2_blau.png` | Katalogbild aus Odoo, Vorlage |
| `fotos_original/run7_damage_01.png` bis `_03.png` | von ChatGPT erzeugte Schadensbilder |
| `fotos/qa_photo_01.jpg` bis `_03.jpg` | auf 1 024 px skaliert, Eingabe des ersten Versuchs |
| `fotos/qa_photo_01_v2.jpg` bis `_03_v2.jpg` | byteidentische Kopien, Eingabe des zweiten Versuchs |
| `kontaktabzug.jpg` | alle drei Ansichten nebeneinander |
| `pruefsummen.txt` | MD5-Summen |
| `logs/` | backend, ollama, n8n, odoo, Containerstände |
