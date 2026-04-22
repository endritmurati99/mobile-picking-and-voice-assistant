/**
 * Barcode-Scanner-Integration.
 * 
 * Strategie (Priorität):
 * 1. Bluetooth-HID-Scanner (onScan.js Pattern)
 * 2. BarcodeDetector API (nur Chrome Android)
 * 3. Touch-Fallback (manuelle Eingabe)
 * 
 * KEIN Kamera-Scanning im MVP — HID-Scanner + Touch reicht.
 */

let scanCallback = null;
let scanBuffer = '';
let scanTimeout = null;
const SCAN_THRESHOLD_MS = 50;  // HID-Scanner tippen schneller als Menschen
const MIN_BARCODE_LENGTH = 4;

/**
 * HID-Scanner-Listener initialisieren.
 * HID-Scanner senden Zeichen als Keyboard-Events mit hoher Geschwindigkeit.
 */
export function initHIDScanner(onScan) {
    scanCallback = onScan;

    document.addEventListener('keydown', (e) => {
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
 * BarcodeDetector API (Chrome Android ≥83).
 * Gibt null zurück wenn nicht verfügbar.
 */
export function isBarcodeDetectorAvailable() {
    return typeof BarcodeDetector !== 'undefined';
}

/**
 * Kamera-Barcode-Scanner-Overlay öffnen.
 * - Nutzt BarcodeDetector API wenn verfügbar (automatische Erkennung)
 * - Fallback: Kamera-Vorschau + manuelle Eingabe
 * onScan(barcode) wird aufgerufen sobald ein Barcode erkannt wurde.
 */
export async function openCameraScanner(onScan) {
    const overlay = document.createElement('div');
    overlay.id = 'barcode-scanner-overlay';
    overlay.style.cssText = [
        'position:fixed', 'inset:0', 'z-index:500',
        'background:#000', 'display:flex', 'flex-direction:column',
    ].join(';');

    const hasDetector = typeof BarcodeDetector !== 'undefined';

    overlay.innerHTML = `
        <div style="position:relative;flex:1;overflow:hidden;background:#000;">
            <video id="scanner-video" autoplay playsinline muted
                   style="width:100%;height:100%;object-fit:cover;"></video>
            <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none;">
                <div style="width:260px;height:130px;border:3px solid var(--primary);border-radius:10px;box-shadow:0 0 0 9999px rgba(0,0,0,0.45);"></div>
            </div>
            <div style="position:absolute;top:16px;left:0;right:0;text-align:center;">
                <span style="background:rgba(0,0,0,0.6);color:var(--text-primary);padding:6px 14px;border-radius:20px;font-size:0.85rem;">
                    ${hasDetector ? 'Barcode in den Rahmen halten' : 'Barcode scannen'}
                </span>
            </div>
        </div>
        <div style="padding:16px;background:var(--bg);display:flex;flex-direction:column;gap:10px;">
            <div style="display:flex;gap:8px;align-items:center;">
                <input type="text" id="scanner-manual-input" placeholder="Barcode manuell eingeben"
                       inputmode="numeric" autocomplete="off"
                       style="flex:1;padding:12px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text-primary);font-size:1rem;">
                <button id="scanner-manual-submit"
                        style="padding:12px 18px;background:var(--success);color:#041514;border:none;border-radius:8px;font-weight:600;">OK</button>
            </div>
            <button id="scanner-close"
                    style="padding:12px;background:var(--danger);color:#fff;border:none;border-radius:8px;font-weight:600;font-size:1rem;">
                Abbrechen
            </button>
        </div>`;

    document.body.appendChild(overlay);

    let videoStream = null;
    let rafHandle = null;

    const videoEl = document.getElementById('scanner-video');

    // Kamera starten
    try {
        videoStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'environment', width: { ideal: 1280 } },
        });
        videoEl.srcObject = videoStream;
    } catch {
        videoEl.parentElement.style.display = 'none';
    }

    function close() {
        if (rafHandle) cancelAnimationFrame(rafHandle);
        if (videoStream) videoStream.getTracks().forEach(t => t.stop());
        overlay.remove();
    }

    document.getElementById('scanner-close').addEventListener('click', close);

    // BarcodeDetector-Loop (automatische Erkennung)
    if (hasDetector && videoStream) {
        const detector = new BarcodeDetector({
            formats: ['ean_13', 'ean_8', 'code_128', 'code_39', 'qr_code', 'data_matrix'],
        });

        async function detectLoop() {
            if (videoEl.readyState >= 2) {
                try {
                    const results = await detector.detect(videoEl);
                    if (results.length > 0) {
                        close();
                        onScan(results[0].rawValue);
                        return;
                    }
                } catch { /* ignorieren */ }
            }
            rafHandle = requestAnimationFrame(detectLoop);
        }
        videoEl.addEventListener('playing', () => {
            rafHandle = requestAnimationFrame(detectLoop);
        });
    }

    // Manuelle Eingabe (immer als Fallback verfügbar)
    const manualInput = document.getElementById('scanner-manual-input');
    const manualSubmit = document.getElementById('scanner-manual-submit');
    manualInput.focus();

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
        <input type="text" id="barcode-input" class="manual-barcode-entry__input" inputmode="numeric"
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
