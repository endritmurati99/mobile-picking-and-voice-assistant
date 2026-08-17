// Regressionstest fuer die Bug-Klasse "Bezeichner benutzt, aber nicht
// importiert". app.js wird nirgends direkt geladen (kein DOM im node-Test),
// deshalb blieb der fehlende buildReadbackPrompt-Import lange unbemerkt und
// killte jeden Voice-confirm_all mit einer stillen ReferenceError.
//
// Dieser Test liest app.js als Quelltext, sammelt alle Namen, die aus den
// lokalen ES-Modulen importiert werden, und stellt sicher, dass jeder aus
// voice-runtime.mjs / voice-helpers.mjs stammende Bezeichner, der in app.js
// aufgerufen wird, auch tatsaechlich importiert ist.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const here = path.dirname(fileURLToPath(import.meta.url));
const jsDir = path.resolve(here, '..');
const appSrc = readFileSync(path.join(jsDir, 'app.js'), 'utf8');

// Alle benannten Importe aus lokalen ./*.mjs / ./*.js Modulen einsammeln.
function importedNames(src) {
    const names = new Set();
    const re = /import\s*\{([^}]*)\}\s*from\s*['"]\.\/[^'"]+['"]/g;
    let m;
    while ((m = re.exec(src)) !== null) {
        for (const raw of m[1].split(',')) {
            const name = raw.trim().split(/\s+as\s+/)[0].trim();
            if (name) names.add(name);
        }
    }
    return names;
}

test('app.js: buildReadbackPrompt ist importiert (Regressionsschutz Voice confirm_all)', () => {
    const names = importedNames(appSrc);
    assert.ok(
        names.has('buildReadbackPrompt'),
        'buildReadbackPrompt wird in app.js:2864 aufgerufen und MUSS aus voice-runtime.mjs importiert sein'
    );
});

test('app.js: jeder aus voice-runtime.mjs exportierte, in app.js aufgerufene Name ist importiert', () => {
    const runtimeSrc = readFileSync(path.join(jsDir, 'voice-runtime.mjs'), 'utf8');
    const exportRe = /export\s+(?:function|const)\s+([A-Za-z0-9_]+)/g;
    const imported = importedNames(appSrc);
    const missing = [];
    let m;
    while ((m = exportRe.exec(runtimeSrc)) !== null) {
        const name = m[1];
        // Wird der Name in app.js als Aufruf/Referenz benutzt?
        const used = new RegExp(`\\b${name}\\s*\\(`).test(appSrc);
        if (used && !imported.has(name)) missing.push(name);
    }
    assert.deepEqual(
        missing,
        [],
        `Diese aus voice-runtime.mjs stammenden Namen werden in app.js benutzt, aber nicht importiert: ${missing.join(', ')}`
    );
});
