# Testlauf QA/0365 — Schadensmeldung mit lokaler Bilderkennung

**Datum:** 14.09.2026
**Alert:** QA/0365 (Odoo-Datensatz-ID 366)
**n8n-Execution:** #137, Workflow „Quality Assessment v2"
**Ergebnis:** Kette vollständig durchlaufen, Bewertung jedoch nicht zustande gekommen
(`ai_evaluation_status = review_required`, `ai_failure_reason = "assessment unavailable"`)

Alle Zeitangaben stammen aus den Container-Logs und sind in UTC notiert, wie dort protokolliert.
Die Ortszeit liegt zwei Stunden davor (16:12:40 UTC = 18:12:40 MESZ).

## 1. Aufbau

| Komponente | Wert |
|---|---|
| Picking-PWA | `https://localhost/`, Auftrag LT/OUT/00248, Position 1 von 5 |
| Artikel | Brick 2x2 hellgelb, SKU 4648231, Regal A-01, 4 Stück, Alpin Spielwaren GmbH |
| Backend | `mobilepickingundvoiceassistant-backend` |
| Workflow | n8n „Quality Assessment v2", published |
| Odoo | Version 19.0-20260723, Quality Alerts (`action-307`) |
| Inferenz | ollama/ollama:latest, CPU-Betrieb |

Beteiligte Modelle laut Logs: `qwen2.5:7b` (Textbewertung), `gemma4:12b` (Artikelabgleich per Bild),
Einbettungsdienst `embed` (Katalogabgleich). Ein Aufruf von `qwen2.5vl:7b` (Schadensprüfung) ist in
diesem Lauf nicht mehr zustande gekommen.

## 2. Eingangsdaten

Vorlage war das echte Produktbild aus der PWA (`https://localhost/api/products/78/image?size=1024`,
192 × 192 px, 1 802 Byte), abgelegt als `brick_2x2_hellgelb_p78.png`.

