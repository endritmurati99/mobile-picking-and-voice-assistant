# Testlauf 10 — dieselben fünf Fotos, diesmal mit Budgetbremse

**Datum:** 15.09.2026
**Auftrag:** L1/OUT/00303, Position 5 von 6
**Artikel:** Brick Bow 2x3x1 hellblau, SKU 6138111, Produkt 96, Regal C-01, 1 Stück,
Meyer Spielwaren KG
**Alert:** QA/0375 (Odoo-Datensatz-ID 376)
**Ergebnis:** `completed` / `scrap`, Konfidenz 0,95 — **Antwort nach 210,9 s, kein Abbruch**

Zeitangaben aus den Container-Logs, UTC.

## 1. Was dieser Lauf prüft

Lauf 9 brach am n8n-Knotenlimit ab: fünf Fotos, drei geprüft, das vierte startete mit 30,6 s
Restzeit für einen Aufruf, der 42–60 s braucht, und wurde 24,2 s nach dem Abbruch serverseitig
beendet. In Odoo stand `assessment unavailable` — der fertige Artikel- und Schadensbefund ging
mit unter.

Dieser Lauf ist die **Gegenprobe zu genau derselben Eingabe**. Einzige Änderung ist der Code:

| | Lauf 9 | Lauf 10 |
|---|---|---|
| Frist der Bildstufe | fest `vision_budget_ms` (240 s), kennt das Knotenlimit nicht | frühere aus Bildbudget und **Anruferfrist** `caller_budget_ms` (255 s ab Eintreffen der Anfrage) |
| Prüfung vor einem Aufruf | „ist das Budget erschöpft" (`time.monotonic() >= deadline`) | „passt der nächste Aufruf noch" (`_reicht_die_zeit`, `vision_call_estimate_ms` = 60 s) |
| Garantierter erster Aufruf | ohne Fessel | startet weiterhin, wird aber gekappt statt den Anrufer zu überleben |

Alles andere ist konstant gehalten: Auftrag, Position, Artikel, Fotoanzahl, `gemma4:12b` und
`qwen2.5:7b` vorgewärmt mit den Produktiv-Kontextgrößen, `QA_MAX_ASSESSMENT_PHOTOS = 5`.

## 2. Eingangsdaten

**Dieselben fünf Bilddateien wie in Lauf 9**, nur unter neuem Namen hochgeladen (der
Idempotenzschlüssel enthält `Dateiname:Größe`). Die MD5-Summen sind identisch:

| Lauf 10 | MD5 | Lauf 9 |
|---|---|---|
| run10_photo_01.jpg | A0CCB89DE2794554906530F7C4CEBE8B | qa_photo_01.jpg |
| run10_photo_02.jpg | 510431A66534BAC3589D6D9392481550 | qa_photo_02.jpg |
| run10_photo_03.jpg | 4F079E1B7B2BF04E4C48210C7A05C9EA | qa_photo_03.jpg |
| run10_photo_04.jpg | 0E52A3896373DAC9EE4806BAA38D9BB9 | qa_photo_04.jpg |
| run10_photo_05.jpg | 5DB05D5A45916C4D6C346EABDC677936 | qa_photo_05.jpg |

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Testlauf 10 Gegenprobe Budgetbremse: Artikel beschaedigt: Brick Bow 2x3x1
              hellblau (SKU 6138111), Regal C-01. Noppe abgebrochen, Riss ueber die
              Woelbung, Ecke abgeplatzt. Nicht versandfaehig. Fuenf Fotos angehaengt.
Fotos:        5  (370 KB gesamt)
```

## 3. Zeitlicher Ablauf

| Zeit (UTC) | Δ zum Start | Ereignis | Dauer |
|---|---|---|---|
| 12:29:08,7 | 0 s | Absenden in der PWA, `POST /api/quality-alerts` → 200 OK | — |
| 12:29:10,5 | 1,8 s | `POST http://n8n:5678/webhook/quality-assessment-v2` → 200 OK | — |
| ≈12:29:14 | ≈5 s | Anfrage `assessments/quality` im Backend, Anruferfrist läuft (Ende ≈12:33:29) | — |
| 12:30:08,2 | 59,5 s | Textbewertung `qwen2.5:7b` fertig (958 Token) | **54,16 s** |
| 12:30:19,7 | 71,0 s | `embed_katalog`: 47 Artikel neu eingebettet — Cache nach dem Backend-Neustart leer | **10,90 s** |
| 12:30:19,9 | 71,2 s | `embed_abgleich`: **`match`**, 6138111 auf **0,9176**, Abstand 0,0886 | 210 ms |
| 12:31:10,2 | 121,5 s | `vision_probe` Foto 1, `ok: true` | **47,07 s** |
| 12:31:54,2 | 165,5 s | `vision_probe` Foto 2, `ok: true` | **42,49 s** |
| 12:32:39,6 | 210,9 s | `vision_probe` Foto 3, `ok: true` | **42,22 s** |
| **12:32:39,6** | **210,9 s** | **Antwort an n8n → 200 OK**, `callbacks/status` → 200 OK, Odoo geschrieben | — |

**Foto 4 wurde nicht gestartet.** Bei 210,9 s blieben rund 48 s bis zur Anruferfrist — weniger als
die veranschlagten 60 s je Aufruf. Dieselbe Prüfung hielt den Katalogbildvergleich zurück. Beides
steht im Klartext im Alert, nichts davon ist stillschweigend entfallen.

