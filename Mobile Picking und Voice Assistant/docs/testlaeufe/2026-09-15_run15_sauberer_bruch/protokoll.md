# Testlauf 15 — der Zustandsvergleich läuft, und findet den Schaden trotzdem nicht

**Datum:** 15.09.2026
**Auftrag:** L1/OUT/00248, Position 4 von 5
**Artikel:** Brick 2x2 grün, SKU 4183780, Produkt 76, Regal C-02, 5 Stück,
Alpin Spielwaren GmbH
**Alert:** QA/0380 (Odoo-Datensatz-ID 381)
**Ergebnis:** `review_required` — **Widerspruch zwischen Text und Bild, Entscheidung an den Menschen**

Zeitangaben aus den Container-Logs, UTC.

## 1. Was dieser Lauf prüft

Seit Lauf 9 kam der Zustandsvergleich nie mehr an die Reihe; seit dem Umbau vom 15.09. läuft er
nur noch bei `intact`. Damit fehlte der Beleg, dass er überhaupt arbeitet.

Dieser Lauf konstruiert den Fall, für den er laut Code existiert: **ein sauber abgebrochenes Eck**.
`DAMAGE_PROMPT` kann es nicht sehen — „eine glatte Bruchfläche ist keine ausgefranste Stelle" —,
der Soll/Ist-Vergleich gegen das Katalogbild soll es fangen.

Drei Fotos statt fünf, `QA_MAX_ASSESSMENT_PHOTOS = 3` wie im Betrieb, damit am Ende Zeit für den
Vergleich bleibt.

## 2. Eingangsdaten

Vorlage: Katalogbild aus Odoo (`default_code = 4183780`). ChatGPT erzeugte drei Ansichten eines
Steins, dem **eine Ecke vollständig fehlt**, Bruchfläche glatt und eben wie geschnitten:
schräg von oben, strenge Draufsicht, Seitenansicht auf die Bruchfläche. Ausdrücklich **kein** Riss,
keine ausgefransten Kanten, keine Absplitterungen.

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Testlauf 15: Artikel beschaedigt: Brick 2x2 gruen (SKU 4183780), Regal C-02.
              Eine Ecke fehlt vollstaendig, Bruchflaeche glatt. Nicht versandfaehig.
              Drei Fotos angehaengt.
Fotos:        3  (201 KB gesamt)
```

## 3. Zeitlicher Ablauf

Die Zuordnung der Aufrufe stammt aus den **Token-Zahlen** im ollama-Log, nicht aus der Reihenfolge:
Meldefotos gehen mit 459 Prompt-Token hinein, das kleine Katalogbild mit 252, Textaufrufe tragen
gar kein Bild.

| Zeit (UTC) | Δ zum Start | Ereignis | Token | Dauer |
|---|---|---|---|---|
| 15:33:59,5 | 0 s | Absenden in der PWA | — | — |
| 15:34:26,8 | 27,3 s | `embed_abgleich`: **`unsicher`**, Grund `zu_dicht` | — | 1,34 s |
| 15:35:13,0 | 73,5 s | `describe` des Meldefotos (Rückfallweg Artikel) | 304 | 44,57 s |
| 15:35:43,4 | 103,9 s | **Textmodell**: Artikelvergleich | 451 | 27,73 s |
| 15:36:15,4 | 135,9 s | `vision_probe` Schadensfoto 1 | 459 | 30,13 s |
| 15:36:51,4 | 171,9 s | `vision_probe` Schadensfoto 2 | 459 | 34,26 s |
| 15:37:25,6 | 206,1 s | `vision_probe` Schadensfoto 3 | 459 | 32,41 s |
| 15:37:48,6 | 229,1 s | `vision_probe` **Katalogbild** (Soll-Befund) | **252** | 21,21 s |
| 15:38:10,1 | 250,6 s | **Textmodell**: Zustandsvergleich, danach Antwort und Callback | 382 | 19,29 s |

**Alle drei Fotos geprüft, der Zustandsvergleich vollständig gelaufen** — Bildaufruf für das
Katalogbild plus Textvergleich. Zum ersten Mal seit Lauf 8.

## 4. Das Ergebnis des Vergleichs

```json
{"event_type": "condition_compare", "new_damage": false, "damage": "intact",
 "reason": "Die Beschreibungen stimmen überein und deuten auf einen Neuzustand hin."}
```

**Beide Stufen haben den Schaden übersehen.** Die absolute Prüfung fand auf allen drei Fotos nichts
(`intact`), und der Vergleich, der genau dafür gebaut ist, fand ebenfalls nichts.

## 5. Was die Kette daraus gemacht hat

```
ai_evaluation_status:  review_required
ai_failure_reason:     Foto widerspricht der Meldung, siehe Fotoanalyse.
ai_photo_analysis:     Schaden: keine Auffälligkeit sichtbar.
                       Hinweis: Die Einstufung lautet „Aussondern", aber kein Foto belegt einen
                       Schaden. Aussondern lässt sich nicht zurücknehmen — bitte manuell
                       entscheiden.
                       Texturteil der Meldung (nicht wirksam): scrap, Konfidenz 0.95.
                       Brick fehlt eine Ecke und ist nicht mehr versandfähig.
