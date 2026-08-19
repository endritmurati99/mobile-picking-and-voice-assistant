/**
 * Barcode-Scanner-Integration.
 *
 * Strategie (Prioritaet):
 * 1. Bluetooth-HID-Scanner (onScan.js Pattern)
 * 2. Kamera:
 *    2a. BarcodeDetector API   -- Chrome/Android, im Lager erprobt, nativ und gratis
 *    2b. zxing-wasm (Fallback) -- iOS/Safari und jeder Browser ohne BarcodeDetector
 * 3. Touch-Fallback (manuelle Eingabe)
 *
 * Warum ueberhaupt ein Fallback:
 * Unter iOS benutzt JEDER Browser (Safari, Chrome, Firefox, Edge) die WebKit-Engine,
 * und WebKit liefert `BarcodeDetector` nicht aus. Auf dem iPhone lief deshalb bisher
 * nur die Kameravorschau ohne jede Erkennung -- die manuelle Eingabe war der einzige Weg.
 *
 * Fremdbibliothek (eingebettet, siehe pwa/vendor/zxing/):
 *   zxing-wasm 3.1.3 -- WebAssembly-Build von zxing-cpp
 *   MIT (Wrapper) + Apache-2.0 (zxing-cpp Kern), https://github.com/Sec-ant/zxing-wasm
 *   Wird ausschliesslich LOKAL geladen (/vendor/zxing/...), nie von einem CDN:
 *   das Lager-WLAN hat keinen Internetzugang. Die Voreinstellung der Bibliothek
 *   zieht die .wasm-Datei von jsDelivr -- genau das wird unten per `locateFile`
 *   ueberschrieben.
 *   Geladen wird sie per dynamischem `import()`, also erst wenn `BarcodeDetector`
 *   wirklich fehlt. Geraete mit BarcodeDetector holen die 1,1 MB nie.
 */

let scanCallback = null;
let scanBuffer = '';
let scanTimeout = null;
const SCAN_THRESHOLD_MS = 50;  // HID-Scanner tippen schneller als Menschen
const MIN_BARCODE_LENGTH = 4;

/** Formate, die im Lager vorkommen. Fuer beide Erkenner dieselbe Liste. */
const DETECTOR_FORMATS = ['ean_13', 'ean_8', 'code_128', 'code_39', 'qr_code', 'data_matrix'];
const ZXING_FORMATS = ['EAN-13', 'EAN-8', 'Code128', 'Code39', 'QRCode', 'DataMatrix'];

/** Erkennung hoechstens alle 120 ms -- 8 Versuche/s reichen und schonen den Akku. */
const SCAN_INTERVAL_MS = 120;
// Sperrfrist nach dem Oeffnen. Ohne sie nimmt der Scanner den Code, der beim
// Aufklappen zufaellig im Bild liegt, bevor der Benutzer ueberhaupt zielen kann.
const ARM_DELAY_MS = 500;
// Ein Treffer zaehlt erst, wenn zwei aufeinanderfolgende Durchlaeufe denselben
// Wert liefern. Kostet rund 120 ms und verhindert den Zufallsgriff auf einen
// Nachbarcode, der nur kurz durchs Bild wandert.
const CONFIRM_HITS = 2;
/** Nach so vielen ms ohne Treffer bekommt der Benutzer einen Hinweis statt Stille. */
const HINT_AFTER_MS = 6000;
const HINT2_AFTER_MS = 14000;

/**
 * HID-Scanner-Listener initialisieren.
 * HID-Scanner senden Zeichen als Keyboard-Events mit hoher Geschwindigkeit.
 */
