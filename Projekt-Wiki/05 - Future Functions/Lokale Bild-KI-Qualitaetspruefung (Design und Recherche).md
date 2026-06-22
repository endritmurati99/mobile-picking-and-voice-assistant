---
title: "Lokale Bild-KI-Qualitätsprüfung (Design & Recherche)"
tags:
  - feature
  - future
  - ai
  - vision
  - benchmark
  - n8n
  - traceability
status: in-research
component: n8n, backend, pwa
created: 2026-06-22
---

# Lokale Bild-KI-Qualitätsprüfung (Design & Recherche)

> [!abstract] Idee in einem Satz
> Ein **lokales Bild-KI-Modell** (via Ollama) prüft beim Kommissionieren das **Produktfoto** —
> ob es das erwartete Produkt ist (z. B. „rosa brick 2x2") und ob es in Ordnung/unbeschädigt ist —,
> **getriggert über n8n**, mit einem **„Evaluieren"-Befehl**. Gleichzeitig ist es ein
> **Forschungs-/Benchmark-Baustein**: Wir messen RAM, Latenz und Durchsatz, weil es auch auf
> **anderer Hardware** (z. B. dem Rechner des Profs) laufen soll.

---

## 1. Die zwei verbundenen Anwendungsfälle

### A) Qualitäts-/Identitätsprüfung beim Picking
- Picker wählt/scannt ein Produkt (z. B. `rosa brick 2x2`).
- Kamera nimmt ein Foto auf → lokales Vision-Modell bewertet:
  - **Identität:** Ist das wirklich der erwartete Lego-Block (z. B. `Brick 2x2 rot`)? (Abgleich gegen Namen / Referenzbild)
  - **Defekt (Kern-Fokus):** Kratzer, fehlende oder beschädigte **Noppen**, Verschmutzung, Verformung — und **Seriennummer unlesbar**.
- Ergebnis als **strukturierte Ausgabe** → kann einen Quality Alert (`quality.alert.custom`) anreichern.

### B) Retouren-Prüfung per Seriennummer (+ optional Bild)
Kombiniert mit [[Barcode als Seriennummer-Bestätigung]] und [[Karton- und Behaelter-Tracking (Put-to-Box)]]:

> [!example] Beispiel Retoure
> Wir haben **Teil A mit Seriennummern 1, 2, 3, 4** an den Kunden geschickt.
> Der Kunde sendet **Teil A mit Seriennummern 1, 5, 5** zurück.
> Das System erkennt automatisch:
> - **Fehlend:** 2, 3, 4 (nicht zurückgekommen)
> - **Unbekannt/Fremd:** 5 (war nie versendet)
> - **Duplikat:** 5 doppelt (physisch unmöglich → Betrug/Fehler)
>
> → klarer Soll/Ist-Abgleich der Seriennummern; das Bild-KI-Modul kann zusätzlich prüfen, ob das
> zurückgesendete Teil überhaupt das richtige Produkt und in welchem Zustand es ist.

**Nutzen:** lückenlose Rückverfolgbarkeit + Schutz gegen Retouren-Betrug — „die teure CPU, die rausging, ist auch die, die zurückkommt".

---

## 1b. Konkretisierung (2026-06-22): Lego-Defekterkennung

> [!success] Scope geklärt
> Die Produkte sind **Lego-Blöcke**. Das Modell soll **einfach** prüfen: **Ist der Block defekt?**
> Konkret: **Kratzer**, **fehlende/beschädigte Noppen**, Verschmutzung/Verformung, und **Seriennummer unlesbar**.
> Also primär **Defekt ja/nein + Art des Defekts** — keine komplexe Szenenanalyse nötig (gut für kleine, lokale Modelle).

### Datenquelle: Produktbilder (Referenzbilder)

> [!info] Wo die Bilder liegen
> Produktbilder liegen **in Odoo** im Feld `product.product.image_1920` (bzw. `image_256` …) — **nicht** als Dateien auf der Platte. Die PWA holt sie über den Backend-Endpoint `GET /api/products/{id}/image` (`backend/app/routers/pickings.py`).

**Export (2026-06-22):** 47 Produktbilder wurden aus Odoo (DB `masterfischer`) exportiert nach `_attachments/produktbilder/` — überwiegend Lego-Blöcke (`Brick 2x2 rot`, `Brick 2x4 W. Bows blau`, `Plate 2x4 grün`, `Roof Tile …`) plus einige Baumodelle. Diese dienen als **Referenz-Soll-Bilder** für den Identitätsabgleich.

> [!warning] Noch zu beschaffen
> Die Odoo-Bilder sind **saubere Katalog-Referenzen (Soll-Zustand)**. Für die **Defekt**-Erkennung brauchen wir zusätzlich **Ist-Fotos mit echten Mängeln** (Kratzer, fehlende Noppen) als Test-/Benchmark-Material — die müssen wir noch fotografieren/sammeln.

## 2. Einordnung in die bestehende Architektur

> [!info] Passt sauber auf die Invarianten
> - **Lokal (Invariante 6):** Ollama läuft als **eigener Container** im `picking-net` — kein Cloud-Zwang.
> - **n8n-getriggert (Invariante 3/4):** Die Bildanalyse ist **async** und läuft über n8n, **nicht** im Voice-Hot-Path.
> - **Odoo bleibt System of Record:** das Ergebnis wird über den bestehenden Backend-Callback-Pfad (`/internal/n8n/*`) nach Odoo geschrieben.

Im Architekturbild ([[02 - Architektur & Diagramm erklärt]]) ersetzt/ergänzt ein **lokaler `ollama`-Container** den heutigen externen `OpenAI`-Knoten. Datenfluss:

```
PWA (Foto) -> Backend -> n8n (Webhook) -> Ollama Vision (lokal) -> n8n -> Backend-Callback -> Odoo
```

---

## 3. Recherche: lokale Vision-Modelle (Stand Juni 2026)

Ollama läuft **ab 8 GB RAM, GPU ist optional** (CPU funktioniert, nur langsamer). Auswahl nach RAM-Budget:

| Modell | Größe | RAM/VRAM ca. | Stärke | Eignung für uns |
| --- | --- | --- | --- | --- |
| **Moondream 2** | ~1.9B | **~2–4 GB** | sehr klein & schnell | Minimal-Setup, einfache Ja/Nein-Prüfung (beschädigt?) |
| **SmolVLM** | ~2B | **sparsamste** Memory-Nutzung | extrem token-effizient (81 Tokens/Bildpatch statt 16k) | Top-Kandidat für schwache Hardware |
| **Qwen2.5-VL 3B** | 3B | ~3–4 GB | Objekt-Lokalisierung, Dokumente | guter kleiner Allrounder (Identität + Defekt) |
| **LLaVA 1.6 7B / MiniCPM-V 4.5 8B** | 7–8B | ~6–8 GB | solides Bildverständnis | Laptop-Standard, mehr Genauigkeit |
| **Qwen2.5-VL 7B / Qwen3-VL 8B / Llama 3.2 Vision 11B** | 8–11B | ~8–16 GB | starkes OCR/Detailverständnis | wenn Genauigkeit/Label-Lesen wichtig |

> [!note] Wichtige Erkenntnisse
> - **Moondream 2** ist das kleinste praktisch nutzbare Modell (~2 GB), aber schwach bei komplexen Szenen.
> - **SmolVLM** hat die **beste Memory-Effizienz** der gängigen VLMs.
> - **Qwen2.5-VL 7B** schlägt in mehreren Benchmarks das größere **Llama 3.2 Vision 11B** (DocVQA 95.7, MMMU 58.6) — kleiner ≠ schlechter.
> - Empfehlung Start: **Qwen2.5-VL 3B** (Balance) oder **Moondream 2** (minimal) — beide klein genug, dass sie auch auf dem Prof-Rechner laufen sollten.

---

## 4. n8n-Anbindung

Zwei dokumentierte Wege (beide n8n-nativ):
1. **Ollama-Node** (LangChain-Sub-Node `lmollama`) — direkte Modell-Anbindung.
2. **HTTP-Request-Node** → POST an die lokale Ollama-API (`/api/generate` bzw. `/api/chat`) mit dem **Bild als base64-String** im JSON-Body.

Bewährtes Muster (es gibt fertige n8n-Templates, z. B. „Compare local Ollama Vision models"):
`Bild holen → in base64 wandeln → an Ollama-Modell(e) mit klarem Prompt senden → strukturierte (JSON/Markdown) Antwort zurück`.

---

## 5. Referenz-Bild-Abgleich — drei Ansätze

| Ansatz | Wie | Vor-/Nachteil |
| --- | --- | --- |
| **A) VLM Zero-Shot** | Prompt: „Ist das ein `rosa brick 2x2`? Beschädigt? Antworte JSON `{match, damaged, reason}`" | Einfach, keine Referenzbilder nötig; abhängig von Modellgüte |
| **B) Embedding-Ähnlichkeit** | Referenzordner pro Produkt; Bild-Embedding (z. B. CLIP) gegen Referenz vergleichen → Score | Robust für **Identität**; braucht Referenzbilder + Embedding-Pipeline |
| **C) Hybrid (empfohlen)** | VLM für Beschreibung/Defekt **+** Embedding-Match für Identität | Stärkste Aussage; mehr Aufwand |