```

**Das ist das richtige Verhalten.** Das Texturteil sagte `scrap` (die Meldung nennt die fehlende
Ecke), der Bildbefund sagte „nichts zu sehen" — der Widerspruchszweig hat daraus kein Urteil
gemacht, sondern die Entscheidung an einen Menschen gegeben, mit beiden Seiten im Klartext. Kein
falsches `sellable`, kein blindes `scrap`.

Der Lauf ist damit **kein Fehlschlag der Kette, sondern ein Fehlschlag der Bilderkennung, den die
Kette aufgefangen hat**.

## 6. Warum der Vergleich nichts fand — und warum der naheliegende Fix nicht trägt

`DAMAGE_PROMPT` fragt in `surface_description` ausschließlich nach der **Oberfläche**: „is it
smooth and continuous everywhere, or is there a region that looks torn, split, gouged, ragged or
broken open?" Eine sauber fehlende Ecke lässt jede Oberfläche glatt. Beide Beschreibungen — Soll
und Ist — sagen „glatt", und `compare_condition` vergleicht genau diese beiden Texte. Der Vergleich
kann nicht sehen, was die Beschreibung nie erfasst hat.

Der naheliegende Schluss wäre: ein zusätzliches Feld für den **Umriss**. Gemessen mit
`bench_umriss.py`, derselbe Prompt plus ein Feld `outline_description`:

| Foto | Produktiv | Mit Umriss-Feld |
|---|---|---|
| Lauf 15, schräg von oben | `damaged=False` | `damaged=False`, **„The body is complete with all corners and edges present."** |
| Lauf 15, Seitenansicht | `damaged=False` | `damaged=False`, **„complete with all corners and edges present."** |
| Lauf 13, Riss | `damaged=True`, 18,0 s | `damaged=True`, 47,9 s |
| Lauf 12, Riss + Noppe | `damaged=True`, 41,4 s | `damaged=True`, 54,8 s |

**Das Modell behauptet ausdrücklich die Vollständigkeit eines Steins, dem sichtbar eine Ecke
fehlt.** Es ist also kein Beschreibungsproblem, das ein Feld löst, sondern eine Grenze der
Wahrnehmung von `gemma4:12b`. Der Zusatz kostet 46–55 s statt 8–41 s je Aufruf und bringt nichts.

**Nicht eingebaut.** Das Skript bleibt als Beleg, dass dieser Weg gemessen und verworfen wurde.

## 7. Nebenbefund: die Artikelachse wird bei Geschwistern unsicher

```
urteil: unsicher, grund: zu_dicht
4183780 (erwartet)  0,8799
343724              0,8644   → Abstand 0,0155
301124              0,8570
```

Der richtige Artikel steht auf Platz 1, aber der Abstand unterschreitet die Knappheitsschwelle von
0,02. Damit übernahm der Textweg — ein zusätzlicher Bildaufruf (44,57 s) plus Textvergleich
(27,73 s), zusammen **72,3 s**, also 29 % der Laufzeit.

Die Ironie: Genau dieser Rückfallweg hat den Lauf gerettet. Ohne ihn wäre die Zeit früher
verbraucht gewesen, und der Zustandsvergleich hätte erneut nicht stattgefunden.

Der grüne 2x2-Würfel ist damit nach Lauf 5 (0,0000) der zweite Fall von `zu_dicht`. Beide Male
liegt es an Geschwistern derselben Formfamilie im Katalog, nicht an schlechten Fotos.

## 8. Gemessene Bildaufrufzeiten

| Aufruf | Token | Dauer |
|---|---|---|
| Meldefoto beschreiben | 304 | 44,57 s |
| Schadensfoto 1 | 459 | 30,13 s |
| Schadensfoto 2 | 459 | 34,26 s |
| Schadensfoto 3 | 459 | 32,41 s |
| Katalogbild (Soll) | 252 | **21,21 s** |

Der Soll-Aufruf ist mit 21,2 s der billigste Bildaufruf aller Läufe — das Katalogbild ist klein
und die Antwort kurz. Das relativiert die Kosten des Zustandsvergleichs: er kostet **nicht** so
viel wie ein Meldefoto, sondern gut die Hälfte.

## 9. Belege

* `fotos/`, `fotos_original/`, `kontaktabzug.jpg`, `pruefsummen.txt`
* `run15_brick2x2_gruen.png` — Katalogbild aus Odoo
* `logs/backend.log` mit der `condition_compare`-Zeile, `logs/ollama.log` mit den Token-Zahlen
* `.claude/skills/qa-testlauf/scripts/bench_umriss.py` — die Messung aus Abschnitt 6

## 10. Was daraus folgt

1. **Die Kette erkennt Oberflächenschäden, keine fehlende Geometrie.** Das ist jetzt gemessen und
   gilt für beide Bildstufen. Für die Arbeit ist das eine benennbare Grenze des Verfahrens, kein
   offener Fehler.
2. **Der Widerspruchszweig trägt.** Er hat den Fall sicher an einen Menschen gegeben, statt eine
   der beiden Halbwahrheiten zu wirksam zu machen.
3. **Offen bleibt die Frage nach einem anderen Bildmodell** auf genau dieser Achse. Die
   Schadensachse wurde am 14.08. mit acht Bildern gemessen (`gemma4:12b` 4/4 gegen `qwen2.5vl:7b`
   2/4) — alle acht zeigten **Oberflächenschäden**. Für fehlende Geometrie liegt keine
   Modellmessung vor.
