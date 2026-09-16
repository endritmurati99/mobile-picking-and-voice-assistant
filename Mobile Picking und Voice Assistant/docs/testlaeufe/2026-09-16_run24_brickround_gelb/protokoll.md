# Lauf 24 — Runder Stein, Fotos aus dem Katalogbild (QA/0386)

**Datum:** 16.09.2026
**Artikel:** Brick 2x2x2 R=15 gelb, SKU 6023350, Produkt-ID 85
**Auftrag:** L1/OUT/00300, Position 1 von 7, Regal A-01, Kunde FH Demo Logistik
**Fotos:** 3, freigestellt auf weiß, aus dem Katalogbild erzeugt (ChatGPT)
**Endzustand:** `completed`, `quarantine`, Konfidenz 0,80
**Laufzeit:** 14:04:42 bis 14:08:01 UTC = **3 min 19 s**

## Was der Lauf prüft

Lauf 21 änderte zwei Dinge gleichzeitig: einen **runden** Artikel und eine **fremde Bildwelt**
(Fotos ohne Katalogvorlage, nur aus einer Textbeschreibung). Die Artikelachse scheiterte dort —
erwarteter Artikel auf Platz 6, Spitzenwert 0,6087 für ein falsches Teil. Offen blieb, welche der
beiden Änderungen das verursacht hat.

Dieser Lauf hält die Bildwelt fest (Fotos **aus** dem Katalogbild, wie in den Läufen 4 bis 20) und
lässt allein die runde Form neu sein. Eine Variable.

## Eingangsdaten

Beschreibung: „Runddach-Stein gelb hat einen durchgehenden Riss quer ueber die gewoelbte
Oberseite, an der oberen Kante fehlt ein Stueck mit rauer Bruchflaeche. Drei Fotos, freigestellt."
Schnellauswahl „Artikel beschädigt", Priorität Normal.

| Foto | Ansicht | MD5 (JPEG) |
|---|---|---|
| 1 | schräg von oben wie die Vorlage | `030F63686692965666060CE837A1A8D0` |
| 2 | nahe Seitenansicht (angefordert war Draufsicht) | `FE26338E615AE320734A790A78602721` |
| 3 | Nahaufnahme der Bruchstelle | `181531ACFDD0C12F6A2D165405FCB1A2` |

Foto 2 kam nicht als Draufsicht zurück. Der Schaden ist darauf sichtbar, und die Artikelachse
sieht ohnehin nur Foto 1 (`n8n_v2.py:322`) — der Lauf bleibt damit aussagekräftig.

## Zeitlicher Ablauf

| Zeit (UTC) | Komponente | Ereignis | Dauer |
|---|---|---|---|
| 14:04:42 | PWA | Meldung abgesendet, Alert QA/0386 angelegt | — |
| 14:04:44,8 | Backend | Webhook an n8n, HTTP 200 | 2,6 s |
| 14:04:45–14:05:13 | ollama `qwen2.5:7b` | Textbewertung (task 2643) | **35,4 s** |
| 14:05:25,4 | `embed` | Katalog neu eingebettet, 47 Artikel | **12,2 s** |
| 14:05:25,7 | `embed` | Artikelabgleich | **0,26 s** |
| 14:06:31,4 | ollama `gemma4:12b` | Foto 1 geprüft | **65,8 s** |
| 14:07:17,6 | ollama `gemma4:12b` | Foto 2 geprüft | **46,2 s** |
| 14:08:01,1 | ollama `gemma4:12b` | Foto 3 geprüft | **43,5 s** |
| 14:08:01,1 | Backend | `condition_compare_skipped`, Grund `schaden_bereits_sichtbar` | 0 s |
| 14:08:01 | Odoo | `ai_evaluation_status: completed` | — |

Auslastung des Knotenlimits: 199 s von 270 s = **74 %**. Bildzeit gesamt 155,5 s von 240 s = 65 %.

## Ergebnis: die Artikelachse trägt, der runde Stein war nicht das Problem

```json
{"event_type": "embed_abgleich", "urteil": "match", "grund_art": "treffer",
 "erwartet": "6023350",
 "rang": [["6023350", 0.9146], ["6380873", 0.7561], ["343724", 0.7522]]}
```

**Spitzenwert 0,9146, Abstand zu Platz 2 0,1585** — der zweitgrößte Abstand aller Läufe, nur der
Dachstein aus Lauf 6 lag mit 0,2396 darüber. Die runde Silhouette kommt im Katalog kein zweites
Mal vor und trennt deshalb sauber.

