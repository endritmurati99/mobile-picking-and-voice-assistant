---
title: PWA & Voice-Pfad
tags:
  - pwa
  - voice
  - frontend
  - service-worker
  - whisper
  - piper
  - barcode
  - https
  - bachelorarbeit
created: 2026-06-22
---

# PWA & Voice-Pfad

> [!info] Worum geht es hier?
> Diese Notiz beschreibt die **Frontend-Hälfte** des Picking-Assistenten: die **PWA** (Progressive Web App). Eine PWA ist eine Webseite, die sich wie eine native App verhält – sie ist auf dem Smartphone **installierbar**, läuft im Vollbild und funktioniert dank **Service Worker** auch bei wackeligem Netz. Im Zentrum steht der **Voice-Pfad**: der komplette Weg von „Picker spricht ins Mikrofon" bis „App sagt etwas zurück". Schwesternotizen: [[05 - Backend (FastAPI)]] (Gegenstück auf Serverseite), [[02 - Architektur & Diagramm erklärt]], [[00 - Start Hier (Übersichtskarte)]].

---

## 1. Was ist die PWA – in einem Satz

Die PWA ist eine **Vanilla-JavaScript-Applikation ohne Framework** (kein React, kein Vue), mobile-first gebaut, installierbar und offline-fähig via Service Worker. Sie spricht **ausschließlich mit dem Backend unter `/api`** – niemals direkt mit Odoo oder n8n.

> [!note] „Vanilla JS" – warum kein Framework?
> „Vanilla" bedeutet: pures JavaScript, das der Browser nativ versteht, ohne zusätzliche Bibliothek. Vorteil für eine Bachelorarbeit: weniger Abhängigkeiten, kleinere Auslieferung, jeder Code-Pfad ist nachvollziehbar. Die Haupt-Logikdatei `js/app.js` umfasst rund 2960 Zeilen.

**Projektverzeichnis (relativ):**
`Mobile Picking und Voice Assistant/pwa/`

---

## 2. Verzeichnisstruktur der PWA

```
pwa/
├── index.html                  # HTML-Einstiegspunkt (App-Shell)
├── manifest.json               # PWA-Manifest (macht App installierbar)
├── sw.js                       # Service Worker (Offline-Caching)
├── css/
│   └── app.css                 # Styling, mobile-first, High-Contrast
├── fonts/                      # Variable WOFF2-Fonts (Outfit, Jakarta, JetBrains Mono)
├── icons/
│   ├── icon-192.png            # PWA-Icon 192×192
│   └── icon-512.png            # PWA-Icon 512×512
└── js/
    ├── app.js                  # Haupt-App-Logik (~2960 Zeilen)
    ├── api.js                  # Backend-API-Client (HTTP-Bridge zu /api)
    ├── voice.js                # Voice-Modul: TTS + STT + Interlock
    ├── voice-helpers.mjs       # Voice-State-Management (State-Machine, Echo-Check)
    ├── voice-runtime.mjs       # Voice-Intent-Klassifikation (clientseitig)
    ├── scanner.js              # Barcode-Scanning (HID + BarcodeDetector API)
    ├── camera.js               # Kamera-Capture für Quality Alerts
    ├── pwa.js                  # PWA-Lifecycle (Service Worker, Installation)
    ├── ui.js                   # UI-State und Rendering-Hilfen
    ├── feedback.js             # Haptik + Akustik (Web Audio API)
    └── tests/
        ├── api.test.mjs
        ├── voice-helpers.test.mjs
        └── voice-runtime.test.mjs
```

> [!note] `.mjs` vs. `.js`
> Die Endung `.mjs` markiert ein **ES-Modul** (modernes JavaScript mit `import`/`export`). Diese Dateien sind reine, testbare Logik-Module ohne Browser-Abhängigkeit – deshalb existieren dafür eigene Unit-Tests (`js/tests/`).

---

## 3. Architektur-Grundregel: PWA spricht NUR mit `/api`