export function initHIDScanner(onScan) {
    scanCallback = onScan;

    document.addEventListener('keydown', (e) => {
        const target = e.target;
        if (
            target
            && (
                target.matches?.('input, textarea, select')
                || target.isContentEditable
            )
        ) {
            return;
        }

        // Enter = Scan-Ende
        if (e.key === 'Enter' && scanBuffer.length >= MIN_BARCODE_LENGTH) {
            e.preventDefault();
            const barcode = scanBuffer.trim();
            scanBuffer = '';
            clearTimeout(scanTimeout);
            if (scanCallback) scanCallback(barcode);
            return;
        }

        // Nur druckbare Zeichen
        if (e.key.length === 1) {
            scanBuffer += e.key;
            clearTimeout(scanTimeout);
            // Reset nach Timeout (manuelles Tippen ist langsamer)
            scanTimeout = setTimeout(() => { scanBuffer = ''; }, 300);
        }
    });
}

/**
 * BarcodeDetector API (Chrome Android >= 83).
 * Gibt false zurueck wenn nicht verfuegbar (u. a. auf JEDEM iOS-Browser).
 */
export function isBarcodeDetectorAvailable() {
    return typeof BarcodeDetector !== 'undefined';
}

/**
 * Auswahl des Erkenners -- als reine Funktion, damit sie ohne Browser testbar ist.
 *
 * @param {object} [scope] Objekt, in dem nach `BarcodeDetector` gesucht wird
 *                         (im Betrieb `globalThis`, im Test ein Attrappen-Objekt).
 * @returns {'barcode-detector'|'zxing-wasm'}
 */
export function selectScanEngine(scope = globalThis) {
    const ctor = scope?.BarcodeDetector;
    return typeof ctor === 'function' ? 'barcode-detector' : 'zxing-wasm';
}

/**
 * Bildausschnitt im angezeigten Rahmen auf Videopixel umrechnen.
 *
 * Das Video haengt mit `object-fit: cover` im Overlay: es wird so skaliert, dass es
 * den Kasten fuellt, der Ueberstand wird links/rechts bzw. oben/unten abgeschnitten.
 * Ohne diese Umrechnung wuerde der Rahmen auf dem Bildschirm etwas ganz anderes
 * einrahmen als der Ausschnitt, den wir dekodieren.
 *
 * Reine Funktion, damit sie ohne Browser pruefbar ist.
 *
 * @returns {{sx:number, sy:number, sw:number, sh:number}} Quellrechteck im Videobild
 */
export function computeRoi({
    videoWidth, videoHeight, displayWidth, displayHeight,
    boxWidth, boxHeight, padding = 0.18,
}) {
    if (!videoWidth || !videoHeight || !displayWidth || !displayHeight) {
        return { sx: 0, sy: 0, sw: videoWidth || 0, sh: videoHeight || 0 };
    }
    // object-fit: cover -> der groessere der beiden Massstaebe gewinnt
    const scale = Math.max(displayWidth / videoWidth, displayHeight / videoHeight);
    // Rahmen ist im Overlay zentriert; Groesse in CSS-Pixeln -> Videopixel
    let sw = (boxWidth / scale) * (1 + padding * 2);
    let sh = (boxHeight / scale) * (1 + padding * 2);
    sw = Math.min(videoWidth, Math.max(1, Math.round(sw)));
    sh = Math.min(videoHeight, Math.max(1, Math.round(sh)));
    const sx = Math.max(0, Math.round((videoWidth - sw) / 2));
    const sy = Math.max(0, Math.round((videoHeight - sh) / 2));
    return { sx, sy, sw, sh };
}

/**
 * zxing-wasm nachladen -- lokal, einmalig, und erst wenn wirklich gebraucht.
 * Der Promise wird gemerkt, damit ein zweites Oeffnen des Scanners sofort startet.
 */
let zxingPromise = null;
export function loadZXing() {
    if (zxingPromise) return zxingPromise;
    zxingPromise = (async () => {
        const moduleUrl = new URL('../vendor/zxing/reader/index.js', import.meta.url).href;
        const wasmUrl = new URL('../vendor/zxing/zxing_reader.wasm', import.meta.url).href;
        const zxing = await import(/* @vite-ignore */ moduleUrl);
        // Ohne diesen Override zieht zxing-wasm die .wasm-Datei von jsDelivr --
        // im Lager-WLAN ohne Internet waere das ein stiller Totalausfall.
        await zxing.prepareZXingModule({
            overrides: {
                locateFile: (path, prefix) => (
                    path.endsWith('.wasm') ? wasmUrl : `${prefix}${path}`
                ),
            },
            fireImmediately: true,
        });
        return zxing;
    })().catch((err) => {
        zxingPromise = null;   // beim naechsten Oeffnen erneut versuchen
        throw err;
    });
    return zxingPromise;
}


