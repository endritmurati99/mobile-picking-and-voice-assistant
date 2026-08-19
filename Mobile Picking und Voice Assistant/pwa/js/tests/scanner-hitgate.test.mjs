/**
 * Der Scanner darf nicht zugreifen, bevor der Benutzer gezielt hat.
 *
 * Am Geraet beobachtet (19.08.2026): auf einem A4-Blatt mit mehreren Codes
 * nebeneinander buchte der Scanner sofort einen Nachbarcode, waehrend der
 * Benutzer noch fokussierte.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { createHitGate } from '../scanner.js';

function taktgeber(start = 0) {
    let jetzt = start;
    return {
        now: () => jetzt,
        vor: (ms) => { jetzt += ms; },
    };
}

test('waehrend der Sperrfrist wird nichts angenommen', () => {
    const t = taktgeber();
    const gate = createHitGate({ armDelayMs: 500, confirmHits: 1, now: t.now });

    assert.equal(gate.offer('343701'), false, 'sofort nach dem Oeffnen');
    t.vor(499);
    assert.equal(gate.offer('343701'), false, 'kurz vor Ablauf');
    t.vor(2);
    assert.equal(gate.offer('343701'), true, 'nach Ablauf');
});

test('ein einzelner Treffer genuegt nicht, zwei gleiche schon', () => {
    const t = taktgeber();
    const gate = createHitGate({ armDelayMs: 0, confirmHits: 2, now: t.now });

    assert.equal(gate.offer('4166960'), false, 'erster Durchlauf');
    assert.equal(gate.offer('4166960'), true, 'zweiter Durchlauf, gleicher Wert');
});

test('ein anderer Wert setzt die Bestaetigung zurueck', () => {
    const gate = createHitGate({ armDelayMs: 0, confirmHits: 2, now: () => 0 });

    assert.equal(gate.offer('4166960'), false);
    assert.equal(gate.offer('6269088'), false, 'Nachbarcode wandert durchs Bild');
    assert.equal(gate.offer('4166960'), false, 'der erste faengt von vorn an');
    assert.equal(gate.offer('4166960'), true);
});

test('ein leerer Durchlauf setzt zurueck', () => {
    const gate = createHitGate({ armDelayMs: 0, confirmHits: 2, now: () => 0 });

    assert.equal(gate.offer('343701'), false);
    assert.equal(gate.offer(''), false, 'Code kurz aus dem Rahmen');
    assert.equal(gate.offer('343701'), false, 'Zaehler beginnt neu');
    assert.equal(gate.offer('343701'), true);
});

test('reset() verwirft den Kandidaten', () => {
    const gate = createHitGate({ armDelayMs: 0, confirmHits: 2, now: () => 0 });

    assert.equal(gate.offer('CLUSTER-B1/WH/OUT/00047'), false);
    gate.reset();
    assert.equal(gate.offer('CLUSTER-B1/WH/OUT/00047'), false, 'nach reset wieder bei eins');
    assert.equal(gate.offer('CLUSTER-B1/WH/OUT/00047'), true);
});

test('der Scanner sucht ausschliesslich im Rahmen', async () => {
    const { readFile } = await import('node:fs/promises');
    const quelle = await readFile(new URL('../scanner.js', import.meta.url), 'utf8');

    assert.ok(
        !/tick\s*%\s*4/.test(quelle),
        'der Vollbild-Durchlauf jedes vierten Takts muss weg sein -- er griff den Nachbarcode',
    );
    assert.ok(
        quelle.includes('currentRegion()'),
        'beide Erkennungswege muessen denselben Rahmenausschnitt benutzen',
    );
});
