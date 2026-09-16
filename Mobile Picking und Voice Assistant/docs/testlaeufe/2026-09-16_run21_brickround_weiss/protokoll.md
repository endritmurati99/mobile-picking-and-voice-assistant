# Testlauf 21 — Fotos ohne Katalogbild: die Artikelachse bricht ein

**Datum:** 16.09.2026
**Alert:** QA/0385 (id 386)
**Auftrag:** L1/OUT/00239, Position 3 von 5
**Artikel:** Brick Round 2x2x2 weiß, SKU 6096680, Regal C-02, 4 Stück, ACME Demo GmbH
**Fotos:** 2 (136 KB), **mit Gemini erzeugt, ohne Katalogbild als Vorlage**
**Fotoobergrenze:** `QA_MAX_ASSESSMENT_PHOTOS=3` (Produktivwert, zwei Fotos gemeldet)

---

## 1. Was dieser Lauf prüft

**Die Artikelachse ohne den stillen Vorteil, den alle 20 Läufe davor hatten.**

In jedem bisherigen Lauf entstanden die Schadensfotos **aus dem Katalogbild**: Vorlage an ChatGPT
anhängen, Schaden hineinrechnen lassen. Meldefoto und Katalogbild teilten damit Herkunft, Pose,
Beleuchtung und Rendering-Stil. Dass der Einbettungsabgleich sie einander zuordnet, ist unter
diesen Bedingungen ein schwächerer Beleg, als er aussieht.

