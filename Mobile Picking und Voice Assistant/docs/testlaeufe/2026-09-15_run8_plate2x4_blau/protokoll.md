# Testlauf 8 — vier Fotos, und warum nur drei ankommen

**Datum:** 15.09.2026
**Auftrag:** L1/OUT/00303, Position 3 von 6
**Artikel:** Plate 2x4 blau, SKU 4216758, Produkt 108, Regal B-01, 1 Stück, Meyer Spielwaren KG
**Alert:** QA/0373 (Odoo-Datensatz-ID 374)
**Ergebnis:** `ai_evaluation_status = completed`, **3 min 10 s**, **ein Foto ungeprüft**

Zeitangaben aus den Container-Logs, UTC.

## 1. Erwartung und Ergebnis

Erwartet war ein Abbruch. Lauf 7 hatte mit drei Fotos 254,5 s von 270 s des n8n-Knotenlimits
verbraucht; ein viertes Foto zu rund 48 s hätte die Kette reißen müssen.

**Eingetreten ist etwas anderes: Die Kette lief in 190 s durch und prüfte nur drei der vier
Fotos.** Im Odoo-Formular steht dazu die Zeile `Fotos: 1 weitere ungeprüft.`

Die Ursache steht in `odoo/addons/quality_alert_custom/models/quality_alert.py:237`:

```python
# Mehr als drei Fotos zu pruefen kostet je Bild rund 21 Sekunden und bringt
# selten mehr Erkenntnis. Die Gesamtzahl reist trotzdem mit, damit niemand
# glaubt, es sei alles angesehen worden.
_MAX_ASSESSMENT_PHOTOS = 3
```

`api_get_assessment_media` liefert höchstens drei Anhänge an die Kette (`limit=` in der
`search`), zählt aber alle (`photo_total`). Das Backend rechnet die Differenz in `skipped` und
schreibt sie in den Klartext.

**Die Obergrenze von drei Fotos war also bereits eingebaut, bevor ich sie gemessen habe.** Meine
Schlussfolgerung aus Lauf 7 — „drei Fotos sind das Maximum, das die Kette trägt" — war im Ergebnis
richtig, in der Begründung falsch: Es deckelt nicht das Zeitbudget, sondern diese Konstante. Vier
Fotos können die Kette gar nicht überlasten.

## 2. Eingangsdaten

Vorlage: Katalogbild aus Odoo (`default_code = 4216758`, 2 100 Byte PNG). ChatGPT erzeugte daraus
vier Ansichten derselben beschädigten Platte, alle freigestellt auf weiß: Schrägansicht,
Draufsicht auf die Noppenseite, Nahaufnahme der Bruchstelle, Ansicht von unten. Schaden:
abgebrochene Noppe, Riss quer durch die Platte, abgeplatzte Ecke.

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Artikel beschaedigt: Plate 2x4 blau (SKU 4216758), Regal B-01.
              Noppe abgebrochen, Riss quer durch die Platte, Ecke abgeplatzt.
              Nicht versandfaehig. Vier Fotos angehaengt.
Fotos:        4  (fotos/qa_photo_01.jpg bis _04.jpg, je 1 024 px JPEG)
```

## 3. Zeitlicher Ablauf

| Zeit (UTC) | Δ zum Start | Ereignis | Dauer |
|---|---|---|---|
| 08:32:56,1 | 0 s | Absenden in der PWA, `POST /api/quality-alerts` → 200 OK | — |
| ≈08:32:57 | 1 s | `POST http://n8n:5678/webhook/quality-assessment-v2` → 200 OK | — |
| ≈08:33:23 | 27 s | Textbewertung `qwen2.5:7b` | **25,10 s** |
| 08:33:24,9 | 28,8 s | `embed_abgleich`: Urteil **`match`**, 4216758 auf **0,8978** | < 1 s |
| 08:34:14,9 | 78,8 s | `vision_probe` Foto 1 (Bilddekodierung 14,58 s), `ok: true` | **50,00 s** |
| 08:34:58,1 | 122,1 s | `vision_probe` Foto 2 (Bilddekodierung 15,27 s), `ok: true` | **43,29 s** |
| 08:35:42,4 | 166,4 s | `vision_probe` Foto 3 (Bilddekodierung 21,22 s), `ok: true` | **44,30 s** |
| 08:36:01,3 | 185,2 s | `vision_probe` Katalogbild (Bilddekodierung 2,97 s), `ok: true` | **18,88 s** |
| ≈08:36:06 | 190 s | Abschließender Textabgleich (4,77 s), `assessments/quality` → 200 OK, `callbacks/status` → 200 OK | — |

