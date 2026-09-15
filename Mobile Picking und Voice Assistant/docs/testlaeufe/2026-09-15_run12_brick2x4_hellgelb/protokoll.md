# Testlauf 12 — vier Fotos geprüft, zum ersten Mal

**Datum:** 15.09.2026
**Auftrag:** L1/OUT/00248, Position 2 von 5
**Artikel:** Brick 2x4 hellgelb, SKU 6294939, Produkt 94, Regal B-01, 2 Stück,
Alpin Spielwaren GmbH
**Alert:** QA/0377 (Odoo-Datensatz-ID 378)
**Ergebnis:** `completed` / `scrap`, Konfidenz 1,0 — **Antwort nach 252,5 s, vier von fünf Fotos
geprüft**

Zeitangaben aus den Container-Logs, UTC.

## 1. Was dieser Lauf prüft

Erster Lauf mit dem **gleitenden Schätzwert**. Bis Lauf 11 stand vor jedem Bildaufruf ein fester
Wert (`vision_call_estimate_ms = 60 s`), an dem gemessen wurde, ob die Restzeit noch reicht.
Lauf 11 hatte ihn widerlegt: 82,88 s gegen 59,11 s im selben Lauf bei fast gleicher Tokenzahl.

Seit dem 15.09. hält `vision_client` die Dauer der letzten acht Schadensaufrufe je Modell fest und
liefert daraus den **80-%-Wert**. Vor `_MINDESTMESSUNGEN = 3` Messungen gilt weiter die Vorgabe.
Die Frage dieses Laufs: ändert der gemessene Wert das Verhalten der Kette, und in welche Richtung?

## 2. Eingangsdaten

Vorlage: Katalogbild aus Odoo (`default_code = 6294939`, 1 207 Byte PNG). ChatGPT erzeugte daraus
fünf Ansichten desselben beschädigten Steins, alle freigestellt auf weiß: schräg von oben,
Draufsicht, Nahaufnahme der Bruchstelle, Ansicht von hinten, Ansicht von unten.

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Testlauf 12: Artikel beschaedigt: Brick 2x4 hellgelb (SKU 6294939), Regal B-01.
              Noppe abgebrochen, Riss laengs ueber die Oberseite, Ecke abgeplatzt.
              Nicht versandfaehig. Fuenf Fotos angehaengt.
Fotos:        5  (357 KB gesamt)
```

## 3. Zeitlicher Ablauf

| Zeit (UTC) | Δ zum Start | Ereignis | Dauer |
|---|---|---|---|
| 13:15:59,6 | 0 s | Absenden in der PWA, `POST /api/quality-alerts` → 200 OK | — |
| ≈13:16:03 | ≈3 s | Anfrage `assessments/quality` im Backend, Anruferfrist bis ≈13:20:18 | — |
| 13:16:32,4 | 32,8 s | Textbewertung `qwen2.5:7b` fertig (214 Token) | **26,19 s** |
| 13:16:43,0 | 43,5 s | `embed_abgleich`: **`match`**, 6294939 auf **0,8521**, Abstand 0,0276 | 194 ms |
| 13:17:35,4 | 95,8 s | `vision_probe` Foto 1 | 49,00 s |
| 13:18:19,4 | 139,9 s | `vision_probe` Foto 2 | 42,38 s |
| 13:19:18,8 | 199,3 s | `vision_probe` Foto 3 | 56,11 s |
| 13:20:12,1 | 252,5 s | **`vision_probe` Foto 4**, danach Antwort → 200 OK, `callbacks/status` → 200 OK | 49,94 s |

Der Katalog war eingebettet im Cache — kein `embed_katalog`, das spart gegenüber den Läufen 10
und 11 rund 14 s.

## 4. Der gleitende Schätzwert in Aktion

Die Messreihe füllte sich während des Laufs:

| Nach Foto | Messungen (s) | Schätzung | Grundlage |
|---|---|---|---|
| 1 | 49,0 | 60,0 s | Vorgabe, zu wenige Messungen |
| 2 | 49,0 / 42,4 | 60,0 s | Vorgabe, zu wenige Messungen |
| 3 | 49,0 / 42,4 / 56,1 | **56,1 s** | 80-%-Wert der drei Messungen |
| 4 | + 49,9 | 56,1 s | 80-%-Wert der vier Messungen |

**Der Unterschied liegt bei Foto 4.** Vor seinem Start blieben 59,2 s Restzeit:

* Mit dem festen Wert von 60 s wäre es **nicht** gestartet — der Lauf wäre wie alle Vorläufe bei
  drei geprüften Fotos geblieben.
* Mit dem gemessenen Wert von 56,1 s startete es, brauchte 49,94 s und war mit **19 s Reserve**
  fertig.

Danach griff die Bremse und schrieb erstmals ihre Begründung ins Log:

```json
{"event_type": "vision_budget_stop", "stelle": "schadenspruefung", "restzeit_s": 19.0, "schaetzung_s": 56.1, "offene_fotos": 1}
{"event_type": "vision_budget_stop", "stelle": "zustandsvergleich", "restzeit_s": 19.0, "schaetzung_s": 56.1, "offene_fotos": 0}
```

Bis Lauf 11 stand über ein zurückgestelltes Foto **keine** Zeile im Backend-Log; die Zahl tauchte
nur im Odoo-Formular auf. Damit ist der zweite offene Punkt aus Lauf 10 erledigt.

## 5. Backend-Zeit gegen Ollama-Zeit

| Aufruf | ollama | Backend | Differenz |
|---|---|---|---|
| Foto 1 (`task 6`) | 48,05 s | 49,00 s | 0,95 s |
| Foto 2 (`task 67`) | 41,34 s | 42,38 s | 1,04 s |
| Foto 3 (`task 126`) | 49,06 s | **56,11 s** | **7,05 s** |
| Foto 4 (`task 191`) | 46,46 s | 49,94 s | 3,48 s |

Die Differenz ist Bildaufbereitung und Transport und schwankt zwischen 1 und 7 s. Die Schätzung
misst die **Backend**-Zeit — also die, gegen die auch der n8n-Knoten läuft. Das ist die richtige
Größe: Ollama-Zeiten allein würden die Kette systematisch zu optimistisch rechnen.

## 6. Ergebnis der Systembewertung

```
ai_evaluation_status:  completed
ai_disposition:        scrap
ai_confidence:         1.0
ai_summary:            Noppe abgebrochen und eingespannt, nicht mehr versandfähig.
ai_photo_analysis:     Schaden: SICHTBAR -- Riss, abgebrochene Noppe, gebrochene Kante.
                       Zustand: nicht verglichen (Zeitbudget erschöpft).
                       Fotos: 1 weitere ungeprüft.
