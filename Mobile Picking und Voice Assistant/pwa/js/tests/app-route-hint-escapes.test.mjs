// Regressionstest fuer die Bug-Klasse "Odoo-Stammdaten ungeescaped in
// innerHTML". renderRouteHint (app.js) setzte Lagerplatz- und Zonennamen
// aus Odoo direkt in Template-Strings, waehrend jeder andere Renderpfad
// durch escapeHtml() laeuft. app.js laedt nicht im node-Test (DOM), deshalb
// wird die Funktion als Quelltext gelesen: jede Interpolation im Markup
// muss escapeHtml durchlaufen oder eine Zahl sein.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const here = path.dirname(fileURLToPath(import.meta.url));
const appSrc = readFileSync(path.resolve(here, '..', 'app.js'), 'utf8');

function functionSource(name) {
    const start = appSrc.indexOf(`function ${name}(`);
    assert.notEqual(start, -1, `${name} nicht in app.js gefunden`);
    const next = appSrc.indexOf('\nfunction ', start + 1);
    return appSrc.slice(start, next === -1 ? undefined : next);
}

test('renderRouteHint: Lagerplatz und Zonen aus Odoo werden escaped', () => {
    const src = functionSource('renderRouteHint');
    assert.match(src, /\$\{escapeHtml\(nextLocation\)\}/, 'nextLocation ohne escapeHtml');
    assert.match(src, /\$\{escapeHtml\(zone\)\}/, 'zone ohne escapeHtml');
    const exprs = [...src.matchAll(/\$\{([^}]*)\}/g)].map((m) => m[1].trim());
    const unguarded = exprs.filter((expr) =>
        !/^escapeHtml\(/.test(expr)
        && expr !== 'remainingLines.length'
        && expr !== 'remainingTravelScore'
        && !/^zonePreview\.map\(/.test(expr)
    );
    assert.deepEqual(unguarded, [], `ungeschuetzte Interpolationen: ${unguarded.join(' | ')}`);
});
