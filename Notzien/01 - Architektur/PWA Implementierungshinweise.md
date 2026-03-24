---
title: PWA Implementierungshinweise
tags:
  - architecture
  - pwa
  - ios
  - mobile
aliases:
  - PWA Hinweise
  - iOS Safari Bugs
---

# PWA Implementierungshinweise

> [!abstract] Mobile Web-Besonderheiten
> iOS Safari und Android Chrome verhalten sich in PWA-Standalone-Mode anders als erwartet.
> Diese Note dokumentiert alle bekannten Probleme und die implementierten Workarounds.

Übergeordnete Architektur: [[System Architektur]] | Voice-Details: [[Voice Intent Engine]] | Überblick: [[00 - Projekt Übersicht]]

---

## iOS Safari: SpeechRecognition funktioniert nicht

> [!danger] WebKit Bug #215884
> `window.SpeechRecognition` (Web Speech API) funktioniert im PWA-Standalone-Mode auf iOS **nicht**.
> Auch im normalen Safari-Browser ist es unzuverlässig (Duplikate, Timeouts, stille Fehler).

**Symptom:** `SpeechRecognition.start()` läuft ohne Fehler, liefert aber nie Ergebnisse.

**Workaround (implementiert):**
- `MediaRecorder` nimmt Audio auf (funktioniert in iOS PWA)
- Audio-Blob wird an `POST /api/voice/recognize` gesendet
- FastAPI → Vosk (Server-Side STT)
- Kein Browser-seitiges STT

**Warum Vosk?** → Siehe [[Voice Intent Engine]]

---

## iOS Safari: Kamera-Permission bei Navigation

> [!warning] WebKit Bug
> iOS Safari widerruft die Kamera-Permission wenn die Seite navigiert (Hash-Change, pushState).
> Die App muss als echte SPA ohne Page Reloads gebaut sein.

**Symptom:** `getUserMedia()` wirft `NotAllowedError` nach Navigation innerhalb der App.

**Workaround (implementiert):**
- `app.js` nutzt kein `window.location.href =` oder `location.hash =` für Navigation
- Stattdessen: DOM-basiertes Routing — `main`-Element wird per JavaScript ausgetauscht
- Kamera-Stream wird in `camera.js` gecacht und nicht bei jedem Formular-Öffnen neu angefordert

---

## getUserMedia() — User-Geste erforderlich

> [!info] Browser-Sicherheitsregel (alle Browser)
> `navigator.mediaDevices.getUserMedia()` muss durch eine **direkte User-Geste** ausgelöst werden.
> Automatische Aufrufe beim Seitenload werden geblockt.

**Implementierung:**
```javascript
// ✅ Korrekt: in click/touchstart Handler
voiceBtn.addEventListener('pointerdown', async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    // ...
});

// ❌ Falsch: beim Seitenload
window.addEventListener('load', async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true }); // GEBLOCKT
});
```

---

## MediaRecorder: Audio-Formate

| Plattform | Format | MIME-Type | Vosk-kompatibel |
| --------- | ------ | --------- | --------------- |
| iOS Safari | MP4/AAC | `audio/mp4` | ✅ Ja |
| Android Chrome | WebM/Opus | `audio/webm;codecs=opus` | ✅ Ja |
| Desktop Chrome | WebM/Opus | `audio/webm;codecs=opus` | ✅ Ja |
| Desktop Firefox | WebM/Opus | `audio/webm` | ✅ Ja |

**Implementierung (voice.js):**
```javascript
const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : 'audio/mp4';
const recorder = new MediaRecorder(stream, { mimeType });
```

Das Backend-ffmpeg konvertiert falls nötig — aber Vosk akzeptiert beide Formate direkt.

---

## SpeechSynthesis (TTS) auf iOS

> [!info] iOS erfordert User-Geste für TTS
> `speechSynthesis.speak()` funktioniert auf iOS nur wenn es aus einer User-Geste heraus aufgerufen wird.
> Nach dem ersten Aufruf wird der Audio-Kontext "aufgeweckt" und funktioniert dann auch asynchron.

**Implementierung (voice.js):**
```javascript
// Beim ersten User-Tap: TTS initialisieren
document.addEventListener('touchstart', () => {
    const u = new SpeechSynthesisUtterance('');
    speechSynthesis.speak(u);
}, { once: true });
```

Nach dieser "Aufweck-Geste" können TTS-Aufrufe auch aus Callbacks kommen.

---

## HTTPS ist zwingend

> [!danger] Kein HTTP-Fallback
> Ohne HTTPS gibt es:
> - Kein `getUserMedia()` → kein Voice, keine Kamera
> - Kein `MediaRecorder`
> - Kein Service Worker → kein Offline-Cache, kein PWA-Install
> - Kein `navigator.share`

**Setup:** Caddy 2 + mkcert — Details im CLAUDE.md und in [[Phase 0 - Infrastruktur]]

**mkcert CA auf Mobile-Geräten installieren:**
- iOS: `.pem` per AirDrop → Profil installieren → Einstellungen → Allgemein → Info → Zertifikatsvertrauenseinstellungen → aktivieren
- Android: Einstellungen → Sicherheit → Zertifikat installieren → CA

---

## Service Worker & PWA-Installation

**Installierbar wenn:**
- HTTPS ✅
- `manifest.json` vorhanden ✅
- Service Worker registriert ✅
- Mind. ein Icon ≥192×192px ✅

**Offline-Strategie (sw.js):** Cache-First für statische Assets (CSS, JS, Icons), Network-First für API-Calls.

> [!tip] PWA-Install-Banner
> iOS zeigt keinen automatischen Install-Banner — Nutzer muss manuell "Zum Home-Bildschirm" wählen.
> Android Chrome zeigt den Banner nach dem 2. Besuch (nach 2 Tagen).
> Eigener In-App Install-Button über `beforeinstallprompt`-Event in `pwa.js` implementiert.

---

## HID-Barcode-Scanner

Bluetooth/USB-HID-Scanner emulieren eine Tastatur. Der Scan-Input kommt als schnelle Tastenfolge gefolgt von Enter.

**Erkennung (scanner.js):**
```javascript
let buffer = '';
let lastKeyTime = 0;

document.addEventListener('keydown', (e) => {
    const now = Date.now();
    if (now - lastKeyTime > 50) buffer = ''; // Neuer Scan-Start
    if (e.key === 'Enter' && buffer.length > 3) {
        handleScan(buffer);
        buffer = '';
    } else if (e.key.length === 1) {
        buffer += e.key;
    }
    lastKeyTime = now;
});
```

---

## Weiterführend

- [[Voice Intent Engine]] — STT-Pipeline, Vosk-Details, Intent-Erkennung
- [[System Architektur]] — Gesamtarchitektur und HTTPS-Pflicht
- [[Phase 0 - Infrastruktur]] — mkcert-Setup, HTTPS einrichten
- [[Phase 2 - Backend und PWA Shell]] — PWA-Tests auf iOS/Android