/**
 * Torwaechter fuer Treffer: Sperrfrist nach dem Oeffnen plus Bestaetigung durch
 * Wiederholung.
 *
 * Am Geraet beobachtet (19.08.2026): auf einem A4-Blatt mit mehreren Codes
 * nebeneinander buchte der Scanner sofort irgendeinen, waehrend der Benutzer
 * noch zielte. Beides hier ist die Antwort darauf -- als eigene Funktion,
 * damit es pruefbar ist und nicht im Kamera-Code versteckt liegt.
 *
 * @param {{armDelayMs?: number, confirmHits?: number, now?: () => number}} options
 */
export function createHitGate({
    armDelayMs = ARM_DELAY_MS,
    confirmHits = CONFIRM_HITS,
    now = () => Date.now(),
} = {}) {
    const openedAt = now();
    let pending = '';
    let hits = 0;

    return {
        /** @returns {boolean} true, wenn der Wert jetzt gilt. */
        offer(value) {
            if (!value) {
                this.reset();
                return false;
            }
            if (now() - openedAt < armDelayMs) return false;
            if (value === pending) {
                hits += 1;
            } else {
                pending = value;
                hits = 1;
            }
            return hits >= confirmHits;
        },
        /** Kandidat aus dem Bild verschwunden -- Bestaetigung faengt von vorn an. */
        reset() {
            pending = '';
            hits = 0;
        },
    };
}

/**
 * Kamera-Barcode-Scanner-Overlay oeffnen.
 * - BarcodeDetector API wenn verfuegbar (Android/Chrome)
 * - sonst zxing-wasm (iOS und alles andere)
 * - immer zusaetzlich: manuelle Eingabe
 * onScan(barcode) wird aufgerufen sobald ein Barcode erkannt wurde.
 */