ai_recommended_action: Ware sperren, aussondern und Schichtleitung informieren.
ai_model:              qwen2.5:7b
ai_last_analyzed_at:   2026-09-15 13:20:12
```

`Fotos: 1 weitere ungeprüft.` statt bisher 2 oder 3 — die Zeile zählt mit, was der gleitende Wert
zusätzlich möglich gemacht hat.

## 7. Artikelachse: der zweitknappste Abstand aller Läufe

| Rang | Artikel | Wert |
|---|---|---|
| 1 | **6294939 (erwartet)** | **0,8521** |
| 2 | 4648231 — Brick 2x2 hellgelb, **derselbe Auftrag** | 0,8244 |
| 3 | 343724 | 0,7383 |

Abstand **0,0276**, knapp über der Knappheitsschwelle von 0,02. Gleiche Farbe, gleiche Familie,
andere Länge — genau die Konstellation, in der Lauf 5 noch `unsicher` meldete (Abstand 0,0000).
Der Lauf zeigt damit auch, wo die Achse dünn wird: **nicht** bei fremden Objekten, sondern bei
Geschwistern im selben Karton.

## 8. Vergleich mit den Vorläufen

| | Lauf 10 | Lauf 11 | Lauf 12 |
|---|---|---|---|
| Fotos angenommen | 5 | 5 | 5 |
| **Fotos geprüft** | 3 | 2 | **4** |
| Schätzwert | fest 60 s | fest 60 s | **gleitend, 56,1 s ab Foto 3** |
| Textbewertung | 54,16 s | 74,94 s | **26,19 s** |
| Bildaufrufe | 47,1 / 42,5 / 42,2 s | 82,9 / 59,1 s | 49,0 / 42,4 / 56,1 / 49,9 s |
| Laufzeit bis Antwort | 210,9 s | 247,9 s | 252,5 s |
| Auslastung Knotenlimit | 78 % | 92 % | 94 % |
| Ergebnis | `completed` | `completed` | `completed` |

Die 94 % sind der höchste Wert eines **erfolgreichen** Laufs. Die Reserve von 19 s ist knapp, aber
sie ist gewollt: der gleitende Wert schöpft die Frist aus, statt sie zu verschenken.

## 9. Abweichungen und bekannte Vorbelastung

* Die Textbewertung war mit 26,19 s die schnellste aller Läufe (214 Token gegen 950 in Lauf 11).
  Die Streuung der Textstufe ist damit 20–75 s — ähnlich breit wie die der Bildstufe.
* Odoo protokolliert weiterhin alle 13–15 s `RuntimeError: Couldn't bind the websocket`.
* Beim Erzeugen der Fotos: ChatGPT **virtualisiert die Nachrichtenliste**. Das „letzte `img` im
  DOM" war zwischenzeitlich ein Bild aus Lauf 11; es wurde heruntergeladen, beim MD5-Vergleich
  erkannt und verworfen. Zuverlässig ist nur der höchste `data-testid="conversation-turn-N"`.
* In der PWA braucht ein Positionswechsel Zeit: der erste Versuch öffnete den Dialog noch mit
  Position 1 („Brick 2x2 hellgelb"). Abgebrochen, Position neu gesetzt, Kopfzeile geprüft.

## 10. Belege

* `fotos/`, `fotos_original/`, `kontaktabzug.jpg`, `pruefsummen.txt`
* `run12_brick2x4_hellgelb.png` — Katalogbild aus Odoo
* `logs/backend.log` (enthält die beiden `vision_budget_stop`-Zeilen), `logs/ollama.log`,
  `logs/odoo.log`

## 11. Was offen bleibt

1. **Die Messreihe überlebt keinen Neustart.** Sie liegt im Prozess. Nach jedem Backend-Neustart
   laufen die ersten drei Aufrufe wieder gegen die Vorgabe von 60 s. Das ist bewusst so — eine
   kalte Maschine rechnet ohnehin anders —, kostet aber je Neustart eine Messreihe.
2. **Der Zustandsvergleich kommt seit Lauf 9 nie mehr dran.** Er steht am Ende der Kette und
   braucht noch einmal einen vollen Aufruf. Bei fünf Fotos bleibt dafür nie Zeit. Wenn er
   fachlich wichtiger ist als das vierte Foto, müsste er **vor** die letzten Fotos.
3. **Die Artikelachse wird bei Geschwistern dünn** (0,0276 in diesem Lauf). Die Knappheitsschwelle
   von 0,02 hat gehalten, aber der Abstand zu einem Fehlurteil ist hier kleiner als der Abstand
   zwischen zwei Aufrufen desselben Bildmodells.
