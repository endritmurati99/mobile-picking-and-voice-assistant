/**
 * Prueft die Scanner-Auswahllogik und die Offline-Zusagen der eingebetteten
 * Barcode-Bibliothek -- ohne Browser, damit es in `node --test` mitlaeuft.
 *
 * Hintergrund: unter iOS gibt es in KEINEM Browser einen `BarcodeDetector`
 * (alle benutzen WebKit). Ohne Fallback zeigt der Scanner dort nur ein
 * Kamerabild und erkennt nie etwas.
 */
import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import {
    computeRoi,
    isBarcodeDetectorAvailable,
    selectScanEngine,
} from '../scanner.js';

const repoRoot = fileURLToPath(new URL('../../../', import.meta.url));
const pwaRoot = path.join(repoRoot, 'pwa');
const scannerSource = readFileSync(path.join(pwaRoot, 'js', 'scanner.js'), 'utf8');
const swSource = readFileSync(path.join(pwaRoot, 'sw.js'), 'utf8');

// --- Auswahllogik --------------------------------------------------------

test('BarcodeDetector vorhanden -> nativer Erkenner wird gewaehlt', () => {
    const scope = { BarcodeDetector: class {} };
    assert.equal(selectScanEngine(scope), 'barcode-detector');
});

test('BarcodeDetector fehlt (iOS/WebKit) -> zxing-wasm wird gewaehlt', () => {
    assert.equal(selectScanEngine({}), 'zxing-wasm');
});

test('BarcodeDetector nur als Attrappe (kein Konstruktor) -> zxing-wasm', () => {
    for (const bogus of [undefined, null, false, 0, '', 'BarcodeDetector', {}]) {
        assert.equal(
            selectScanEngine({ BarcodeDetector: bogus }),
            'zxing-wasm',
            `BarcodeDetector=${String(bogus)} darf nicht als nutzbar gelten`,
        );
    }
});

test('ohne Argument wird globalThis geprueft (Node hat keinen BarcodeDetector)', () => {
    assert.equal('BarcodeDetector' in globalThis, false);
    assert.equal(selectScanEngine(), 'zxing-wasm');
    assert.equal(isBarcodeDetectorAvailable(), false);

    globalThis.BarcodeDetector = class {};
    try {
        assert.equal(selectScanEngine(), 'barcode-detector');
        assert.equal(isBarcodeDetectorAvailable(), true);
    } finally {
        delete globalThis.BarcodeDetector;
    }
    assert.equal(selectScanEngine(), 'zxing-wasm');
});

// --- Bildausschnitt (object-fit: cover) ----------------------------------

test('computeRoi schneidet den Rahmen mittig aus und bleibt im Videobild', () => {
    // Video 1920x1080, Anzeige 390x700 (iPhone hochkant), Rahmen 260x130 CSS-px.
    // cover -> scale = max(390/1920, 700/1080) = 0.6481..
    const roi = computeRoi({
        videoWidth: 1920, videoHeight: 1080,
        displayWidth: 390, displayHeight: 700,
        boxWidth: 260, boxHeight: 130,
    });
    const scale = Math.max(390 / 1920, 700 / 1080);
    assert.equal(roi.sw, Math.round((260 / scale) * 1.36));
    assert.equal(roi.sh, Math.round((130 / scale) * 1.36));
    // mittig
    assert.equal(roi.sx, Math.round((1920 - roi.sw) / 2));
    assert.equal(roi.sy, Math.round((1080 - roi.sh) / 2));
    // im Bild
    assert.ok(roi.sx >= 0 && roi.sy >= 0);
    assert.ok(roi.sx + roi.sw <= 1920);
    assert.ok(roi.sy + roi.sh <= 1080);
    // und deutlich kleiner als das Vollbild -- sonst bringt der Ausschnitt nichts
    assert.ok(roi.sw * roi.sh < 1920 * 1080 * 0.6);
});

test('computeRoi klemmt einen zu grossen Rahmen auf die Videogroesse', () => {
    const roi = computeRoi({
        videoWidth: 640, videoHeight: 480,
        displayWidth: 640, displayHeight: 480,
        boxWidth: 5000, boxHeight: 5000,
    });
    assert.deepEqual(roi, { sx: 0, sy: 0, sw: 640, sh: 480 });
});

test('computeRoi faellt bei unbekannter Videogroesse auf das Vollbild zurueck', () => {
    assert.deepEqual(
        computeRoi({ videoWidth: 0, videoHeight: 0, displayWidth: 0, displayHeight: 0, boxWidth: 260, boxHeight: 130 }),
        { sx: 0, sy: 0, sw: 0, sh: 0 },
    );
});

// --- Offline-Zusagen -----------------------------------------------------

test('die Bibliothek liegt eingebettet im Projekt', () => {
    const files = [
        'vendor/zxing/reader/index.js',
        'vendor/zxing/share.js',
        'vendor/zxing/zxing_reader.wasm',
        'vendor/zxing/LICENSE',
    ];
    for (const rel of files) {
        const full = path.join(pwaRoot, rel);
        assert.ok(statSync(full).size > 0, `${rel} fehlt oder ist leer`);
    }
    // gueltiges WebAssembly-Modul: Magic \0asm + Version 1
    const wasm = readFileSync(path.join(pwaRoot, 'vendor/zxing/zxing_reader.wasm'));
    assert.deepEqual([...wasm.subarray(0, 8)], [0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00]);
});

test('scanner.js laedt die Bibliothek dynamisch, nicht statisch', () => {
    // Ein statisches `import ... from '../vendor/...'` wuerde die 1,1 MB auch auf
    // Android-Geraeten holen, die den nativen BarcodeDetector haben.
    assert.match(scannerSource, /await import\(/);
    assert.doesNotMatch(scannerSource, /^\s*import\s[^(]*vendor/m);
    assert.match(scannerSource, /\.\.\/vendor\/zxing\/reader\/index\.js/);
    assert.match(scannerSource, /\.\.\/vendor\/zxing\/zxing_reader\.wasm/);
});

test('kein CDN im Scanner-Pfad -- das Lager-WLAN hat kein Internet', () => {
    assert.doesNotMatch(scannerSource, /https?:\/\/(?!github\.com)/);
    // Der locateFile-Override ist die einzige Bremse gegen den jsDelivr-Default
    // der Bibliothek. Faellt er weg, scannt das iPhone im Lager gar nicht mehr.
    assert.match(scannerSource, /locateFile/);
});

test('der Service Worker cacht die Bibliothek und wurde hochgezaehlt', () => {
    for (const asset of [
        '/vendor/zxing/reader/index.js',
        '/vendor/zxing/share.js',
        '/vendor/zxing/zxing_reader.wasm',
    ]) {
        assert.ok(swSource.includes(`'${asset}'`), `${asset} fehlt im PRECACHE`);
    }
    const version = swSource.match(/const CACHE_NAME = 'picking-v(\d+)';/);
    assert.ok(version, 'CACHE_NAME nicht gefunden');
    assert.ok(
        Number(version[1]) >= 26,
        `CACHE_NAME steht auf v${version[1]} -- ohne Bump behalten iPhones die alte scanner.js`,
    );
});