**Gesamtlaufzeit: 3 min 10 s.** Gegen das n8n-Knotenlimit zählt die Strecke Webhook bis Antwort
auf `/assessments/quality`: **188,1 s von 270 s, Reserve 81,9 s.** Foto 4 wurde nie an die Kette
übergeben.

Dass der vierte Bildaufruf das **Katalogbild** war und nicht das vierte Foto, zeigen die
Token-Zahlen: Fotos 1 bis 3 gingen mit je 439 Prompt- und 256 Bild-Token hinein, der vierte Aufruf
mit 232 Prompt- und nur 49 Bild-Token. Das Katalogbild aus Odoo ist 192 px groß, die Meldefotos
1 024 px.

### 3.1 Inferenzzeiten

| Aufruf | Modell | Token | Bilddekodierung | Gesamt |
|---|---|---|---|---|
| Textbewertung | `qwen2.5:7b` | 224 | — | 25,10 s |
| Foto 1 | `gemma4:12b` | 507 | 14,58 s | 48,48 s |
| Foto 2 | `gemma4:12b` | 512 | 15,27 s | 42,41 s |
| Foto 3 | `gemma4:12b` | 496 | 21,22 s | 43,49 s |
| Katalogbild | `gemma4:12b` | 255 | 2,97 s | 18,14 s |
| Artikelvergleich (Text) | `qwen2.5:7b` | 70 | — | 4,77 s |

### 3.2 Die Bilddekodierung ist der zweitgrößte Posten

| Aufruf | Dekodierung | Gesamt | Anteil |
|---|---|---|---|
| Foto 1 | 14,58 s | 48,48 s | 30 % |
| Foto 2 | 15,27 s | 42,41 s | 36 % |
| Foto 3 | 21,22 s | 43,49 s | 49 % |
| Katalogbild | 2,97 s | 18,14 s | 16 % |

Die reine Auswertezeit schwankt wenig (10,5–17,1 s), die Dekodierung dagegen um Faktor 1,5
zwischen drei gleich großen Fotos. Kleinere Bilder wären der offensichtliche Hebel — aber genau
den hat die Kette schon einmal verworfen: Laut Messung in `assessment_media` verschwanden bei
512 px zwei von drei geprüften Rissen. `DAMAGE_MAX_EDGE = 1024` ist also kein Versehen, sondern
eine bezahlte Entscheidung zugunsten der Erkennung.

## 4. Ergebnis der Systembewertung

```
ai_evaluation_status:  completed
ai_disposition:        scrap
ai_confidence:         1.0
ai_summary:            Abgebrochene Noppe und Riss machen den Artikel unbrauchbar.
ai_recommended_action: Ware sperren, aussondern und Schichtleitung informieren.
ai_photo_analysis:
  Schaden: SICHTBAR -- crack running through the middle, broken piece missing
  from front left corner, large crack/break in the center-left area, a large
  cracked area with missing material, a smaller torn section at the bottom left,
  Riss, broken piece.
  Zustand: Abgleich mit dem Katalogbild bestätigt den Befund
           (Signifikante Risse und gebrochene Bereiche fehlen im SOLL-Zustand.)
  Fotos: 1 weitere ungeprüft.
```

Der Einbettungsabgleich lieferte den höchsten Wert der ganzen Serie: **0,8978** für den erwarteten
Artikel. Die flache Platte hat eine im Katalog eindeutige Silhouette.

