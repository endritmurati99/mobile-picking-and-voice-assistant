# Gegentest zum Artikelabgleich: weißer Hintergrund gegen Lagerfoto

**Datum:** 15.09.2026
**Frage:** Liegt der Artikelabgleich falsch, oder liegt es am Foto?
**Verfahren:** `facebook/dinov2-base` im Dienst `embed`, direkt über `POST /abgleich`
angesprochen — ohne die übrige Kette, damit nur der Abgleich gemessen wird.

## 1. Anlass

In den Läufen 1, 2 und 3 lautete das Urteil des Artikelabgleichs dreimal `mismatch`, und dreimal
gewann derselbe falsche Artikel `301124` (Brick 2x2 hellgrün) — gegen ein gelbes 2x2-Foto, gegen
ein weißes 1x2x2-Foto und gegen dasselbe weiße 1x2x2-Foto erneut. Offen war, ob das Verfahren
untauglich ist oder ob die generierten Regalfotos zu weit von den Katalogbildern entfernt liegen.

## 2. Aufbau

Der Dienst hält den Katalog aus 47 eingebetteten Artikelbildern im Speicher
(`katalog_stand` aus dem laufenden Betrieb, `modell: facebook/dinov2-base`). Abgefragt wurde
dreimal dasselbe Objekt, Brick 1x2x2 weiß, SKU 6101121:

| Eingabe | Datei |
|---|---|
| unverändertes Katalogbild | `2026-09-15_run3_brick1x2x2_weiss/run3_brick_1x2x2_weiss_p72.png` |
| Schadensfoto, Lagerhintergrund | `2026-09-15_run3_brick1x2x2_weiss/fotos/qa_photo_01.jpg` |
| Schadensfoto, weißer Hintergrund | `fotos/qa_photo_01.jpg` (dieser Ordner) |

Das dritte Bild entstand aus derselben Vorlage über ChatGPT, mit der Anweisung: gleicher Stein,
gleiche Beschädigung, gleiche Kameraperspektive, aber freigestellt auf weißem Grund, diffuses
Studiolicht, keine Umgebung.

## 3. Ergebnis

| Eingabe | Urteil | Platz 1 | Wert für 6101121 | Abstand zu Platz 2 |
|---|---|---|---|---|
| Katalogbild | `match` | 6101121 | **1,0** | 0,109 |
| Schaden, weißer Hintergrund | `match` | 6101121 | **0,8723** | 0,0694 |
| Schaden, Lagerhintergrund | `mismatch` | 301124 (0,4973) | **0,393**, Platz 5 | 0,0774 |

Vollständige Rangfolgen:

```
Katalogbild        6101121 1.0     343701 0.891   6294237 0.8084  6135522 0.7961  4250172 0.7923
weisser Grund      6101121 0.8723  343701 0.8029  4250172 0.7197  6294237 0.7166  6135522 0.7137
Lagerhintergrund    301124 0.4973 4183780 0.4199  4159527 0.4021  4185178 0.3982  6101121 0.393
```

## 4. Bewertung

Dasselbe Objekt mit derselben Beschädigung erreicht freigestellt **0,8723 auf Platz 1** und im
Regalfoto **0,393 auf Platz 5**. Alle Ähnlichkeitswerte brechen im Regalfoto flächig ein: der
beste Kandidat kommt dort nicht über 0,4973, während er freigestellt bei 0,8723 liegt.

**Der Artikelabgleich ist nicht das Problem.** DINOv2 bettet das Foto ein, wie es ist — samt
Karton, Regalboden, Streulicht und Schattenwurf. Diese Bildanteile haben im Katalog kein
Gegenstück, weil dort jedes Bild freigestellt ist. Das Verfahren vergleicht also zwei verschiedene
Bildwelten, nicht zwei Teile.

Damit ist auch die Rangfolge der drei bisherigen Läufe erklärt: Wenn der Bildinhalt im
Einbettungsraum stark verrauscht ist, entscheidet nicht mehr die Teileform, sondern welcher
Katalogeintrag zufällig am nächsten liegt — dreimal `301124`.

## 5. Folgerungen

1. Für die Bewertung der Artikelachse müssen Meldefotos und Katalogbilder aus derselben Bildwelt
   stammen. Entweder das Meldefoto wird freigestellt, bevor es in den Abgleich geht, oder der
   Katalog enthält zusätzlich Aufnahmen im Lagerkontext.
2. Freistellen ist der kleinere Eingriff: ein Segmentierungsschritt vor der Einbettung, der den
   Hintergrund entfernt. Das ändert nichts am Modell und nichts an den Schwellen.
3. Die Schadensachse ist von alldem nicht betroffen. `gemma4:12b` hat in Lauf 3 beide Schäden im
   Regalfoto korrekt benannt.

## 6. Belege im Ordner

| Datei | Inhalt |
|---|---|
| `fotos_original/run4_weiss_01.png` | von ChatGPT erzeugtes Schadensbild, weißer Hintergrund |
| `fotos/qa_photo_01.jpg` | auf 1 024 px skalierte Fassung, Eingabe des Abgleichs |
| `pruefsummen.txt` | MD5-Summen |