export async function openCameraScanner(onScan) {
    const returnFocus = document.activeElement;
    const overlay = document.createElement('div');
    overlay.id = 'barcode-scanner-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'scanner-title');
    overlay.tabIndex = -1;
    overlay.style.cssText = [
        'position:fixed', 'inset:0', 'z-index:500',
        'background:#000', 'display:flex', 'flex-direction:column',
    ].join(';');

    const engine = selectScanEngine();
    const hasDetector = engine === 'barcode-detector';

    overlay.innerHTML = `
        <div style="position:relative;flex:1;overflow:hidden;background:#000;">
            <video id="scanner-video" autoplay playsinline webkit-playsinline muted
                   style="width:100%;height:100%;object-fit:cover;"></video>
            <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none;">
                <div id="scanner-frame" style="width:260px;height:130px;border:3px solid var(--primary);border-radius:10px;box-shadow:0 0 0 9999px rgba(0,0,0,0.45);"></div>
            </div>
            <div style="position:absolute;top:16px;left:0;right:0;text-align:center;padding:0 12px;">
                <span id="scanner-status" role="status" aria-live="polite"
                      style="display:inline-block;background:rgba(0,0,0,0.6);color:#fff;padding:6px 14px;border-radius:20px;font-size:0.85rem;line-height:1.35;max-width:100%;">
                    Barcode in den Rahmen halten
                </span>
            </div>
        </div>
        <div style="padding:16px;background:var(--bg);display:flex;flex-direction:column;gap:10px;">
            <strong id="scanner-title" style="color:var(--ink);font-size:1.1rem;">Barcode scannen</strong>
            <div style="display:flex;gap:8px;align-items:center;">
                <input type="text" id="scanner-manual-input" placeholder="Barcode manuell eingeben"
                       inputmode="text" autocomplete="off"
                       style="flex:1;min-width:0;padding:12px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--ink);font-size:1rem;">
                <button type="button" id="scanner-manual-submit"
                        style="padding:12px 18px;background:var(--success);color:#041514;border:none;border-radius:8px;font-weight:600;">OK</button>
            </div>
            <button type="button" id="scanner-close"
                    style="padding:12px;background:var(--danger);color:#fff;border:none;border-radius:8px;font-weight:600;font-size:1rem;">
                Abbrechen
            </button>
        </div>`;

    document.body.appendChild(overlay);

    let videoStream = null;
    let loopHandle = null;
    let closed = false;

    const videoEl = document.getElementById('scanner-video');
    const frameEl = document.getElementById('scanner-frame');
    const statusEl = document.getElementById('scanner-status');

    const setStatus = (text) => { if (statusEl && !closed) statusEl.textContent = text; };

    // iOS: `muted` und `playsinline` muessen auch als Property gesetzt sein, sonst
    // verweigert WebKit die Inline-Wiedergabe und geht in den Vollbild-Player.
    videoEl.muted = true;
    videoEl.playsInline = true;
    videoEl.setAttribute('playsinline', '');

    // Kamera starten. iOS wirft bei zu strengen Constraints OverconstrainedError,
    // deshalb absteigende Kette statt einer einzigen Anforderung.
    const constraintCandidates = [
        // Scharfe Bilder helfen 1D-Codes am meisten: erst 1920 versuchen.
        { video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } } },
        { video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } } },
        { video: { facingMode: 'environment' } },
        { video: true },
    ];

    for (const constraints of constraintCandidates) {
        try {
            videoStream = await navigator.mediaDevices.getUserMedia(constraints);
            break;
        } catch { /* naechste Stufe versuchen */ }
    }

    if (videoStream) {
        videoEl.srcObject = videoStream;
        // Safari startet nicht immer von selbst, obwohl `autoplay` gesetzt ist.
        // Ohne dieses explizite play() bleibt das Bild auf dem iPhone schwarz.
        try { await videoEl.play(); } catch { /* Autoplay-Politik, Bild kommt trotzdem */ }
        // Dauer-Autofokus, wo der Browser ihn anbietet (Android). iOS ignoriert das
        // stillschweigend und fokussiert selbst -- deshalb nur best effort.
        try {
            const [track] = videoStream.getVideoTracks();
            const caps = track?.getCapabilities?.() ?? {};
            const advanced = [];
            if (caps.focusMode?.includes('continuous')) advanced.push({ focusMode: 'continuous' });
            if (caps.exposureMode?.includes('continuous')) advanced.push({ exposureMode: 'continuous' });
            if (advanced.length) await track.applyConstraints({ advanced });
        } catch { /* optional */ }
    } else {
        videoEl.parentElement.style.display = 'none';
        overlay.style.background = 'var(--bg)';
        overlay.lastElementChild.style.margin = 'auto 0';
    }

    function close() {
        if (closed) return;
        closed = true;
        if (loopHandle) clearTimeout(loopHandle);
        if (videoStream) videoStream.getTracks().forEach(t => t.stop());
        document.removeEventListener('keydown', handleDialogKeydown);
        overlay.remove();
        returnFocus?.focus?.();
    }

    function handleDialogKeydown(event) {
        if (event.key === 'Escape') {
            event.preventDefault();
            close();
            return;
        }
        if (event.key !== 'Tab') return;
        const focusable = [...overlay.querySelectorAll('input, button:not([disabled])')];
        const first = focusable[0];
        const last = focusable.at(-1);
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
        }
    }

    document.addEventListener('keydown', handleDialogKeydown);

    document.getElementById('scanner-close').addEventListener('click', close);

    // ---- Erkennungsschleife -------------------------------------------------
    // Bewusst `setTimeout` statt `requestAnimationFrame`: rAF steht still, sobald
    // die Seite in den Hintergrund geht, und feuert sonst 60x/s -- viel oefter als
    // noetig. Die feste Taktung ist sparsamer und auf jedem Geraet gleich.
    if (videoStream) {
        const startedAt = Date.now();
        let hintLevel = 0;
        let canvas = null;
        let ctx = null;
        let tick = 0;

        // Der Bildausschnitt, den der Rahmen auf dem Schirm markiert -- in
        // Videopixeln. Beide Erkennungswege brauchen ihn: der eine, um nur
        // diesen Teil zu dekodieren, der andere, um Treffer ausserhalb zu
        // verwerfen.
        const currentRegion = () => {
            const vw = videoEl.videoWidth;
            const vh = videoEl.videoHeight;
            if (!vw || !vh) return null;
            if (!frameEl) return { sx: 0, sy: 0, sw: vw, sh: vh };
            const boxRect = frameEl.getBoundingClientRect();
            return computeRoi({
                videoWidth: vw,
                videoHeight: vh,
                displayWidth: videoEl.clientWidth,
                displayHeight: videoEl.clientHeight,
                boxWidth: boxRect.width,
                boxHeight: boxRect.height,
            });
        };

        const grabFrame = () => {
            const vw = videoEl.videoWidth;
            const vh = videoEl.videoHeight;
            if (!vw || !vh) return null;

            // NUR der Rahmenausschnitt. Frueher lief jeder vierte Durchlauf ueber
            // das Vollbild, um Codes knapp neben dem Rahmen mitzunehmen -- auf
            // einem A4-Blatt mit mehreren Codes nebeneinander griff der Scanner
            // damit den Nachbarn, bevor der Benutzer zielen konnte. Am Geraet
            // beobachtet. Der Rahmen ist die Zielhilfe; was ausserhalb liegt,
            // ist nicht gemeint.
            const region = currentRegion() || { sx: 0, sy: 0, sw: vw, sh: vh };

            if (!canvas) {
                canvas = document.createElement('canvas');
                ctx = canvas.getContext('2d', { willReadFrequently: true });
            }
            if (canvas.width !== region.sw || canvas.height !== region.sh) {
                canvas.width = region.sw;
                canvas.height = region.sh;
            }
            ctx.drawImage(
                videoEl,
                region.sx, region.sy, region.sw, region.sh,
                0, 0, region.sw, region.sh,
            );
            return ctx.getImageData(0, 0, region.sw, region.sh);
        };

        const gate = createHitGate();

        const succeed = (value) => {
            if (!value || closed) return false;
            if (!gate.offer(value)) return false;
            close();
            onScan(value);
            return true;
        };

        const missed = () => gate.reset();

        const updateHint = () => {
            const elapsed = Date.now() - startedAt;
            if (hintLevel < 2 && elapsed > HINT2_AFTER_MS) {
                hintLevel = 2;
                setStatus('Immer noch nichts erkannt. Bitte den Code unten von Hand eintippen.');
            } else if (hintLevel < 1 && elapsed > HINT_AFTER_MS) {
                hintLevel = 1;
                setStatus('Noch nichts erkannt: Abstand ca. 15 cm, Code ganz in den Rahmen, ruhig halten.');
            }
        };

        const schedule = (fn) => { loopHandle = setTimeout(fn, SCAN_INTERVAL_MS); };

        if (hasDetector) {
            const detector = new BarcodeDetector({ formats: DETECTOR_FORMATS });
            const loop = async () => {
                if (closed) return;
                if (videoEl.readyState >= 2) {
                    try {
                        const results = await detector.detect(videoEl);
                        // Der native Erkenner sieht immer das ganze Videobild. Damit
                        // er sich auf einem Blatt mit mehreren Codes nicht den
                        // Nachbarn greift, zaehlt nur, was mit seiner Mitte im
                        // angezeigten Rahmen liegt.
                        const inFrame = results.filter((result) => {
                            const box = result.boundingBox;
                            const region = currentRegion();
                            if (!box || !region) return true;
                            const cx = box.x + box.width / 2;
                            const cy = box.y + box.height / 2;
                            return cx >= region.sx && cx <= region.sx + region.sw
                                && cy >= region.sy && cy <= region.sy + region.sh;
                        });
                        const werte = [...new Set(inFrame.map(r => r.rawValue).filter(Boolean))];
                        if (werte.length > 1) {
                            setStatus('Mehrere Codes im Rahmen. Naeher heran oder einzeln zeigen.');
                            missed();
                        } else if (werte.length === 1) {
                            if (succeed(werte[0])) return;
                        } else {
                            missed();
                        }
                    } catch { /* ignorieren */ }
                }
                tick++;
                updateHint();
                schedule(loop);
            };
            schedule(loop);
        } else {
            setStatus('Scanner wird vorbereitet ...');
            loadZXing().then((zxing) => {
                if (closed) return;
                setStatus('Barcode in den Rahmen halten');
                const loop = async () => {
                    if (closed) return;
                    if (videoEl.readyState >= 2) {
                        try {
                            const imageData = grabFrame();
                            if (imageData) {
                                const results = await zxing.readBarcodes(imageData, {
                                    formats: ZXING_FORMATS,
                                    tryHarder: true,
                                    tryRotate: true,
                                    tryInvert: true,
                                    // Bewusst mehr als eins: liegen zwei Codes im
                                    // Rahmen, soll das auffallen statt willkuerlich
                                    // einen davon zu buchen.
                                    maxNumberOfSymbols: 2,
                                });
                                const werte = [...new Set(results.map(r => r.text).filter(Boolean))];
                                if (werte.length > 1) {
                                    setStatus('Mehrere Codes im Rahmen. Naeher heran oder einzeln zeigen.');
                                    missed();
                                } else if (werte.length === 1) {
                                    if (succeed(werte[0])) return;
                                } else {
                                    missed();
                                }
                            } else {
                                missed();
                            }
                        } catch { /* ignorieren, naechster Versuch */ }
                    }
                    tick++;
                    updateHint();
                    schedule(loop);
                };
                schedule(loop);
            }).catch(() => {
                setStatus('Automatische Erkennung nicht verfuegbar -- bitte unten eintippen.');
            });
        }
    }

    // Manuelle Eingabe (immer als Fallback verfuegbar)
    const manualInput = document.getElementById('scanner-manual-input');
    const manualSubmit = document.getElementById('scanner-manual-submit');

    // Nur wenn KEINE Kamera laeuft, bekommt das Eingabefeld sofort den Fokus.
    // Sonst schiebt die Bildschirmtastatur des iPhones die Kameravorschau aus dem
    // Bild und der Benutzer scannt gegen eine verdeckte Ansicht. Der Fokus liegt
    // dann auf dem Overlay -- Fokusfalle, Tab und Escape bleiben unveraendert.
    if (videoStream) overlay.focus(); else manualInput.focus();

    const submitManual = () => {
        const val = manualInput.value.trim();
        if (val.length >= MIN_BARCODE_LENGTH) {
            close();
            onScan(val);
        }
    };
    manualSubmit.addEventListener('click', submitManual);
    manualInput.addEventListener('keydown', e => { if (e.key === 'Enter') submitManual(); });
}

/**
 * Touch-Fallback: Manuelles Barcode-Eingabefeld anzeigen.
 */
export function showManualInput(onSubmit) {
    const existing = document.getElementById('manual-barcode-input');
    if (existing) existing.remove();

    const container = document.createElement('div');
    container.id = 'manual-barcode-input';
    container.className = 'manual-barcode-entry';
    container.innerHTML = `
        <input type="text" id="barcode-input" class="manual-barcode-entry__input" inputmode="text"
               placeholder="Barcode eingeben" autocomplete="off">
        <button id="barcode-submit"
                class="manual-barcode-entry__submit">
            Barcode absenden
        </button>
    `;

    const input = container.querySelector('#barcode-input');
    const btn = container.querySelector('#barcode-submit');

    btn.addEventListener('click', () => {
        const val = input.value.trim();
        if (val.length >= MIN_BARCODE_LENGTH && onSubmit) {
            onSubmit(val);
            input.value = '';
        }
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') btn.click();
    });

    return container;
}
