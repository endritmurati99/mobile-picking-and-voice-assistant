/**
 * Kreuztest der Kanonisierung.
 *
 * Der Fingerprint entsteht in Python (Odoo) und wird in Node (n8n Signature
 * Gate) nachgerechnet. Weichen die beiden Seiten ab, antwortet
 * `api_accept_event` mit "Payload fingerprint mismatch" -- ein 409, der wie ein
 * Signaturfehler aussieht und stundenlang in die falsche Richtung fuehrt.
 *
 * Zwei Fixtures, zwei Builder: `envelope-canonical.json` stammt aus einem
 * echten Bau von `quality.alert.event.builder`, `envelope-shipment.json` aus
 * `shipment.event.builder` (Task 2). Beide muessen dieselbe Kanonisierungsregel
 * einhalten (SHA-256 ueber die exakten Bytes von `envelope_text`), deshalb
 * laeuft derselbe Testrumpf ueber beide.
 */
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

import {sha256Hex} from '../custom-nodes/n8n-nodes-pwr/dist/src/security/pwrSignature.js';

for (const fixtureName of ['envelope-canonical.json', 'envelope-shipment.json']) {
  test(`fingerprint parity: ${fixtureName}`, async (t) => {
    const fixture = JSON.parse(
      await readFile(new URL(`./fixtures/${fixtureName}`, import.meta.url), 'utf8'),
    );

    await t.test('the gate hashes exactly what Odoo fingerprinted', () => {
      const body = Buffer.from(fixture.envelope_text, 'utf8');
      assert.equal(sha256Hex(body), fixture.payload_fingerprint);
    });

    await t.test('a re-formatted serialisation breaks the fingerprint', () => {
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

    await t.test('the fingerprint is sensitive to a single changed byte', () => {
      const tampered = Buffer.from(
        fixture.envelope_text.replace('"schema_version":"v2"', '"schema_version":"v3"'),
        'utf8',
      );
      assert.notEqual(sha256Hex(tampered), fixture.payload_fingerprint);
    });
  });
}