```
Frontend (index.html + js/)
         │
         ├─→ [API-Client] (api.js)
         │   └─→ HTTP POST/GET
         │       └─→ /api/...   (FastAPI-Endpunkte → siehe [[05 - Backend (FastAPI)]])
         │
         └─→ [Service Worker] (sw.js)
             └─→ Cache-Strategien (Shell cachen, /api NIEMALS cachen)
```

> [!important] Keine Direktzugriffe
> Die PWA kennt weder Odoo noch n8n. **Alles** läuft über FastAPI unter `/api`. Das ist die saubere Trennung, die in [[02 - Architektur & Diagramm erklärt]] beschrieben ist: Frontend ↔ Backend ↔ (Odoo, n8n).

---

## 4. PWA-Kern: Installierbarkeit, Manifest, Service Worker

### 4.1 Das Manifest – macht die App installierbar

**Datei:** `pwa/manifest.json`

```json
{
    "name": "LogILab Picking Assistant",
    "short_name": "Picking",
    "description": "Mobiler Picking-Assistent mit Voice und Qualitätserfassung",
    "start_url": "/",
    "display": "standalone",
    "orientation": "portrait",
    "theme_color": "#091014",
    "background_color": "#091014",
    "lang": "de",
    "icons": [
        { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
        { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png" }
    ]
}
```

- `display: "standalone"` → App läuft **ohne Browser-Chrome** (keine Adressleiste), wie eine native App.
- `start_url: "/"` → Beim Tippen auf das Home-Screen-Icon startet die App-Shell.
- `theme_color` / `background_color` → Farben für Header und Splash-Screen.

### 4.2 Service Worker – das Offline-Gehirn

**Datei:** `pwa/sw.js`, Cache-Name `picking-v11`.

Ein Service Worker ist ein **Skript, das zwischen App und Netzwerk sitzt** und jede Anfrage abfangen kann. Er ist die Voraussetzung dafür, dass eine Web-App offline funktioniert.

**Lifecycle:**

| Phase | Was passiert |
|-------|--------------|
| `install` | Alle Shell-Assets (HTML, CSS, JS, Icons, Fonts) werden **vorausgeladen** (PRECACHE) |
| `activate` | Alte Cache-Versionen löschen, `clients.claim()` übernimmt die Kontrolle |
| `fetch` | `shouldHandleRequest()` entscheidet pro Anfrage die Strategie |
| `message` | `SKIP_WAITING`-Signal von der App → neuer Worker wird sofort aktiv |

**Cache-Strategie (entscheidend):**

```javascript
const CACHE_NAME = 'picking-v11';
const PRECACHE = [
    '/', '/index.html', '/manifest.json',
    '/css/app.css', '/fonts/*', '/icons/*',
    '/js/app.js', '/js/api.js', '/js/voice.js', ...
];
// Navigation & Shell-Assets → Network-First mit Cache-Fallback
// /api/*                    → NICHT cachen (immer frisch vom Backend)
```

> [!warning] `/api/*` wird bewusst NICHT gecacht
> Picking-Daten, Lagerbestände und Voice-Antworten müssen **immer aktuell** sein. Würde man sie cachen, könnte ein Picker einen längst kommissionierten Auftrag erneut sehen. Deshalb gilt: Die **App-Shell** (Code, Layout) wird gecacht, die **Daten** nie.

### 4.3 Installierbarkeits-Kriterien (alle erfüllt)

