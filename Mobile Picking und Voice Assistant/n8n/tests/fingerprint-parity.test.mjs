/**
 * Kreuztest der Kanonisierung.
 *
 * Der Fingerprint entsteht in Python (Odoo) und wird in Node (n8n Signature
 * Gate) nachgerechnet. Weichen die beiden Seiten ab, antwortet
 * `api_accept_event` mit "Payload fingerprint mismatch" -- ein 409, der wie ein
 * Signaturfehler aussieht und stundenlang in die falsche Richtung fuehrt.
 * Die Fixture stammt aus einem echten Bau von `quality.alert.event.builder`.
 */
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

import {sha256Hex} from '../custom-nodes/n8n-nodes-pwr/dist/src/security/pwrSignature.js';

const fixture = JSON.parse(
  readFileSync(new URL('./fixtures/envelope-canonical.json', import.meta.url), 'utf8'),
);

test('the gate hashes exactly what Odoo fingerprinted', () => {
  const body = Buffer.from(fixture.envelope_text, 'utf8');
  assert.equal(sha256Hex(body), fixture.payload_fingerprint);
});

test('a re-formatted serialisation breaks the fingerprint', () => {
  // Warum der Workflow den empfangenen Rumpf NIE neu serialisieren darf.
  //
  // Achtung, gemessen: fuer DIESEN Envelope liefert
  // `JSON.stringify(JSON.parse(text))` zufaellig dieselben Bytes -- die
  // Schluessel sind bereits sortiert, es gibt keine Fliesskommazahlen, und JS
  // setzt wie Python keine Leerzeichen. Das ist Glueck, keine Garantie: eine
  // Zahl wie 1.0 (Python "1.0", JS "1") oder eine andere Schluesselreihenfolge
  // kippt es sofort. Deshalb behauptet dieser Test die schwaechere, aber wahre
  // Aussage -- der Hash haengt an den exakten Bytes, nicht an der Struktur.
  const reformatted = Buffer.from(
    JSON.stringify(JSON.parse(fixture.envelope_text), null, 1),
    'utf8',
  );
  assert.notEqual(
    createHash('sha256').update(reformatted).digest('hex'),
    fixture.payload_fingerprint,
  );
});

test('the fingerprint is sensitive to a single changed byte', () => {
  const tampered = Buffer.from(
    fixture.envelope_text.replace('"priority":"1"', '"priority":"2"'),
    'utf8',
  );
  assert.notEqual(sha256Hex(tampered), fixture.payload_fingerprint);
});
