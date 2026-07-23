# Baustellen-Analyse — Mobile Picking Assistant

**Datum:** 2026-07-23 · **HEAD:** 45bad50 · **Methodik:** 9 parallele Analyse-Agenten (8 Bereiche + Completeness-Critic), Code live gelesen, Testsuiten live ausgeführt, Intent-Engine live geprobt. Rohdaten mit allen Details: `2026-07-23-baustellen-analyse.data.json`.

## Gesamtbild

Kern (Picking, Cluster, Serial-Validierung, PWA) solider als erwartet — Backend 220/220 Tests grün, Node 21/21 + 34/34 grün, Playwright 28/30. Echte Baustellen: **Voice** (2 kritische Bugs, Fehlerkennungen schreiben echte Odoo-Daten), **Vision-LLM** (Text-Pipeline fertig, Vision-Teil existiert nicht), **Versandlabel** (bei null), **Netzwerk/Auth** (Remote unmöglich, keine echte Authentifizierung), **Querschnitt** (keine CI, kein Backup).

Severity-Legende: 💀 kritisch · 🔴 hoch · 🟡 mittel · ⚪ niedrig

---

## 1. Odoo 19 Upgrade — funktioniert-mit-lücken

**Stand:** Live-Instanz Odoo 18.0 Community (DB `masterfischer`, Addons `./odoo/addons18`). **Odoo-19-Trial läuft bereits** (`odoo19-trial`, DB `masterfischer_o19_trial`, 19er-Addon-Baum `./odoo/addons` mit 19.0.x-Manifesten und `res.groups.privilege`-Security). Integration bewusst versionsportabel: nur JSON-RPC durch eine einzige `execute_kw`-Fassade (`odoo_client.py`, 107 Zeilen, ~60 Callsites), 17+-Feldnamen (`quantity` statt `qty_done`), Package-Modell-Laufzeit-Detection `stock.package` (19) vs `stock.quant.package` (18). Instanz-Umschaltung per `X-Odoo-Instance`-Header. n8n greift nie direkt auf Odoo zu.

| Lücke | Sev | Aufwand |
|---|---|---|
| Kein Migrationspfad Produktiv-DB 18→19. Community = kein Upgrade-Service. Optionen: OpenUpgrade oder Reseed via `seed-odoo.py` (Historie weg). | 🔴 | mehrere Tage |
| JSON-RPC/XML-RPC in 19 deprecated (JSON-2 Nachfolger). Läuft noch; Umbau lokal begrenzt (eine Fassade). | 🟡 | Tag |
| Doppelter Addon-Baum `addons/` vs `addons18/` driftet ohne CI-Check. `picking_assistant_context` = leeres Skelett. | 🟡 | Stunden |
| `button_validate`-Rückgabe ungeprüft (`picking_service.py:895-903`) — Wizard-Dict würde fälschlich als Abschluss gelten. Cluster macht es korrekt. `skip_immediate` seit 17 obsolet. | 🟡 | Stunden |
| `_sql_constraints`-Stil in 19 deprecated (`picking_assistant.py:274-280`). | ⚪ | Stunden |
| 19er-Gates hartkodiert auf Trial-DB (`config.py:61-62`, dbfilter in `odoo.conf`). | ⚪ | Stunden |

## 2. Cluster Picking — funktioniert-mit-lücken

**Stand:** Kern vollständig und sauber: `cluster_service.py` (970 Zeilen, 0 TODOs) mit echten `stock.picking.batch`-Objekten, Zonen-Vorschlägen, Package-Zuordnung, Karton-Pflichtbestätigung, Serial-Validierung, Kompensation, Telemetrie. 65 Backend-Tests + 6 E2E-Specs grün. Happy Path E2E nachgewiesen. **Fazit: vernünftig für Happy Path, für Realbetrieb fehlen Abbruch/Resume/Fehlmengen.**

