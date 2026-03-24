---
title: Phase 3 - Barcode Scanning
tags:
  - phase
  - scanning
  - barcode
status: pending
---

# Phase 3 — Barcode Scanning

> [!todo] Wartet auf Phase 2
> HID-Scanner und Touch-Fallback vollständig integrieren und auf realen Geräten testen.
> **Voraussetzung:** [[Phase 2 - Backend und PWA Shell]] ✅ abgeschlossen.

Überblick: [[00 - Projekt Übersicht]] | Scan-Logik: [[API Dokumentation]] | PWA-Details: [[PWA Implementierungshinweise]] | Nächste Phase: [[Phase 4 - Voice Picking]]

---

## Was in dieser Phase implementiert / getestet wird

Der Scan-Flow ist bereits im Backend (`routers/scan.py`) und in der PWA (`pwa/js/scanner.js`, `pwa/js/app.js`) implementiert. Diese Phase verifiziert die End-to-End-Korrektheit mit realer Hardware.

### Scan-Strategien (Priorität)

| Strategie | Implementierung | Verfügbarkeit |
| --------- | --------------- | ------------- |
| Bluetooth-HID-Scanner | `scanner.js:initHIDScanner()` | Alle Browser |
| `BarcodeDetector` API | `scanner.js:isBarcodeDetectorAvailable()` | Chrome Android ≥83 |
| Touch/Manuelle Eingabe | `scanner.js:showManualInput()` | Immer (Fallback) |

---

## Implementierungsdetails (Referenz)

### HID-Scanner-Erkennung (`pwa/js/scanner.js`)

```javascript
// HID-Scanner sendet Zeichen mit <50ms Abstand
// Menschliches Tippen ist langsamer → unterscheidbar
let buffer = '';
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && buffer.length >= 4) {
        handleScan(buffer.trim()); buffer = '';
    } else if (e.key.length === 1) {
        buffer += e.key;
        setTimeout(() => { buffer = ''; }, 300); // Reset nach 300ms
    }
});
```

### Backend Scan-Validierung (`routers/scan.py`)

```bash
POST /api/scan/validate?barcode=4006381333931&expected_barcode=4006381333931
# → {"match": true, "barcode": "4006381333931"}

POST /api/scan/validate?barcode=9999999999999&expected_barcode=4006381333931
# → {"match": false, "barcode": "9999999999999"}
```

### Pick-Zeile bestätigen (`routers/pickings.py`)

```bash
POST /api/pickings/1/confirm-line?move_line_id=1&scanned_barcode=4006381333931&quantity=5
# → {"success": true, "message": "Bestätigt.", "picking_complete": false}
```

---

## Test-Szenarien

### HID-Scanner Tests

```bash
# Manuelle Simulation: Sehr schnell tippen → sollte als Scan erkannt werden
# Normales Tippen → sollte als manuelle Eingabe erkannt werden
```

| Szenario | Erwartetes Verhalten |
| -------- | -------------------- |
| Richtiger Barcode scannen | ✅ Grüne Bestätigung + TTS "Bestätigt" |
| Falscher Artikel scannen | ❌ Rote Fehlermeldung + TTS "Falscher Artikel" |
| Letzter Pick einer Bestellung | ✅ "Auftrag abgeschlossen" |
| Produkt ohne Barcode | ⚠️ Touch-Fallback erscheint |
| Scanner nicht verbunden | ⚠️ Manuelle Eingabe aktiviert |

### Touch-Fallback Tests

- [ ] Manuelle Eingabe erscheint bei fehlender Barcode-Eingabe
- [ ] Numerische Tastatur öffnet sich auf Mobile
- [ ] Eingabe per Enter-Taste bestätigen
- [ ] Eingabe per Button bestätigen

---

## PWA-Tests auf Mobile

### iOS Safari

- [ ] HID-Scanner via Bluetooth: Zeichen kommen als `keydown`-Events an
- [ ] Scan wird korrekt abgetrennt (Enter-Key)
- [ ] Touch-Fallback Input öffnet numerische Tastatur (`inputmode="numeric"`)
- [ ] Barcode-Mismatch → roter Toast + TTS-Fehler
- [ ] Richtiger Scan → grüner Toast + TTS-Bestätigung

### Android Chrome

- [ ] HID-Scanner via Bluetooth: gleiche Tests wie iOS
- [ ] BarcodeDetector API verfügbar? → `typeof BarcodeDetector !== 'undefined'`
- [ ] Touch-Fallback funktioniert identisch

---

## EAN-13 Validierung (`utils/barcode.py`)

Das Backend validiert EAN-13-Prüfziffern:

```python
validate_ean13("4006381333931")  # → True
validate_ean13("4006381333930")  # → False (falsche Prüfziffer)
```

> [!info] Test-Barcodes
> Aus `seed-odoo.py`:
> - `4006381333931` — Schraube M8x40
> - `4006381333948` — Mutter M8 DIN934
> - `4006381333955` — Unterlegscheibe M8
> - `5901234123457` — Winkel 40x40
> - `7622210100528` — Gewindestange M8

---

## Bekannte Fallstricke

> [!warning] HID-Scanner + Focus
> HID-Scanner-Events werden nur empfangen, wenn das Dokument den Focus hat.
> Bei Modals oder Overlays kann der Focus verloren gehen.
> Fix: `document.addEventListener` statt `element.addEventListener`.

> [!warning] iOS Bluetooth-HID
> iOS sendet HID-Scanner-Events nur wenn der Cursor nicht in einem `<input>` ist
> und der Scanner als "keyboard" verbunden ist.
> Falls der Scanner nicht reagiert: Cursor aus Input-Feldern heraus tippen.

> [!warning] Barcode-Länge
> Min. 4 Zeichen für Scanner-Erkennung (`MIN_BARCODE_LENGTH = 4`).
> EAN-13 = 13 Zeichen, EAN-8 = 8 Zeichen, Code-128 variabel.

---

## Go/No-Go Checkliste

| Kriterium | Status |
| --------- | ------ |
| HID-Scanner: Scan wird in PWA erkannt | ☐ |
| Richtiger Barcode → `{"success": true}` | ☐ |
| Falscher Barcode → Fehlermeldung | ☐ |
| Letzter Pick → `{"picking_complete": true}` | ☐ |
| Touch-Fallback: Manuelle Eingabe funktioniert | ☐ |
| iOS + Android getestet | ☐ |

---

## Weiterführend

- [[API Dokumentation]] — `/api/scan/validate` und `/api/pickings/{id}/confirm-line`
- [[PWA Implementierungshinweise]] — iOS/Android HID-Scanner-Besonderheiten
- [[Phase 4 - Voice Picking]] — Voice-Picking als Enhancement zum Scan
- [[Phase 2 - Backend und PWA Shell]] — Voraussetzungen