Hier war das anders, und zwar **unfreiwillig**: Gemini nimmt keinen Bildanhang an, wenn der
Upload-Dialog über die Oberfläche bedient wird — der Datei-Eingang wird verworfen, sobald das Menü
schließt. Die Vorlage ließ sich deshalb nur **als Text beschreiben** („weisser zylindrischer
LEGO-Baustein, rund, etwa 2x2 Noppen breit und 2 Bausteine hoch, mit vier runden Noppen obenauf,
glaenzendes weisses ABS-Plastik").

Damit misst dieser Lauf zum ersten Mal, was der Einbettungsabgleich leistet, wenn das Meldefoto
**nicht** vom Katalogbild abstammt.

### Zusätzlich neu

- **Formfamilie rund.** In 20 Läufen kam nur Eckiges vor (Brick, Plate, Roof Tile, Bow). DINOv2
  ist formdominant, ein Zylinder ist eine ungeprüfte Achse.
- **Farbe weiß.** Die Farbe, die in Lauf 3 im Lagerfoto scheiterte (0,4973, Platz 5) und
  freigestellt in Lauf 4 trug (0,8723).

### Warum nur zwei Fotos

Gemini hat den dritten Auftrag (Nahaufnahme der Bruchstelle) **zweimal still verworfen** — die
Anfrage steht in der Unterhaltung, es kam keine Antwort und kein Fehler. Zwei Fotos sind zulässig;
Lauf 6 lief ebenfalls mit zweien.

---

## 2. Eingangsdaten

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Testlauf 21: Artikel beschaedigt: Brick Round 2x2x2 weiss (SKU 6096680),
              Regal C-02. Langer ausgefranster Riss ueber die Zylinderwand, eine Noppe
              ausgebrochen. Nicht versandfaehig. Zwei Fotos angehaengt.
Fotos:        2  (136 KB gesamt)
```

Foto 1 ist die strenge Draufsicht auf die vier Noppen mit der ausgebrochenen Noppe, Foto 2 die
Schrägansicht mit dem durchgehenden Riss. Kontaktabzug in `kontaktabzug.jpg`.

---

## 3. Zeitlicher Ablauf

| Zeit | seit Start | Dauer | Ereignis | Quelle |
|---|---|---|---|---|
| **12:27:38,9** | 0 s | — | **Meldung abgesendet** | Browser |
| 12:28:03 | 24 s | 18,4 s | Textbewertung (Disposition) | ollama.log |
| 12:28:03,9 | 25 s | 0,72 s | `embed_abgleich`: **`mismatch`** | backend.log |
| 12:28:46,2 | 67 s | 39,4 s | Schadensprüfung Foto 1 | backend.log |
| 12:29:24,6 | 106 s | 35,6 s | Schadensprüfung Foto 2 | backend.log |
| 12:29:24 | 105 s | — | Alert geschrieben, `callbacks/status` → 200 | backend.log |

**Gesamtdauer 1 min 45 s** — kürzester Lauf der Reihe, bei zwei Fotos und ohne Zustandsvergleich.

---

## 4. Ergebnis

```
name:                  QA/0385
ai_evaluation_status:  review_required
ai_failure_reason:     Foto widerspricht der Meldung, siehe Fotoanalyse.
ai_photo_analysis:     Artikel: FALSCHES TEIL -- Foto passt zu 343701 (0.609), nicht zum
                       bestellten Artikel 6096680 (dort Platz 6).
                       Artikel: nächste Treffer im Katalog -- 343701 0.609, 4250172 0.554,
                       6294237 0.543.
                       Schaden: SICHTBAR -- Riss, gebrochene Kante.
                       Texturteil der Meldung (nicht wirksam): scrap, Konfidenz 0.95.
```

---

## 5. Befunde

### 5.1 Die Artikelachse scheitert — selbstbewusst und deutlich

```json
{"urteil": "mismatch", "grund_art": "anderer_artikel", "erwartet": "6096680",
 "rang": [["343701", 0.6087], ["4250172", 0.5541], ["6294237", 0.5427]], "abstand": 0.0546}
```

Drei Dinge daran sind bemerkenswert:

1. **Der erwartete Artikel steht auf Platz 6**, nicht auf Platz 1 oder 2.
2. **Der Spitzenwert liegt bei 0,6087.** In allen 20 Läufen davor lag der richtige Artikel
   zwischen 0,64 und 0,93, meist über 0,85. Selbst der Spitzenreiter ist hier also auffällig
   schwach — aber immer noch weit über der Fremdschwelle von 0,45, es wird kein `unsicher`.
3. **Der Abstand beträgt 0,0546** und liegt damit klar über der Knappheitsschwelle von 0,02. Das
   Urteil ist also **kein Zweifelsfall, sondern eine falsche Gewissheit.**

Die in Lauf 17 eingebaute Weitersuche auf dem nächsten Foto greift hier **nicht** — und das ist
richtig so: sie löst nur bei `zu_dicht` aus, nicht bei `mismatch`. Ein zweites Foto hätte
denselben Fehler wiederholt, denn beide Fotos stammen aus derselben Quelle.

### 5.2 Was das über die bisherigen 20 Läufe sagt

**Die `match`-Ergebnisse der Läufe 4 bis 20 sind teilweise ein Artefakt der Bildherstellung.**
Wenn das Meldefoto aus dem Katalogbild gerechnet wird, teilen beide Pose, Ausleuchtung,
Materialwirkung und Rendering-Stil. DINOv2 misst Bildähnlichkeit, nicht Artikelidentität — unter
diesen Bedingungen misst es also auch die gemeinsame Herkunft mit.

Das entwertet die früheren Messungen nicht, aber es verschiebt, was sie belegen: Sie zeigen, dass
der Einbettungsweg **innerhalb einer Bildwelt** zuverlässig trennt (und der Textvergleich das
nicht tut — der Befund aus Abschnitt 3 der Gesamtübersicht bleibt gültig). Sie zeigen **nicht**,
dass er ein echtes Lagerfoto einem Katalogbild zuordnet.

Der Domänensprung war bereits bekannt: Lauf 3 gegen Lauf 4, dasselbe Teil, 0,4973 im Lagerfoto
gegen 0,8723 freigestellt. Neu ist, dass **auch ein freigestelltes Studiofoto nicht reicht**, wenn
es nicht vom Katalogbild abstammt.

### 5.3 Die Schadensachse trägt auch hier

```
Schaden: SICHTBAR -- Riss, gebrochene Kante.
```

Beide Fotos wurden geprüft, der Schaden auf Anhieb erkannt und übersetzt. Das bestätigt Lauf 20 auf
einer neuen Formfamilie und einem Bild, das nicht aus dem Katalogbild stammt: **Die Schadensachse
hängt nicht an der Bildherkunft, die Artikelachse schon.**

### 5.4 Die Kette entscheidet trotzdem richtig

Falscher Artikelbefund plus sichtbarer Schaden ergibt einen Widerspruch, und der geht an einen
Menschen: `review_required` mit beiden Seiten im Klartext, inklusive Rangfolge. Der Mensch sieht
`343701 0.609, 4250172 0.554, 6294237 0.543` und erkennt an den niedrigen Werten, dass hier nichts
richtig passt.

**Kein `completed` mit falschem Artikel, kein stilles Durchwinken.** Der Widerspruchszweig fängt
den Fehler der Artikelachse ab — genau dafür wurde er gebaut.

### 5.5 Laufzeit

1 min 45 s, der kürzeste Lauf der Reihe. Zwei Fotos statt drei sparen rund 37 s, und der
Zustandsvergleich entfällt, weil der Schaden sichtbar ist. Drei Modellaufrufe insgesamt.

---

## 6. Was daraus folgt

**Für die Arbeit:** Die Artikelachse ist an die Bildwelt gebunden. Das ist eine Eigenschaft des
Verfahrens, keine Fehlfunktion — und sie ist jetzt zweifach belegt (Domänensprung Lager/freigestellt
in Lauf 3/4, Herkunftssprung in Lauf 21).

**Offen, und ohne neue Messung nicht zu beantworten:** Ob ein echtes Foto eines echten Teils gegen
das Katalogbild trägt. Beide Enden der Messreihe sind synthetisch — entweder aus dem Katalogbild
gerechnet oder frei erfunden. Ein Handyfoto eines realen Bausteins wäre die Messung, die diese
Frage schließt.

**Nicht zu tun:** Die Knappheitsschwelle anfassen. Sie greift hier nicht, weil der Abstand mit
0,0546 weit darüber liegt. Was fehlt, ist keine engere Schwelle, sondern eine **untere Schranke auf
den Spitzenwert** — 0,6087 ist für einen echten Treffer auffällig niedrig. Ob eine solche Schranke
trägt, müsste über alle 63 archivierten Fotos gemessen werden, bevor sie eingebaut wird.

---

## 7. Belege

| Datei | Inhalt |
|---|---|
| `fotos/qa_photo_01..02.jpg` | die beiden gemeldeten Fotos, 1024 px |
| `fotos_original/` | die Gemini-Originale, 2048 px |
| `kontaktabzug.jpg` | beide Ansichten nebeneinander |
| `pruefsummen.txt` | MD5 von Original und aufbereiteter Fassung |
| `run21_brickround_weiss.png` | das Katalogbild, gegen das abgeglichen wurde |
| `logs/backend.log` | `embed_abgleich`, Schadensprüfungen, Zeitstempel |
| `logs/ollama.log` | drei Modellaufrufe |
| `logs/odoo.log` | Alert-Schreibvorgang |
