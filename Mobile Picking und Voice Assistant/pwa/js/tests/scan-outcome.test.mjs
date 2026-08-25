import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { SCAN_OUTCOME, describeScanOutcome } from '../voice-runtime.mjs';

const jsDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const appSrc = readFileSync(path.join(jsDir, 'app.js'), 'utf8');

// Jede Buchung endet in genau einem dieser Ergebnisse. Fehlt eines, kann
// handleScan ein Ergebnis melden, fuer das keine Ansage hinterlegt ist.
const ALL = [
    'no_line', 'stock_checking', 'out_of_stock', 'wrong_barcode',
    'serial_cancelled', 'rejected', 'booked', 'aborted',
    'conflict', 'network_error',
];

test('SCAN_OUTCOME kennt jedes Ergebnis von handleScan', () => {
    assert.deepEqual(Object.values(SCAN_OUTCOME).sort(), [...ALL].sort());
});

test('describeScanOutcome schweigt, wenn handleScan bereits gesprochen hat', () => {
    for (const status of ['wrong_barcode', 'rejected', 'booked', 'conflict', 'network_error']) {
        assert.equal(describeScanOutcome(status), '', `${status} darf nicht doppelt angesagt werden`);
    }
});

test('describeScanOutcome schweigt beim Abbruch durch den Benutzer', () => {
    assert.equal(describeScanOutcome('aborted'), '');
});

test('describeScanOutcome nennt den Grund, wenn handleScan stumm abbricht', () => {
    for (const status of ['no_line', 'stock_checking', 'out_of_stock', 'serial_cancelled']) {
        const sentence = describeScanOutcome(status);
        assert.ok(sentence.length > 0, `${status} darf nicht stumm bleiben`);
        assert.doesNotMatch(sentence, /gebucht/i, `${status} darf keine Buchung behaupten`);
    }
});

test('describeScanOutcome verneint bei unbekanntem Ergebnis', () => {
    // Kein Schweigen und keine Erfolgsmeldung: ein Ergebnis, das niemand
    // vorgesehen hat, ist keine Buchung.
    assert.match(describeScanOutcome('irgendwas'), /nicht/i);
});

// Regressionsschutz fuer den Kern des Fehlers: der Sprachpfad sagte
// "Gebucht." unabhaengig davon, ob gebucht wurde -- und weil speak() die
// laufende Ansage abbricht, ueberschrieb dieses Wort sogar die wahre
// Fehlermeldung aus handleScan.
test('app.js behauptet nach handleScan keine Buchung mehr', () => {
    assert.doesNotMatch(appSrc, /speak\(\s*['"]Gebucht\.?['"]\s*\)/);
});

test('app.js verwirft kein handleScan-Ergebnis im Sprachpfad', () => {
    // Ein `await handleScan(...)` als eigenstaendige Anweisung wirft das
    // Ergebnis weg -- genau daraus entstand die falsche Erfolgsmeldung.
    const discarded = appSrc
        .split('\n')
        .filter((zeile) => /^\s*await handleScan\(/.test(zeile));
    assert.deepEqual(discarded, []);
});

test('app.js wertet handleScan-Ergebnisse ueber describeScanOutcome aus', () => {
    assert.ok(appSrc.includes('describeScanOutcome('));
    assert.ok(appSrc.includes('SCAN_OUTCOME'));
});
