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
 * Touch-Fallback: Manuelles Barcode-Eingabefeld anzeigen.
 */
export function showManualInput(onSubmit) {
    const existing = document.getElementById('manual-barcode-input');
    if (existing) existing.remove();

    const container = document.createElement('div');
    container.id = 'manual-barcode-input';
    container.innerHTML = `
        <input type="text" id="barcode-input" inputmode="numeric" 
               placeholder="Barcode eingeben" autocomplete="off"
               style="width:100%; padding:12px; font-size:1.2rem; border-radius:8px; border:1px solid #444; background:#1a1a2e; color:#eee;">
        <button id="barcode-submit" 
                style="width:100%; margin-top:8px; padding:12px; font-size:1rem; border-radius:8px; background:#4caf50; color:#000; border:none; font-weight:600;">
            Bestätigen
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