| Lücke | Sev | Aufwand |
|---|---|---|
| Kein Abbruch-Pfad: Rundgang verlassen → Batch hängt für immer `in_progress`, Pickings blockiert. Nur 5 Endpoints, kein cancel. | 🔴 | Tag |
| Kein Resume: Reload → Batch unerreichbar. `loadBatch()` existiert (`app.js:3294`), kein UI-Einstieg, kein localStorage-Persist. | 🔴 | Tag |
| Batch-Pickings bleiben in Einzelliste sichtbar (`get_open_pickings` filtert `batch_id` nicht) → Doppel-Pick-Konflikt. | 🔴 | Stunden |
| Serial-Position Menge >1 = Sackgasse: Odoo splittet in 1-Stück-Lines, PWA sendet aber `quantity_demand`=N, Validator lehnt ab → Batch nie abschließbar. | 🔴 | Stunden |
| Kein Fehlmengen-/Skip-Pfad im Rundgang; leeres Fach = kein legaler Ausweg. | 🟡 | mehrere Tage |
| `validate_batch` prüft serverseitig nicht, ob alles gepickt (Gate nur im Frontend); `skip_backorder` verwirft Restmengen. | 🟡 | Stunden |
| Zone mit >8 Aufträgen liefert gar keinen Vorschlag statt getrimmtem. | ⚪ | Stunden |
| `create_batch` verkleinert Auswahl stillschweigend; Kompensation räumt CLUSTER-Packages nicht auf. | ⚪ | Stunden |

## 3. Voice Agents — funktioniert-mit-lücken (schlechtester Bereich, live verifiziert)

**Stand:** Pipeline durchgängig lokal: RMS-Sprachdetektion → ffmpeg → Whisper small (dt.) → Intent-Engine (Exact→Regex→Levenshtein→Partial, 761 Zeilen) → Piper/Browser-TTS. Recovery-Dialog nur im Band [0.68, 0.73).

