# Voice Latency + Commands v1 Design

## Ziel

Der normale Voice-Hot-Path bleibt lokal und deterministisch:

PWA Audio -> FastAPI `/api/voice/recognize` -> Whisper -> lokale Intent Engine -> PWA-Aktion.

Keine Standardkommandos duerfen ueber n8n oder einen LLM-Pfad laufen. v1 reduziert wahrgenommene Wartezeit und macht die Kommandos fuer Auftrag, Paket und Karton eindeutiger.

## Scope

1. Kurze Systemantworten sollen nicht erst Piper anfragen. Texte wie `Fertig.` oder `Abgebrochen.` nutzen sofort Browser-TTS.
2. Der Post-TTS-Cooldown wird auf einen kuerzeren, getesteten Wert gesetzt, damit der naechste Aufnahmezyklus schneller startet.
3. `done` darf nicht feuern, solange noch eine aktive Pick-Zeile sichtbar ist.
4. `confirm_all` wird kontextuell enger: nur Detail-Ansicht mit aktiver Zeile.
5. Neue/erweiterte Sprachformen:
   - `naechster Auftrag` -> `next_order`
   - `Auftrag erledigt`, `Auftrag fertig`, `komplett` -> `confirm_all` nur im sicheren Detail-Kontext
   - `Paket erledigt`, `Karton erledigt`, `Position erledigt`, `Artikel erledigt` -> `confirm`

## Nicht-Scope

- Kein LLM/NLP-Layer im Hot-Path.
- Keine Odoo-Schattenlogik im Frontend.
- Kein optimistisches fachliches Abhaken vor Backend-Erfolg.
- Kein n8n-Umbau in v1; der n8n-Folgeprozess bleibt als separater naechster Optimierungsschritt.

## Tests

- Backend: Intent Engine testet neue Phrasen und Kontextblockaden.
- Backend: Voice Route testet, dass `done` mit aktiver letzter Zeile blockiert bleibt.
- PWA Unit: Voice Helper testet kuerzeren Cooldown und Piper-Bypass fuer kurze Systemantworten.
- Regression: `npm run test:voice` und gezielte `pytest`-Suites.