- HTTPS (in Production) – siehe [Abschnitt 9](#9-https-pflicht-mikrofon-kamera-service-worker)
- Manifest mit Icons 192×192 und 512×512
- Service Worker mit `fetch`-Handler
- `display: "standalone"`
- Viewport-Meta-Tag im `<head>`

---

## 5. Der API-Client – die Brücke zum Backend

**Datei:** `pwa/js/api.js`. Alle Endpunkte liegen unter `/api`.

| Methode | Endpoint | Zweck |
|---------|----------|-------|
| GET | `/pickers` | Picker-Profil-Liste laden |
| GET | `/pickings` | Aktuelle Aufträge (nach Picker via Header gefiltert) |
| GET | `/pickings/{id}` | Detail eines Auftrags |
| POST | `/pickings/{id}/claim` | Auftrag reservieren (Heartbeat alle 30 s) |
| POST | `/pickings/{id}/heartbeat` | Claim auffrischen (verhindert Timeout) |
| POST | `/pickings/{id}/release` | Auftrag freigeben |
| POST | `/pickings/{id}/confirm-line` | Position bestätigen (mit Barcode) |
| GET | `/pickings/{id}/stock?product_id=X&location_id=Y` | Verfügbarkeit prüfen |
| POST | `/pickings/{id}/replenishment-request` | Nachschub anfordern |
| POST | `/quality-alerts` | Quality-Alert (FormData mit Foto-Anhängen) |
| POST | `/voice/recognize` | Whisper-STT (Audio → Text + Intent) |
| POST | `/voice/assist` | Intent-Engine (Text → Kommando/Antwort) |
| POST | `/voice/tts` | Piper-TTS (Text → Audio) |
| GET | `/health` | Health-Check |

> [!note] Die drei Voice-Endpunkte
> `/voice/recognize`, `/voice/assist` und `/voice/tts` sind das serverseitige Rückgrat des Voice-Pfads. Ihre Gegenstücke im Backend sind in [[05 - Backend (FastAPI)]] dokumentiert (Router `app/routers/voice.py`, Services `whisper_client.py`, `piper_client.py`, `intent_engine.py`).

**Header-Muster:**

```javascript
// Lese-Anfragen
headers: { 'X-Picker-User-Id': picker.id }

// Schreib-Anfragen (idempotent)
headers: {
    'X-Picker-User-Id': picker.id,
    'X-Device-Id': deviceId,
    'Idempotency-Key': `scope:deviceId:...`   // Schutz gegen Doppel-Buchung
}
```

> [!note] Idempotency-Key – warum?
> Mobile Netze sind unzuverlässig. Drückt der Picker zweimal „Bestätigen" (oder schickt das Netz die Anfrage doppelt), sorgt der `Idempotency-Key` dafür, dass das Backend die Aktion **nur einmal** ausführt. Details zur serverseitigen Speicherung (Odoo-Tabelle `picking.assistant.idempotency`) in [[05 - Backend (FastAPI)]].

**Local Storage (Offline-Grace-Mode):**

```javascript
STORAGE_KEYS = {
    picker:             'picking-assistant-picker',
    pickerCatalog:      'picking-assistant-picker-catalog',
    deviceId:           'picking-assistant-device-id',
    preferredZone:      'picking-assistant-preferred-zone',
    highContrastEnabled:'picking-assistant-high-contrast',
    searchQuery:        'picking-assistant-search-query',
}
```

---

## 6. Der Voice-Pfad – Schritt für Schritt

> [!info] Das Herzstück
> Der Voice-Pfad erlaubt es dem Picker, **freihändig** zu arbeiten: Er hat die Hände am Karton, spricht Kommandos und bekommt gesprochene Antworten. Touch bleibt aber immer als Rückfallebene erreichbar ([Abschnitt 10](#10-touch-ist-immer-fallback)).

### 6.1 Der Pfad in einer Zeile

```
Aufnahme → POST /api/voice/recognize → Whisper STT → lokale Intent-Engine → Aktion → Piper TTS Antwort
```

### 6.2 Jeder Schritt erklärt

**Schritt 1 – Aufnahme (Mikrofon, im Browser):**

```javascript
activateVoiceMode()
├─ navigator.mediaDevices.getUserMedia({
│     audio: {
│        echoCancellation: true,   // Echo unterdrücken
│        noiseSuppression: true,   // Lagerhallenlärm dämpfen
│        autoGainControl: true     // Lautstärke automatisch
│     }
│  })
├─ AudioContext + AnalyserNode    // misst Lautstärke (RMS) für Sprach-Erkennung
└─ voiceModeActive = true
```

Die Aufnahme stoppt automatisch (`startListeningCycle`) nach:
- 300 ms Stille **nach** erkannter Sprache, oder
- 6 s ohne jede Sprache (Timeout), oder
- spätestens nach 10 s (Maximal-Recording).

Sprache wird erkannt, wenn der RMS-Lautstärkewert `> 18` für 100 ms überschreitet (`hasSpeech = true`).

**Schritt 2 – POST `/api/voice/recognize` (Audio zum Backend):**

```javascript
recognizeVoice(audioBlob, options) → POST /api/voice/recognize
├─ FormData: { audio, context, surface, remaining_line_count }
└─ Antwort: { text, intent, confidence, ... }
```

Das Audio geht als `multipart/form-data` an das Backend. `context`, `surface` und `remaining_line_count` geben dem Backend Kontext (welche Maske, wie viele Positionen offen) – das verbessert die Intent-Erkennung.

**Schritt 3 – Whisper STT (Speech-to-Text, serverseitig):**

Das Backend (`app/services/whisper_client.py`) schickt das Audio an einen **lokalen Whisper-Container** (`/asr`, `language=de`). Whisper wandelt Sprache in Text um. „Lokal" heißt: läuft im eigenen Docker-Netz, keine Cloud → siehe [[03 - Docker & Container]].

**Schritt 4 – lokale Intent-Engine (Text → Kommando):**

Aus dem Text wird ein **Intent** (Absicht). Die Erkennung ist **deterministisch** (regelbasiert, kein LLM) und passiert serverseitig in `app/services/intent_engine.py`. Zusätzlich existiert clientseitig `voice-runtime.mjs` zur Intent-Klassifikation. Mögliche Aktionen: `confirm`, `next`, `problem`, `stock_query`, `done`, `pause`, `photo`, `repeat`, `help`, `status`, `unknown` u. a.

> [!note] „Deterministisch" als bewusste Design-Entscheidung
> Deterministisch = bei gleicher Eingabe immer gleiche Ausgabe, nachvollziehbar, ohne KI-Halluzination. Für eine sicherheitskritische Picking-Aufgabe ist das robuster als ein generatives Modell. Hunderte umgangssprachliche Aliase („jep", „passt", „mhm" → `confirm`) decken reale Sprache ab. Der zukünftige Ausbau zu echten Natural-Language-Kommandos ist ein separater Forschungs-/Ausblickspunkt.

**Schritt 5 – Aktion ausführen:**

Je nach Intent ruft die App den passenden `/api`-Endpunkt auf, z. B. `confirm` → `POST /pickings/{id}/confirm-line`, oder `stock_query` → `POST /voice/assist` (das wiederum n8n synchron befragt, mit lokalem Fallback – siehe [[05 - Backend (FastAPI)]] und [[07 - n8n]]).

**Schritt 6 – Piper TTS Antwort (Text-to-Speech):**

```javascript
// Primär: Server-TTS via Piper
await fetch('/api/voice/tts', {
    method: 'POST',
    body: JSON.stringify({ text, lang: 'de-DE' })
})
└─ Antwort: Audio-Blob → wird abgespielt
└─ Verfügbarkeit wird gecacht (_piperHealthy)
```

Das Backend (`app/services/piper_client.py`) lässt einen lokalen **Piper-Container** den Antworttext sprechen. Piper-Timeout ist 5 s; schlägt es fehl, antwortet das Backend mit `503`, und die PWA fällt auf die Browser-eigene Sprachausgabe zurück:

```javascript
// Fallback: Browser SpeechSynthesis
const utterance = new SpeechSynthesisUtterance(text);
utterance.lang = 'de-DE';
utterance.voice = loadBestDeVoice();   // bevorzugt Markus/Anna
window.speechSynthesis.speak(utterance);
```

> [!info] Hybrid-TTS als Zuverlässigkeits-Trick
> Zwei Sprachausgaben hintereinander geschaltet: Server-Piper (gute Qualität) zuerst, Browser-TTS als Sicherheitsnetz. Der Picker bekommt **immer** eine Antwort, selbst wenn der Piper-Container ausfällt.

### 6.3 Das Audio-Interlock – das schwierigste Detail

> [!warning] Das Problem: Die App hört sich selbst
> Wenn die App per TTS spricht, fängt das Mikrofon die eigene Stimme wieder ein („Echo") und versucht, sie als Kommando zu deuten. Lösung: eine **State-Machine** (Zustandsmaschine), die Mikrofon und Lautsprecher gegeneinander verriegelt („Interlock").

**Datei:** `pwa/js/voice-helpers.mjs`. Fünf Zustände (`VOICE_STATES`):

```javascript
export const VOICE_STATES = {
    IDLE:      'idle',        // keine Aktivität
    LISTENING: 'listening',   // bereit aufzunehmen
    RECORDING: 'recording',   // Audio wird aufgezeichnet
    SPEAKING:  'speaking',    // TTS läuft → Mikrofon gemutet
    COOLDOWN:  'cooldown',    // TTS fertig, 500 ms Pause vor STT
};
```

**Zustandsübergänge (`transitionVoiceState`):**

| Event | Übergang | Effekt |
|-------|----------|--------|
| `activate` / `capture-start` | → LISTENING | Mikrofon bereit |
| `speech-start` | → RECORDING | Aufnahme startet |
| `tts-start` | → SPEAKING | `muteMic(true)` – Mikro aus |
| `tts-end` | → COOLDOWN | 500 ms Pause (`POST_TTS_COOLDOWN_MS`) |
| `cooldown-end` | → LISTENING | `muteMic(false)` – Mikro wieder an |
| `deactivate` | → IDLE | Voice-Modus aus |

**Zweite Verteidigungslinie – Echo-Erkennung im Text:** Selbst wenn doch etwas durchrutscht, prüft `isLikelyPromptEcho(transcript, lastPromptText)` das erste Transkript nach einer TTS-Ausgabe:

```javascript
isLikelyPromptEcho(transcript, lastPromptText) {
    ├─ Normalisierung (ä→ae, Diakritika entfernen)
    ├─ Token-Overlap-Analyse
    └─ wenn > 60 % Überschneidung → verwerfen
}
```

### 6.4 Confirmation-Dialog (Sicherheitsnetz)

Antwortet das Backend mit `requires_confirmation: true`, fragt die App nach, bevor sie eine folgenreiche Aktion ausführt:

```javascript
_handleIntentWithRecovery(result) {
    if (result.requires_confirmation) {
        speak(result.confirmation_prompt);   // z. B. "Bestätigen Sie?"
        _pendingConfirmAction = result.intent;
        _pendingConfirmValue  = result.value;
        // wartet auf "confirm", "pause" oder neuen Intent
    }
}
```

### 6.5 Push-to-Talk (PTT) als Voice-Fallback

Lange auf den Voice-Button drücken (> 350 ms, `VOICE_LONG_PRESS_MS`) aktiviert Push-to-Talk: aufnehmen, solange gedrückt; beim Loslassen → `recognizeVoice()` → Intent-Verarbeitung. Nützlich in lauter Umgebung, wo Dauer-Lauschen unzuverlässig wäre.

---

## 7. Barcode-Scan (HID + `/api/scan/validate`)

**Datei:** `pwa/js/scanner.js`. Drei-stufige Fallback-Kette:

```
1. HID-Scanner (Bluetooth Keyboard-Wedge, z. B. Zebra)
   └─ initHIDScanner(onScan), lauscht auf 'keydown', Enter = Barcode fertig
2. BarcodeDetector API (Chrome Android ≥ 83)
   └─ Formate: EAN-13, EAN-8, Code-128, Code-39, QR, DataMatrix (nur mit Kamera-Erlaubnis)
3. Touch-Fallback: manuelle Eingabe im Textfeld
```

> [!note] „HID Keyboard-Wedge" einfach erklärt
> Viele professionelle Barcode-Scanner verhalten sich gegenüber dem Gerät wie eine **Tastatur**: Sie „tippen" die gescannten Ziffern und drücken am Ende Enter. Die App muss also nur auf Tastatur-Events lauschen – kein Spezial-Treiber nötig.

**HID-Logik (Kernidee):**

```javascript
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && scanBuffer.length >= MIN_BARCODE_LENGTH) {
        e.preventDefault();
        const barcode = scanBuffer.trim();
        scanBuffer = '';
        if (scanCallback) scanCallback(barcode);
        return;
    }
    if (e.key.length === 1) {
        scanBuffer += e.key;
        // Reset nach 300 ms – manuelles Tippen ist langsamer als ein Scanner
        scanTimeout = setTimeout(() => { scanBuffer = ''; }, 300);
    }
});
```

**Validierung gegen das Backend:** Der gescannte Code wird über `POST /api/scan/validate` geprüft (Router `app/routers/scan.py`). Input: `barcode` + `expected_barcode`; Output: `{ match, barcode, expected, message }`. Im normalen Picking-Fluss fließt der Barcode zudem in `POST /pickings/{id}/confirm-line` ein.

> [!warning] Kamera-Scan braucht HTTPS
> Stufe 2 (BarcodeDetector über die Kamera) und der Kamera-Overlay funktionieren nur im **Secure Context** (HTTPS) und nur nach einer Nutzer-Geste. Siehe [Abschnitt 9](#9-https-pflicht-mikrofon-kamera-service-worker).

---

## 8. Touch ist immer Fallback

> [!important] Grundprinzip Barrierefreiheit & Robustheit
> Jede Aktion, die per Voice oder Scan geht, geht **auch per Fingertipp**. Voice und Scan sind Beschleuniger, kein Zwang. Fällt das Mikrofon oder der Scanner aus, bleibt die App voll bedienbar.

**Datei:** `pwa/js/app.js`, Markup in `pwa/index.html`.

```html
<!-- Detail-Ansicht: jede Position hat Touch-Buttons -->
<div class="detail-compact__actions">
    <button class="btn-confirm"    data-line-id="${line.id}">Bestätigen</button>
    <button class="btn-short-pick" data-line-id="${line.id}">Fehlbestand</button>
</div>

<!-- Manuelle Barcode-Eingabe als Scan-Fallback -->
<div id="scan-input-area">
    <input type="text" placeholder="Barcode..." inputmode="numeric">
    <button>OK</button>
</div>
```

**Barrierefreiheit (Accessibility):**
- Touch-Targets mindestens `--touch-min: 48px` (WCAG Level AA).
- **High-Contrast-Modus** (`body.high-contrast`) für WCAG AAA, umschaltbar, in Local Storage gespeichert.
- `aria-label`, `aria-pressed`, `role="dialog"` für Screenreader.

**High-Contrast über CSS-Variablen** (`pwa/css/app.css`):

```css
:root {
    --bg: #f6f8fc;  --surface: #ffffff;  --ink: #142033;
    --primary: #355cff;  --success: #53c98d;  --danger: #ef6b6b;
    --radius: 20px;  --touch-min: 48px;
}
body.high-contrast {
    --bg: #FFFFFF;  --ink: #000000;  --primary: #003DA5;   /* WCAG-AAA-Kontrast */
}
```

**Multisensorisches Feedback** (`pwa/js/feedback.js`, Web Audio API + Vibration API, ganz ohne MP3/OGG-Dateien): `feedbackSuccess()` (heller Doppel-Beep + kurze Vibration + grüner Flash), `feedbackError()` (tiefer Brummton + lange Vibration + roter Flash), `feedbackAlert()` (Ton-Tripel + komplexes Vibrationsmuster). So bekommt der Picker Rückmeldung über **drei Kanäle** – Ton, Vibration, Bild – auch in lauter Umgebung oder mit Handschuhen.

---

## 9. HTTPS-Pflicht (Mikrofon, Kamera, Service Worker)

> [!warning] Ohne HTTPS läuft fast nichts
> Browser geben drei sicherheitskritische Funktionen **nur im „Secure Context"** frei – also nur über `https://` (Ausnahme: `localhost`):
> 1. **Mikrofon** (`getUserMedia` Audio) → ohne HTTPS kein Voice-Pfad
> 2. **Kamera** (`getUserMedia` Video, BarcodeDetector) → ohne HTTPS kein Kamera-Scan
> 3. **Service Worker** (`navigator.serviceWorker.register`) → ohne HTTPS keine Installierbarkeit, kein Offline

**Konsequenz:** Auch in der lokalen Entwicklung und im LAN muss die PWA über HTTPS ausgeliefert werden, damit Voice, Kamera und PWA-Installation funktionieren.

**Lösung: `mkcert`.** `mkcert` ist ein kleines Werkzeug, das **lokal vertrauenswürdige Zertifikate** erzeugt. Es legt eine eigene Mini-Zertifizierungsstelle (CA) im System an, sodass selbst-ausgestellte Zertifikate für `localhost` und lokale IPs vom Browser **ohne Warnung** akzeptiert werden – als wären sie echt.

> [!note] Warum nicht einfach `http://`?
> Über `http://192.168.x.x` (das Smartphone im selben WLAN) würde der Browser Mikrofon, Kamera und Service-Worker-Registrierung blockieren. `mkcert` löst genau dieses Henne-Ei-Problem für die Testumgebung. Wie das im Container-/Reverse-Proxy-Setup verdrahtet ist, gehört zu [[03 - Docker & Container]].

---

## 10. App-Lebenszyklus & Zustände (Kurzüberblick)

**Datei:** `pwa/js/app.js`. Die App durchläuft `sessionState`:

```
profile_required → list → detail → complete
    │                │       │         └─ Gratulation, „Nächsten starten"
    │                │       └─ Position für Position: Scan / Voice / Touch
    │                └─ Aufträge anzeigen, Auftrag claimen
    └─ Picker wählen
```

Während ein Auftrag bearbeitet wird, läuft ein **Heartbeat alle 30 s** (`startClaimHeartbeat()` → `POST /pickings/{id}/heartbeat`), damit der Claim nicht abläuft (Backend-Claim-TTL standardmäßig 120 s; Details in [[05 - Backend (FastAPI)]]). Connectivity-Events (`online`/`offline`/`visibilitychange`/`pageshow`) und Service-Worker-Updates (`updatefound` → `SKIP_WAITING`) werden in `pwa/js/pwa.js` und `app.js` behandelt.

---

## 11. Tests

**Verzeichnis:** `pwa/js/tests/`

| Datei | prüft |
|-------|-------|
| `api.test.mjs` | API-Client, Fehlerbehandlung |
| `voice-helpers.test.mjs` | Echo-Erkennung, State-Machine-Übergänge |
| `voice-runtime.test.mjs` | Intent-Klassifikation, Confidence-Schwellwerte |

---

## 12. Zusammenfassung der Kernmechanismen

| Funktion | Implementierung | Datei(en) |
|----------|-----------------|-----------|
| PWA-Installation | Manifest + Service Worker | `manifest.json`, `sw.js`, `js/pwa.js` |
| Offline-Caching | Shell cachen, `/api` nie | `sw.js` |
| Backend-API | Fetch + Idempotency-Keys | `js/api.js` |
| Voice-Aufnahme | `getUserMedia` + RMS-Detection | `js/voice.js` |
| TTS↔STT-Interlock | 5-State-Machine | `js/voice.js`, `js/voice-helpers.mjs` |
| Echo-Vermeidung | Token-Overlap-Analyse | `js/voice-helpers.mjs` |
| Intent (Client) | deterministische Klassifikation | `js/voice-runtime.mjs` |
| Barcode HID | Keyboard-Event-Listener | `js/scanner.js` |
| Barcode Kamera | BarcodeDetector API | `js/scanner.js` |
| Touch-Fallback | immer sichtbare Buttons/Felder | `js/app.js`, `index.html` |
| Feedback | Web Audio + Vibration API | `js/feedback.js` |
| High-Contrast | CSS-Variablen + Local Storage | `css/app.css`, `js/app.js` |

---

> [!info] Weiterlesen
> - Serverseite des Voice-Pfads (Whisper, Piper, Intent-Engine, `/voice/*`): [[05 - Backend (FastAPI)]]
> - Wie alles zusammenhängt: [[02 - Architektur & Diagramm erklärt]]
> - Lokale Container (Whisper/Piper, HTTPS-Proxy): [[03 - Docker & Container]]
> - Synchrone Voice-Antworten & Quality-AI über Workflows: [[07 - n8n]]
> - Begriffe (PWA, STT, TTS, HID, Intent, Idempotenz): [[10 - Glossar]]
> - Zurück zur Übersicht: [[00 - Start Hier (Übersichtskarte)]]