Im ollama-Log endet die letzte Generierung (`task 136`) sauber mit `stop processing`; **kein
`cancel task`** im Laufzeitfenster. Zum Vergleich Lauf 9: dort stand dort `srv stop: cancel task,
id_task=198` und 65,6 s Rechenzeit ohne Ergebnis.

## 4. Inferenzzeiten (ollama, `num_thread: 8`)

| Aufruf | Modell | Gesamtzeit | Token |
|---|---|---|---|
| Textbewertung (`task 4`) | qwen2.5:7b | 54,16 s | 958 |
| Foto 1 (`task 6`) | gemma4:12b | 46,21 s | 519 |
| Foto 2 (`task 69`) | gemma4:12b | 40,31 s | 523 |
| Foto 3 (`task 136`) | gemma4:12b | 40,19 s | 518 |

Die Bildaufrufe liegen mit 40,2–46,2 s am unteren Rand des gemessenen Bandes (42–60 s). Der
Schätzwert von 60 s ist damit bewusst konservativ: er lässt eher ein Foto liegen, als eine Antwort
zu verlieren.

## 5. Ergebnis der Systembewertung

```
ai_evaluation_status:  completed
ai_disposition:        scrap
ai_confidence:         0.95
ai_summary:            Noppe abgebrochen und nicht versandfähig, irreparabel.
ai_photo_analysis:     Schaden: SICHTBAR -- Riss, abgebrochene Noppe, gebrochene Kante.
                       Zustand: nicht verglichen (Zeitbudget erschöpft).
                       Fotos: 2 weitere ungeprüft.
ai_recommended_action: Ware sperren, aussondern und Schichtleitung informieren.
ai_model:              qwen2.5:7b
ai_last_analyzed_at:   2026-09-15 12:32:39
```

Die Schadensbefunde sind kurz geblieben („Riss, abgebrochene Noppe, gebrochene Kante") — die
Wortgrenze aus Lauf 8/9 hält auch hier.

## 6. Vergleich mit Lauf 9

| | Lauf 9 | Lauf 10 |
|---|---|---|
| Eingabe | 5 Fotos | **dieselben** 5 Fotos (MD5 gleich) |
| Artikelabgleich | `match`, 0,9176 | `match`, 0,9176 |
| geprüfte Fotos | 3 (+1 angefangen und verloren) | 3 (4 und 5 gar nicht erst gestartet) |
| Laufzeit bis Antwort | **Abbruch bei 270,1 s** | **210,9 s** |
| Auslastung Knotenlimit | 100 % (gerissen) | 78 % |
| verlorene Rechenzeit | 65,6 s (Foto 4) | 0 s |
| Ergebnis in Odoo | `assessment unavailable`, `review_required` | `completed`, `scrap`, Konfidenz 0,95 |
| Bildbefund in Odoo | leer | vollständig, mit benannten Lücken |

Der Artikelabgleich liefert auf denselben Bildern denselben Wert auf vier Nachkommastellen — die
Einbettung ist an dieser Stelle reproduzierbar, anders als das Bildmodell.

## 7. Abweichungen und bekannte Vorbelastung

* `embed_katalog` musste 47 Artikel neu einbetten (10,90 s), weil der Backend-Neustart für den
  neuen Code den Cache geleert hat. Lauf 9 zahlte aus demselben Grund 16,90 s. Ohne diesen Posten
  läge die Antwort bei rund 200 s.
* Odoo protokolliert weiterhin alle 13–15 s
  `RuntimeError: Couldn't bind the websocket ... (evented port 8072)` mit `"GET /websocket" 500`.
  Unabhängig von der Meldungskette.
* `n8n` schreibt während des Workflows keine Container-Logs; `logs/n8n.log` bleibt deshalb leer.

## 8. Belege

* `fotos/` — die fünf hochgeladenen JPEGs
* `logs/backend.log`, `logs/ollama.log`, `logs/odoo.log` — Container-Logs des Zeitfensters
* `logs/ollama_models.txt`, `logs/container_images.txt`
* Selbstprüfung des Codes: `.claude/skills/qa-testlauf/scripts/pruef_budget.py`
  (fünf Fälle, ohne Modelle; Fall 2 ist Lauf 9 im Kleinen)

## 9. Was offen bleibt

1. **Der Schätzwert ist ein fester Wert, kein Messwert.** `vision_call_estimate_ms` = 60 s steht
   fest im Code. Ein gleitender Mittelwert der letzten Aufrufe wäre genauer — bei 40 s je Aufruf
   hätte in diesem Lauf noch ein viertes Foto hineingepasst.
2. **Das Backend protokolliert nicht, dass es ein Foto zurückstellt.** Die Zahl steht im Alert,
   aber keine Logzeile nennt den Grund. Für die Fehlersuche wäre ein `vision_budget_stop` mit
   Restzeit und Schätzwert nützlich.
3. **Die Summe der Einzelbudgets übersteigt weiterhin das Knotenlimit** (90 s Text + 240 s Bild +
   Textvergleiche). Die Anruferfrist deckelt das jetzt wirksam, aber die Einzelwerte sind
   weiterhin nicht miteinander abgestimmt.