## 5. Die Schadenszeile ist wieder lang — und das liegt nicht an den Dopplungen

`_schadensworte` hat gearbeitet: `Riss` und `broken piece` stehen einmal statt mehrfach. Die Zeile
ist trotzdem unlesbar lang, weil `gemma4:12b` diesmal **ganze Sätze** als Einzelbefunde geliefert
hat statt kurzer Begriffe:

```
crack running through the middle
broken piece missing from front left corner
large crack/break in the center-left area
a large cracked area with missing material
a smaller torn section at the bottom left
```

Das Glossar greift nur bei kurzen, kanonischen Begriffen (`crack`, `broken edge`, `chip`). Ein
ganzer Satz steht nicht darin und bleibt deshalb wörtlich stehen — so gebaut, hier aber mit dem
Ergebnis, dass fünf englische Sätze im Odoo-Formular landen.

**Offen:** Entweder der Prompt in `vision_client.py` verlangt ausdrücklich Ein- bis Zweiwortbefunde
(`DAMAGE_PROMPT` sagt bisher nur „array of short strings"), oder `_schadensworte` kürzt zu lange
Einträge auf ihr erstes Schlüsselwort. Die erste Variante ist die ehrlichere: sie ändert, was das
Modell liefert, statt nachträglich zu raten, was gemeint war.

## 6. Vergleich aller Fotoanzahlen

| | Lauf 5, 1 Foto | Lauf 6, 2 Fotos | Lauf 7, 3 Fotos | **Lauf 8, 4 Fotos** |
|---|---|---|---|---|
| Fotos übergeben | 1 | 2 | 3 | **3 von 4** |
| Bildaufrufe | 3 | 3 | 4 | **4** |
| Bildzeit gesamt | 121,6 s | 129,3 s | 169,9 s | **156,5 s** |
| Gesamtlaufzeit | 3 min 15 s | 2 min 42 s | 4 min 17 s | **3 min 10 s** |
| Auslastung n8n-Knoten (270 s) | 71 % | 59 % | 94 % | **70 %** |
| Endzustand | `completed` | `completed` | `completed` | `completed` |

Lauf 8 ist trotz eines Fotos mehr **schneller** als Lauf 7 — weil das vierte Foto gar nicht
übergeben wurde und die einzelnen Aufrufe diesmal günstiger liefen (Textbewertung 25,1 s statt
59,4 s, Katalogbild 18,1 s statt 24,1 s). Die Streuung zwischen zwei Läufen mit gleicher Fotozahl
ist damit größer als der Unterschied zwischen drei und vier Fotos.

## 7. Was das für die Zeitgrenzen heißt

Die Kette kann mit der jetzigen Odoo-Konstante **nie mehr als drei Fotos prüfen**. Das
Zeitbudget von 240 s und das Knotenlimit von 270 s werden damit nur im ungünstigen Fall knapp
(Lauf 7: 94 %), aber nicht durch die Fotoanzahl gesprengt.

Die in der Gesamtübersicht notierte Empfehlung „Fotoanzahl deckeln" ist damit erledigt — sie ist
bereits umgesetzt, an einer Stelle, die ich zuerst nicht gesucht hatte. Was offen bleibt, ist die
Budgetrechnung: 90 s Text plus 240 s Bild plus zwei Textvergleiche à 90 s dürfen zusammen
weiterhin länger laufen als die 270 s, die der n8n-Knoten wartet.

## 8. Belege im Ordner

| Datei | Inhalt |
|---|---|
| `run8_plate2x4_blau_p108.png` | Katalogbild aus Odoo, Vorlage |
| `fotos_original/run8_damage_01.png` bis `_04.png` | von ChatGPT erzeugte Schadensbilder |
| `fotos/qa_photo_01.jpg` bis `_04.jpg` | auf 1 024 px skaliert, Eingabe der Meldung |
| `kontaktabzug.jpg` | alle vier Ansichten nebeneinander |
| `pruefsummen.txt` | MD5-Summen |
| `logs/` | backend, ollama, n8n, odoo, Containerstände |