Deine Idee mit dem **Referenzbild-Ordner** (Eingabe „rosa brick 2x2" → vergleicht mit hinterlegtem Referenzbild) ist genau Ansatz **B/C** — als „zusätzliche Stärkung" über das reine VLM hinaus.

---

## 6. Der Forschungsbeitrag: Benchmark-/Evaluierungs-Harness

Kern für die Bachelorarbeit (Design Science: Artefakt **messbar** machen). Der Befehl **„Evaluieren"** löst einen Messlauf aus.

**Zu messende Größen:**
- **RAM:** Peak-Verbrauch + Modell-Ladezeit
- **Latenz:** Zeit pro Bild (Inferenz)
- **Durchsatz:** Bilder pro Minute
- **Parallelität:** wie viele gleichzeitige Anfragen, bevor es einbricht → entspricht „**wie viele Mitarbeiter** können gleichzeitig arbeiten"
- **Genauigkeit:** korrekte Identität/Defekt vs. Ground-Truth (vorbereitete Bilder)
- **Robustheit:** Verhalten bei wechselndem Licht/Winkel/Unschärfe

**Portabilität (wichtig für den Prof-Rechner):**
Der Harness ist ein **reproduzierbares Skript** über einen festen Bildsatz und schreibt das **Ressourcenprofil** raus → derselbe Lauf auf einem anderen Rechner zeigt direkt, ob/wie gut es dort läuft. Mehrere Modelle (z. B. Moondream 2 vs. Qwen2.5-VL 3B vs. LLaVA 7B) auf **demselben** Bildsatz vergleichen → Tabelle.

> [!tip] Baut auf Bestehendem auf
> Knüpft direkt an die bereits geplante **bildbasierte Workflow-Prüfung** an (100–1000 Läufe, Latenz/Streuung messen) aus [[System Architektur]] / der Teststrategie.

---

## 7. Offene Fragen / nächste Schritte
- [x] **Was genau erkennen?** → Lego-Defekte: Kratzer, fehlende/beschädigte Noppen, Verschmutzung, Seriennummer unlesbar (Defekt ja/nein + Art).
- [x] **Referenz-Soll-Bilder** → 47 Produktbilder aus Odoo exportiert nach `_attachments/produktbilder/`.
- [ ] **Zielhardware**: läuft auf dem Demo-Laptop UND später auf dem Rechner des Profs (andere RAM/Leistung) → Harness muss portabel messen.
- [ ] **Ist-Fotos mit Defekten** sammeln/fotografieren (Benchmark-/Test-Bildsatz: gut / Kratzer / fehlende Noppe / falsches Produkt).
- [ ] Erstes Modell für den Prototyp festlegen (Vorschlag: **Qwen2.5-VL 3B** oder **Moondream 2**).
- [ ] Danach: konkreter Implementierungsplan (`writing-plans`).

## Quellen (Recherche)
- [Local Vision Models 2026 (LLaVA, Llama 3.2 Vision, Qwen3-VL, Ollama)](https://www.promptquorum.com/power-local-llm/local-vision-models-llava-ollama-2026)
- [SmolVLM – small yet mighty Vision Language Model (Hugging Face)](https://huggingface.co/blog/smolvlm)
- [Best Ollama Models for Vision (Serverman)](https://www.serverman.co.uk/ai/ollama/best-ollama-models-for-vision/)
- [Ollama System Requirements 2026](https://localaimaster.com/blog/ollama-system-requirements)
- [Automate Image Analysis with Local Ollama Vision Models in n8n](https://buldrr.com/workflows/automate-image-analysis-local-ollama-vision-models-n8n/)
- [n8n Template: Compare local Ollama Vision models for image analysis](https://n8n.io/workflows/3185-compare-local-ollama-vision-models-for-image-analysis-using-google-docs/)

## Verwandt
- [[Barcode als Seriennummer-Bestätigung]] · [[Karton- und Behaelter-Tracking (Put-to-Box)]] · [[07 - n8n]] · [[02 - Architektur & Diagramm erklärt]] · [[Future Functions]]