Daraus wurden mit ChatGPT (Modell „6 Pro", Bildgenerierung) fünf Schadensfotos desselben Steins aus
verschiedenen Perspektiven erzeugt. Die Vorlage wurde dem Modell als Bild mitgegeben, nicht nur
beschrieben.

| Datei | Perspektive / Schaden | Original (PNG) | Upload (JPEG, 1024 px) |
|---|---|---|---|
| 01 | schräg von oben, abgebrochene Noppe, Riss an der Kante | 1 613 033 B | 90 005 B |
| 02 | strenge Draufsicht, Noppe komplett abgebrochen | 1 923 434 B | 136 934 B |
| 03 | Nahaufnahme von der Seite, langer Riss in der Seitenwand | 1 952 997 B | 135 820 B |
| 04 | schräg von hinten/unten, abgeplatzte Ecke, Kratzer | 1 763 452 B | 104 413 B |
| 05 | im geöffneten Karton im Regal, Blitzlicht | 2 300 043 B | 173 185 B |

Originale: `fotos_original/`, Uploads: `fotos/`, Übersicht: `kontaktabzug.jpg`,
Prüfsummen: `pruefsummen.txt`. Alle fünf MD5-Summen unterscheiden sich, die Bilder sind also nicht
Kopien voneinander.

Die Verkleinerung auf 1024 px JPEG entspricht `DAMAGE_MAX_EDGE` im Backend; die Originale hätten
zusammen 9,5 MB belegt und das Upload-Limit von 10 MB nahezu ausgeschöpft.

Meldung im Formular:

```
Typ:          Artikel beschädigt
Priorität:    Normal
Beschreibung: Artikel beschaedigt: Brick 2x2 hellgelb (SKU 4648231), Regal A-01.
              Noppe abgebrochen, Riss an der Kante, Kratzer auf der Oberseite.
              Nicht versandfaehig. Fotos angehaengt.
Fotos:        5
```

## 3. Zeitlicher Ablauf

| Zeit (UTC) | Δ zum Start | Ereignis | Quelle |
|---|---|---|---|
| 16:12:38 | −2 s | Odoo legt QA/0365 an (`create_date`) | Odoo-Datensatz |
| 16:12:40 | 0 s | `POST /api/quality-alerts` → 200 OK | backend.log |
| 16:12:40,466 | 0,5 s | `POST http://n8n:5678/webhook/quality-assessment-v2` → 200 OK | backend.log |
| 16:12:40 | 0 s | n8n-Execution #137 startet | n8n-Oberfläche |
| 16:13:01,685 | 21,7 s | ollama lädt Runner `qwen2.5:7b` (`loaded runners count=1`) | ollama.log |
| 16:14:10,554 | 90,6 s | `llm_quality_disposition_failed`, Modell `qwen2.5:7b` | backend.log |
| 16:14:24,835 | 104,8 s | `embed_katalog`: 47 Artikel eingebettet, **13 129 ms** | backend.log |
| 16:14:24,836 | 104,8 s | `embed_katalog_bereit`, **13 709 ms** | backend.log |
| 16:14:25,096 | 105,1 s | `embed_abgleich`: Urteil **mismatch**, **259 ms** | backend.log |
| 16:14:25,097 | 105,1 s | `article_compare`: `same_article = false` | backend.log |
| ≈16:14:25 | ≈105 s | Beginn des `gemma4:12b`-Aufrufs (rückgerechnet aus `duration_ms`) | abgeleitet |
| 16:15:52,726 | 192,7 s | ollama lädt Runner `gemma4:12b` (`loaded runners count=2`) | ollama.log |
| 16:17:11 | 271 s | n8n-Execution #137 endet, `ai_last_analyzed_at` gesetzt | n8n / Odoo |
| 16:17:45,232 | 305,2 s | `vision_probe_failed`, `gemma4:12b`, `ReadTimeout`, **200 016 ms** | backend.log |

**Gesamtlaufzeit n8n-Execution #137: 4 min 31,215 s (271,2 s).**
Vergleichslauf #136 vom 10.09.2026: 4 min 19,75 s (259,8 s).

## 4. Messwerte im Einzelnen

### 4.1 Modell-Ladezeiten (Kaltstart)

| Modell | Laderunner fertig | Ladezeit ab jeweiligem Auslöser |
|---|---|---|
| `qwen2.5:7b` | 16:13:01,685 | ≈21,7 s nach Meldungseingang |
| `gemma4:12b` | 16:15:52,726 | ≈87,6 s nach Beginn des Aufrufs (≈16:14:25) |

Der `gemma4:12b`-Runner wurde als zweiter Runner geladen (`loaded runners count=2`), während
`qwen2.5:7b` noch im Speicher lag. Kontextgröße laut Log: `n_ctx_slot = 8192`, ein Slot,
`kv_unified = false`, Prompt-Cache aktiv mit 8192 MiB Limit.

**Das Laden von `gemma4:12b` verbrauchte allein rund 88 der 200 Sekunden, die dem Aufruf insgesamt
zur Verfügung standen — also etwa 44 % des Zeitbudgets, bevor die erste Inferenz begann.**

### 4.2 Einbettungsbasierter Artikelabgleich

```json
{"event_type": "embed_katalog", "artikel": 47, "duration_ms": 13129}
{"event_type": "embed_abgleich", "urteil": "mismatch", "grund_art": "anderer_artikel",
 "erwartet": "4648231",
 "rang": [["301124", 0.7634], ["343724", 0.717], ["6294237", 0.7161]],
 "abstand": 0.0464, "duration_ms": 259}
```

Begründung im Log:
„Foto passt zu 301124 (0.763), nicht zum bestellten Artikel 4648231 (dort Platz 4)."

Das Verfahren ordnete die generierten Fotos also einem **anderen** Katalogartikel zu. Der Abstand
zwischen Platz 1 und Platz 2 beträgt nur 0,0464 — die Rangfolge ist entsprechend wenig belastbar.
Der Katalogaufbau (47 Artikel) dauerte 13,1 s, der eigentliche Vergleich nur 259 ms.

### 4.3 Abbruch der Bildprüfung

```json
{"event_type": "vision_probe_failed", "model": "gemma4:12b",
 "error_type": "ReadTimeout", "error": "", "duration_ms": 200016}
```

Der Aufruf lief exakt in den konfigurierten Grenzwert `vision_timeout_ms = 200000`
(`backend/app/config.py:187`) und wurde abgebrochen.

### 4.4 Textbewertung

```json
{"event_type": "llm_quality_disposition_failed", "model": "qwen2.5:7b", "error": ""}
```

90,6 s nach Meldungseingang gescheitert; das Feld `error` ist leer, die Ursache ist aus dem Log
allein nicht bestimmbar. Hier besteht Nachbesserungsbedarf am Logging.

## 5. Endzustand des Datensatzes

```
name:                  QA/0365
create_date:           2026-09-14 16:12:38
photo_count:           5
ai_evaluation_status:  review_required
ai_failure_reason:     assessment unavailable
ai_last_analyzed_at:   2026-09-14 16:17:11
ai_disposition:        (leer)
ai_confidence:         0
ai_summary:            (leer)
ai_photo_analysis:     (leer)
ai_provider:           (leer)
ai_model:              (leer)
```

Positiv: Alle fünf Fotos sind vollständig in Odoo angekommen (`photo_count = 5`), die
Picker-Meldung wurde wortgleich übernommen, und das System ist bei ausbleibender Bewertung
kontrolliert auf „review_required" zurückgefallen, statt einen falschen Befund zu schreiben.

## 6. Auswertung

1. **Die Kette funktioniert technisch vollständig.** PWA → Backend (`200 OK`) → Outbox-Event →
   n8n-Webhook (`200 OK`) → Odoo-Datensatz mit fünf Fotos. Kein Glied ist ausgefallen.

2. **Die Bewertung scheitert an der Zeit, nicht an der Logik.** `ai_last_analyzed_at` steht auf
   16:17:11, der `gemma4:12b`-Aufruf lief aber noch bis 16:17:45. Die n8n-Execution war zu diesem
   Zeitpunkt bereits beendet und hat ein leeres Ergebnis übernommen; der Backend-Aufruf lief
   verwaist weiter. Das erklärt `assessment unavailable`.

3. **Der Kaltstart ist der größte Einzelposten.** Rund 88 s Modellladezeit innerhalb eines
   200-s-Budgets. Bei vorgewärmtem Modell stünde diese Zeit vollständig für die Inferenz zur
   Verfügung. Ein Keep-Alive für `gemma4:12b` und `qwen2.5vl:7b` ist die naheliegendste Maßnahme.

4. **Die Zeitschranken liegen zu dicht beieinander.** Gemessen: 271,2 s Gesamtlaufzeit gegen einen
   n8n-Node-Timeout von 270 s. Der Lauf ging nur durch, weil die 270 s für den einzelnen
   HTTP-Rückruf gelten, nicht für die gesamte Execution. Der Abstand ist damit faktisch null.

   | Schranke | Wert | Quelle |
   |---|---|---|
   | Ollama-Timeout je Aufruf | 200 s | `backend/app/config.py:187` |
   | Budget aller Vergleiche einer Meldung | 240 s | `backend/app/config.py:192` |
   | Wartezeit auf die Assessment-Sperre | 150 s | `backend/app/config.py:235` |
   | n8n-Node-Timeout des Rückrufs | 270 s | `n8n/workflows/quality-assessment-v2.json:251` |

   Da nur eine Bewertung gleichzeitig läuft (`_ASSESSMENT_GATE = asyncio.Semaphore(1)`,
   `backend/app/routers/n8n_v2.py:115`), kann Wartezeit plus Laufzeit rechnerisch 390 s erreichen
   und das n8n-Timeout deutlich überschreiten.

5. **Grenze der synthetischen Testdaten.** Der Einbettungsabgleich ordnete die generierten Fotos
   dem Artikel 301124 statt 4648231 zu. Für den Test der *Verfügbarkeit* der Kette ist das
   unerheblich, für eine Aussage über die *Erkennungsgüte* sind Fotos des realen Artikels
   erforderlich. Der geringe Abstand von 0,0464 zwischen Platz 1 und 2 zeigt zusätzlich, dass die
   Rangfolge bei diesem Katalogumfang wenig trennscharf ist.

## 7. Bekannte Vorbelastung (nicht Teil dieses Laufs)

Odoo protokolliert unabhängig vom Testlauf alle 13–15 s:

```
RuntimeError: Couldn't bind the websocket. Is the connection opened on the evented port (8072)?
"GET /websocket?version=19.0-2 HTTP/1.1" 500 -
```

Relevant, falls die Oberfläche auf Bus-Aktualisierungen für den Alert-Status wartet.

Ebenfalls unkritisch, aber im Log sichtbar:
`msg="model recommendations refresh failed" ... lookup ollama.com ... server misbehaving` —
der Container hat keinen Internetzugang, die lokale Inferenz ist davon nicht betroffen.

## 8. Verzeichnisinhalt

```
2026-09-14_QA0365/
├── protokoll.md                 (dieses Dokument)
├── brick_2x2_hellgelb_p78.png   Vorlage aus der PWA
├── kontaktabzug.jpg             alle fünf Perspektiven nebeneinander
├── pruefsummen.txt              MD5 je Datei
├── fotos/                       qa_photo_01..05.jpg, hochgeladen
├── fotos_original/              damage_01..05.png, wie generiert
└── logs/                        backend, n8n, ollama, odoo, Modell- und Imageliste
```

## 9. Wiederholung

Der Lauf ist als Skill hinterlegt und kann unverändert wiederholt werden:

```
.claude/skills/qa-testlauf/
├── SKILL.md
└── scripts/
    ├── prepare-photos.ps1     Skalierung, Kontaktabzug, Prüfsummen
    └── collect-evidence.ps1   Logs und Laufzeiten einsammeln
```

Empfehlung für den nächsten Lauf: Modelle vorher warmlaufen lassen, damit die Kaltstartzeit die
Messung nicht mehr dominiert, und zusätzlich einen Lauf mit Fotos des realen Artikels durchführen,
um Verfügbarkeit und Erkennungsgüte getrennt bewerten zu können.