**Damit ist Lauf 21 entschieden:** Nicht die runde Form hat die Artikelachse gekippt, sondern die
fremde Bildwelt. Derselbe Formtyp erreicht mit katalogstämmigen Fotos 0,9146 auf Platz 1, mit frei
erzeugten Fotos 0,6096 auf Platz 6. Der Befund aus Abschnitt 3 der Gesamtübersicht — die Achse ist
bildweltgebunden — steht damit auf zwei unabhängigen Beinen: dem Lagerhintergrund (Läufe 1 bis 4)
und der Erzeugungsherkunft (Läufe 21 gegen 24).

Nebenbefund zur untersuchten Schranke aus Lauf 23: 0,9146 liegt deutlich über 0,80, der Lauf wäre
von einer unteren Schranke unberührt geblieben. Er stützt die Trennung, ohne sie zu beweisen.

## Ergebnis der Systembewertung

```
ai_disposition:        quarantine
ai_confidence:         0.80
ai_summary:            Riss und Bruchflaeche weisen auf Schadensursache hin, aber Zustand ist
                       noch nicht definitiv.
ai_photo_analysis:     Schaden: SICHTBAR -- Riss, gebrochene Kante.
ai_recommended_action: Ware sperren und manuelle Prüfung anfordern.
ai_model:              qwen2.5:7b
```

Zwei Dinge daran sind neu beziehungsweise bestätigt:

* **`quarantine` zum ersten Mal.** Die Vorläufe endeten auf `scrap` (Läufe 5 bis 14, 20) oder auf
  `review_required` über den Widerspruchszweig (Läufe 15 bis 18, 21). Die dritte Einstufung ist
  damit erstmals an einem echten Fall belegt.
* **Glossar und Entdopplung greifen.** Drei Fotos, jedes mit eigenen Befunden, ergeben zwei
  deutsche Begriffe: `Riss, gebrochene Kante`. Kein englischer Rest, keine Dopplung.

`condition_compare_skipped` mit Grund `schaden_bereits_sichtbar` — die Änderung aus Lauf 14 wirkt
wie vorgesehen: Bei `damaged` kann der Vergleich nichts mehr entscheiden und kostet deshalb auch
keinen Bildaufruf.

## Vergleich mit den Vorläufen

| | Lauf 20 (Plate 2x4) | Lauf 21 (rund, ohne Vorlage) | **Lauf 24 (rund, aus Vorlage)** |
|---|---|---|---|
| Fotos | 3 | 2 | **3** |
| Artikelachse | `match` | **`mismatch`, Platz 6** | **`match`, 0,9146** |
| Abstand zu Platz 2 | — | 0,0546 | **0,1585** |
| Bildaufrufe | 3 | 2 | **3** |
| Endzustand | `completed`, `scrap` 0,9 | `review_required` | **`completed`, `quarantine` 0,8** |
| Laufzeit | 2 min 31 s | 1 min 45 s | **3 min 19 s** |

Die Bildaufrufe lagen mit 43,5 bis 65,8 s im bekannten Band 37–83 s. Foto 1 war mit 65,8 s der
langsamste — dieselbe Streuung wie in Lauf 11, wo Foto 1 82,9 s brauchte.

## Abweichungen

**Der Katalog wurde mitten im Lauf neu eingebettet (12,2 s).** Ursache: Für Lauf 23 hatte ich den
Einbettungsdienst mit `fuelle_katalog.py` direkt befüllt. Das Skript schreibt aber nicht in den
Laufzeitspeicher des Backends (`runtime.katalog_merken`), also hielt das Backend den Katalog
weiterhin für leer und baute ihn erneut auf. Die 12,2 s gehen direkt vom Zeitfenster ab — offener
Punkt 7 der Gesamtübersicht, hier zum zweiten Mal gemessen (Lauf 7 A: 25,9 s für dieselben 47
Artikel, damals ohne warmen Dienst).

**Vor dem Lauf zwei Eingriffe in die Umgebung:**

* Die PWA hing im Zustand „Lagerdaten werden vorbereitet". Ursache war der fehlende CSRF-Token im
  Tab (Stolperfalle 12), nicht die Sitzung. Nach `sessionStorage.setItem` und `location.reload()`
  stand die Auftragsliste sofort.
* `qwen2.5vl:7b` belegte noch einen Modellplatz aus Lauf 22. Mit `keep_alive: 0` entladen, damit
  der Lauf im Produktivzustand misst (zwei Kettenmodelle geladen, dritter Platz frei).

**Bekannte Vorbelastung:** Odoo protokolliert weiterhin
`RuntimeError: Couldn't bind the websocket. Is the connection opened on the evented port (8072)?`
im Sekundentakt. Unabhängig von der Meldungskette.

## Belege

* `fotos/` — die drei abgesendeten JPEGs, `fotos_original/` — die PNGs von ChatGPT
* `kontaktabzug.jpg`, `pruefsummen.txt`
* `logs/` — Backend-, ollama-, n8n- und Odoo-Auszüge
* `run24_brickround_gelb.png` — das Katalogbild, aus dem die Fotos entstanden