| Lücke | Sev | Aufwand |
|---|---|---|
| Negation kaputt: „nicht ok" → confirm 0.95, „nicht gut" → confirm 0.95 (Negationsliste kennt nur stimmt/richtig/passt). Regex vergibt pauschal 0.95. Live verifiziert. | 💀 | Stunden |
| Voice-confirm **simuliert Barcode-Scan** (`app.js:2508-2509`) ohne Pflicht-Read-back → eine Fehlerkennung = echter Odoo-Write. `confirm_all` bucht alles. | 💀 | Tag |
| Whisper-Halluzinationen ungefiltert (`no_speech_prob` verworfen); kein initial_prompt mit Domänenvokabular. | 🔴 | Stunden |
| STT-Ausfall stumm: Whisper down → leeres Transkript → kommentarlos gedroppt. Kein Toast, keine Ansage. | 🔴 | Stunden |
| Toter Schwellenbereich [0.73, 0.78): Backend-Recovery endet bei 0.73, Frontend akzeptiert ab 0.78. Nie abgestimmt. | 🔴 | Stunden |
| n8n „AI Synthesize" ist **kein LLM** — if/else-Template, Canned-Antworten. Ollama läuft, wird für Voice nie gerufen. Größter Qualitätshebel. | 🔴 | mehrere Tage |
| Sprach-Mengeneingabe/Check-Digit = toter Code (Kontexte nie gesendet); GERMAN_NUMBERS nur 0–12. Pick-by-Voice-Kernfunktion fehlt. | 🟡 | Tag |
| Echo-Filter verwirft legitime Antworten; Pending-Confirm ohne TTL (spätes beiläufiges „ja gut" führt Aktion aus). | 🟡 | Stunden |
| Englische Aliasse verschmutzen deutsches Matching („eine" → „fine" → confirm 0.75). Live verifiziert. | 🟡 | Stunden |
| Piper nach einem einzigen Fehler permanent aus (bis Reload); 2 inkonsistente Stimmen (≤24 Zeichen = Browser-TTS). | 🟡 | Stunden |
| Latenzkette sequentiell, keine Voice-Metriken persistiert (Accuracy, p95). | 🟡 | Tag |
| ffmpeg-Fallback sendet webm als „audio/wav" mit encode=false → garantiert leer. | ⚪ | Stunden |
| Doppelt gepflegte Phrasenlisten (ALIASES + REGEX, ~200 Phrasen) mit Drift; RMS-Schwelle 18 fix. | ⚪ | Tag |

## 4. Seriennummern — funktioniert-mit-lücken (effektiv ja, effizient nein)

**Stand:** Validierung vorbildlich (`serial_validation.py`): Existenz, Produktbindung, Mehrdeutigkeit, Reservierungs-Match, Bestand am Platz, Menge==1 bei serial. In beiden Flows eingebunden. Retouren-Reconcile-API existiert. Tests auf 3 Ebenen.

| Lücke | Sev | Aufwand |
|---|---|---|
| Keine Voice-Integration: „bestätigen" auf Serial-Position → lautloses Pflicht-Modal, hands-free endet bei teuren Artikeln. | 🔴 | mehrere Tage |
| Erwartete/reservierte Serial wird nie angezeigt — Picker rät. Feld liegt schon im Detail-Payload, Cluster liefert `lot_id` gar nicht aus. Fix billig. | 🔴 | Stunden |
| Kein Serial-Tausch (reserviert A, greifbar B) — Sackgasse, Supervisor nötig. Odoo Barcode kann es. | 🟡 | Tag |
| 2 Scans pro Position (erst Produkt, dann Serial); Serial-Direktscan schlägt fehl. | 🟡 | Tag |
| Doppelte Serial über mehrere unreservierte Lines unerkannt (Quant ändert sich erst bei validate). | 🟡 | Tag |
| Serial-Line Menge >1 ohne Split-Flow = Sackgasse (auch Einzel-Flow). | 🟡 | Tag |
| Kein Kamera-Scan im Serial-Modal (nur Text-Input/HID). | 🟡 | Stunden |
| Retouren-Reconcile ohne UI und ohne Folgeprozess (kein Alert/Event bei Abweichung). | ⚪ | Tag |
| HID-Fokus-Fragilität: Fokusverlust im Modal → Scan landet im globalen Handler → „Falscher Barcode". | ⚪ | Stunden |

## 5. PWA Design — funktioniert-mit-lücken (**ja, geht vernünftig auf dem Handy**)

**Stand:** Mobile-first bestätigt: 48px-Touch-Token, 64px-Confirm-Buttons, safe-area-insets, 100dvh, Portrait-Lock, Lagerplatzcode clamp bis 3rem, High-Contrast-Modus, Pixel-7-Playwright-Default, axe-A11y (WCAG 2.1 AA), Visual-Regression, 320px-Kleinstgeräte-Test.

| Lücke | Sev | Aufwand |
|---|---|---|
| Offline nur App-Shell: kein Auftrags-Cache, keine Write-Queue (Idempotency-Keys existieren schon). WLAN-Funkloch = Flow tot. | 🔴 | mehrere Tage |
| Dark Mode toter Code: komplettes Theme in CSS, kein JS setzt `data-theme`, kein Toggle. Manifest dunkel vs index.html hell. 90% fertig. | 🟡 | Stunden |
| Install-Stub (`showInstallButton` = console.log), kein apple-touch-icon, keine maskable-Icons. | 🟡 | Stunden |
| Confirm-Button nicht in Daumenzone (Scrollfluss statt Sticky-Bottom; Muster existiert im Code bereits). | 🟡 | Tag |
| Kein `touch-action: manipulation` → Double-Tap-Zoom-Risiko bei schnellem Serien-Tippen (iOS). | 🟡 | Stunden |
| Null iOS/WebKit-E2E (backdrop-filter, MediaRecorder, BarcodeDetector weichen ab). | 🟡 | Tag |
| SW/Offline null Testabdeckung (`serviceWorkers: 'block'` in Playwright); Precache-Liste manuell. | 🟡 | Tag |
| Outfit-Font geladen+gecacht, nie verwendet. | ⚪ | Stunden |
| Einzelne Targets <48px (back 40px, Chips 38px); Meta-Labels ~10px. | ⚪ | Stunden |
| CSS-Akkretion: 3836 Zeilen, tote Blöcke, doppelte Definitionen, Override-Schichten mit !important. | ⚪ | Tag |

## 6. Netzwerk/Deployment — funktioniert-mit-lücken (heute nur gleiches LAN)

**Stand:** Caddy TLS-Proxy (mkcert), `/api`→Backend, Rest→PWA-Caddy. Phone erreicht PWA nur im LAN/Hotspot (`LAN_HOST=172.20.10.2`). Secure-Context für getUserMedia gelöst, aber Root-CA manuell pro Gerät. PWA host-agnostisch (`API_BASE='/api'`). Whisper/Piper/Ollama sauber ohne Host-Ports.

| Lücke | Sev | Aufwand |
|---|---|---|
| **Keine echte Auth** — Identität = selbstbehauptete Header `X-Picker-User-Id`/`X-Device-Id`. Vor jeder Remote-Exposition zwingend Token-Auth oder Access-Layer. | 💀 | mehrere Tage |
| Zertifikat an eine LAN-IP gekettet (172.20.10.2) — Netzwechsel bricht HTTPS → Voice/Scanner tot. Reparatur jedes Mal manuell. | 🔴 | Stunden |
| Odoo (8069) + n8n (5678) unverschlüsselt auf allen Interfaces; Caddy leitet `/odoo` per 308 aktiv aus TLS raus. Fix: 127.0.0.1-Bind + hinter Caddy proxien. | 🔴 | Stunden |
| Cloudflare-Tunnel halb angelegt: Token in .env, kein cloudflared-Service, `WEBHOOK_URL` hartkodiert überschrieben. **Empfehlung: Tailscale** (MagicDNS + `tailscale cert` ersetzt mkcert komplett) oder cloudflared + Cloudflare Access. | 🔴 | Tag |
| Root-CA-Rollout pro Gerät skaliert nicht (häufigster Support-Fall). Echte Domain eliminiert das. | 🟡 | Tag |
| Voice remote fragil: Piper 5s-Timeout beidseitig + permanentes Disable nach einem Fehler; n8n-Sync degradiert bei WAN-Latenz. | 🟡 | Tag |
| Live-Cloudflare-Tokens im Klartext in .env (Desktop-Sync-Pfad) — vor Tunnel-Upgrade rotieren. | 🟡 | Stunden |
| CORS auf genau eine Origin fixiert. | ⚪ | Stunden |

## 7. n8n Versandlabel — kaum-vorhanden

**Stand:** Kein Label-Workflow, auch nicht partiell. `pick-confirmed.json`/`batch-confirmed.json` = Stubs (Log-String + „received"). Kein separater Pack-Schritt — Abschluss = letzte Line picked → `button_validate` → Event. Bausteine vorhanden: Versandadresse+Carrier lädt Backend bereits (`_apply_shipping_context`), sendet sie nur nicht mit; Callback-Muster mit Idempotenz+Secret kopierbar (`n8n_internal.py`); n8n-Binary-Storage gemountet. Spec §5.6 (`2026-07-23-parallel-modernization-program-design.md`) + Event-Contracts (`shipment.parcel.ready.v1`, `shipping.label.status.v1`) definiert, nichts implementiert.

| Lücke | Sev | Aufwand |
|---|---|---|
| Kein Shipping-Label-Workflow in n8n. | 💀 | mehrere Tage |
| Kein Carrier-Adapter, keine PDF/ZPL-Erzeugung. Für Thesis: **PDF-Mock-Carrier** pragmatisch. | 💀 | mehrere Tage |
| `pick-confirmed`-Payload zu dünn (nur picking_id + completed_by) — Adresse/Carrier fehlen. | 🔴 | Stunden |
| Kein Callback-Endpoint für Label-Status (`n8n_shipping.py` nur geplant). | 🔴 | Tag |
| Keine Label-Ablage (`ir.attachment`) / `carrier_tracking_ref` in Odoo; Addon `picking_assistant_shipping` fehlt. | 🔴 | Tag |
| Events fire-and-forget ohne Retry/Outbox — validiertes Picking, verlorenes Label-Event. | 🔴 | mehrere Tage |
| Kein Druck-Pfad (Minimal: PDF-URL in PWA + window.print; executeCommand in n8n geblockt). | 🟡 | Tag |
| `batch-confirmed` ohne Picking-Auflösung und ohne Path-Override. | ⚪ | Stunden |

## 8. Vision-LLM Qualitätsprüfung — halb-fertig (Vision-Teil = 0)

**Stand:** Text-Pipeline fertig und E2E-verifiziert (QA/0154, `ai_provider=ollama-local`): PWA-Multi-Foto-Upload → Idempotenz+Fingerprint → Odoo `ir.attachment` → n8n-Heuristik + Ollama qwen2.5:7b Disposition → Write-back mit Chatter-Note → Shadow-Eval-Infrastruktur backend-seitig komplett. **Aber kein Codepfad übergibt je Bilder an ein LLM** — Prompt sagt wörtlich „Es stehen keine Bildinhalte zur Verfügung", `ai_photo_analysis` hart null. Moondream/qwen2.5vl-Experimente (2026-07-08) nirgends im Repo persistiert.

| Lücke | Sev | Aufwand |
|---|---|---|
| Vision-Pfad existiert nicht: Attachment-Fetch aus Odoo (base64) → Ollama `images`-Parameter → `ai_photo_analysis`-Befüllung → n8n-Wiring. | 💀 | mehrere Tage |
| Vision-Modellwahl ungeklärt (qwen2.5vl:3b vs moondream vs minicpm-v, CPU-only). Als ADR dokumentieren + `LLM_VISION_MODEL`-Setting. | 🔴 | Tag |
| **Timeout-Bug: n8n-Node 35s vs Backend 90s** — LLM-Antworten still verworfen, Heuristik gewinnt fälschlich. Node auf ≥95s + Workflow neu importieren. Sofortwirkung. | 🔴 | Stunden |
| Shadow-Eval-Workflow verwaist (kein executeWorkflow-Aufrufer, läuft nie) + ruft OpenAI auf (kein Internet am Lab-PC). | 🔴 | Tag |
| Human-in-the-loop unvollständig: kein Override in Odoo, kein Konfidenz-Schwellwert, Picker sieht Ergebnis nie (nur Pending-Banner). | 🟡 | Tag |
| `ai_enhanced_description`-Kontrakt unerfüllt (nur charAt(0).toUpperCase()). | 🟡 | Stunden |
| Toter Live-Kamera-Code (`camera.js`: startCamera/capturePhoto ungenutzt). | ⚪ | Stunden |

## 9. Querschnitt (Completeness-Critic, live verifiziert)

**Stand:** Backend-pytest 220/220 grün (2,8s), Node 21/21 + 34/34 grün, Playwright 28/30. Idempotenz-Store korrekt in Odoo (keine Schatten-DB). QA rein lokal über Makefile.

| Lücke | Sev | Aufwand |
|---|---|---|
| Keine CI-Pipeline — E2E am HEAD rot, ohne dass es auffiel. pytest+Node als Gate = billigster Schutz. | 🔴 | Stunden |
| Kein Backup/Restore für pg_data/odoo_data/n8n_data — Docker-Reset = Thesis-DB + Fotos unwiederbringlich weg. Auch Basis für 18→19-Migration. | 🔴 | Stunden |
| E2E-Flakes: `pickings.spec.js:52` Race unter 2 Workern; `visual.spec.js` Schwelle zu strikt; `python` statt `python3` im webServer bricht Suite auf Standard-WSL. | 🟡 | Stunden |
| Unbegrenzte Uploads: Fotos/Audio komplett in RAM, base64 +33%, ein JSON-RPC-Call — OOM-Risiko. Kein Limit in Caddy/Config. | 🟡 | Stunden |
| Docker ungehärtet: `uvicorn --reload` dauerhaft, whisper/ollama `:latest` ungepinnt (Evaluation nicht reproduzierbar), Limits nur n8n, Healthchecks nur db+n8n. | 🟡 | Tag |

---

## Priorisierter Angriffsplan

| # | Track | Inhalt | Aufwand |
|---|---|---|---|
| **0** | Fundament | Backup-Skript (pg_dump+Filestore+n8n), CI-Gate (pytest+Node), E2E-Fixes (Race, python3, Pixel-Schwelle) | halber Tag |
| **1** | Voice-Sicherheit | Negation, Pflicht-Read-back für schreibende Intents, Halluzinationsfilter (no_speech_prob), Schwellen-Abgleich, STT-Ausfall-Feedback, englische Aliasse raus | Stunden–1 Tag |
| **2** | VLLM-Vision | Timeout-Fix (sofort), dann Vision-Pfad: Attachment-Fetch → Ollama images → Modell-ADR → Write-back → Picker-Anzeige | Stunden + mehrere Tage |
| **3** | Versandlabel | Payload erweitern, n8n-Workflow mit PDF-Mock-Carrier, Callback-Endpoint, ir.attachment+Tracking-Ref, PWA-Anzeige | 2–3 Tage |
| **4** | Cluster-Härtung | Abbruch-Endpoint, Resume (localStorage+Banner), batch_id-Filter in Einzelliste, Serial-qty-Fix | 1–2 Tage |
| **5** | Serial-UX | Erwartete Serial anzeigen, Kamera im Modal, HID-Fokus-Fix | Stunden |
| **6** | Odoo 19 | Reseed-Entscheid, Compose-Umbau, Addon-Baum-Konsolidierung, button_validate-Fix | mehrere Tage |
| **7** | Netzwerk | Tailscale (Empfehlung) + Token-Auth, Odoo/n8n hinter TLS, Tokens rotieren | 1–2 Tage |
| **8** | PWA-Feinschliff | Dark-Mode-Toggle, Offline-Queue, Install/iOS, Daumenzone | verteilt |

**Parallelisierbar:** Tracks 0, 1, 4, 5 unabhängig. Tracks 2+3 teilen n8n + `n8n_internal.py` — nacheinander oder koordiniert.

## Status / Nächster Schritt

- [x] Analyse abgeschlossen (2026-07-23)
- [ ] **Morgen: User wählt Startreihenfolge** (Empfehlung: Track 0 zuerst, dann 1+4+5 parallel per Subagenten, danach 2 → 3)
