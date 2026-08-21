import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const repoRoot = fileURLToPath(new URL('../../../', import.meta.url));
const pwaRoot = path.join(repoRoot, 'pwa');

function readBytes(relativePath) {
    return readFileSync(path.join(repoRoot, relativePath));
}

function assertWoff2(relativePath) {
    const bytes = readBytes(relativePath);
    assert.equal(bytes.subarray(0, 4).toString('ascii'), 'wOF2', `${relativePath} is not a valid WOFF2 file`);
}

function assertPng(relativePath, expectedSize) {
    const bytes = readBytes(relativePath);
    const pngSignature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
    assert.deepEqual([...bytes.subarray(0, 8)], pngSignature, `${relativePath} is not a PNG`);

    const width = bytes.readUInt32BE(16);
    const height = bytes.readUInt32BE(20);
    assert.equal(width, expectedSize.width, `${relativePath} width`);
    assert.equal(height, expectedSize.height, `${relativePath} height`);
}

test('service worker cache is bumped for the phone reliability release', () => {
    const sw = readFileSync(path.join(pwaRoot, 'sw.js'), 'utf8');
    assert.match(sw, /const CACHE_NAME = 'picking-v29';/);
});

test('active voice button has a filled high-contrast state', () => {
    const css = readFileSync(path.join(pwaRoot, 'css', 'app.css'), 'utf8');
    assert.match(css, /\.nav-btn--active\s*\{[^}]*background:\s*var\(--primary\)/s);
    assert.match(css, /\.nav-btn--active\s*\{[^}]*color:\s*var\(--primary-ink\)/s);
});

test('CSS font URLs point to valid bundled WOFF2 files', () => {
    const css = readFileSync(path.join(pwaRoot, 'css', 'app.css'), 'utf8');
    const fontPaths = [...css.matchAll(/url\(["']?\/?(fonts\/[^"')]+\.woff2)["']?\)/g)]
        .map((match) => path.join('pwa', match[1]));

    assert.ok(fontPaths.length > 0, 'expected at least one bundled WOFF2 URL');
    for (const fontPath of fontPaths) {
        assertWoff2(fontPath);
    }
});

test('all bundled WOFF2 font files are valid', () => {
    const fontFiles = readdirSync(path.join(pwaRoot, 'fonts'))
        .filter((fileName) => fileName.endsWith('.woff2'))
        .map((fileName) => path.join('pwa', 'fonts', fileName));

    assert.ok(fontFiles.length > 0, 'expected at least one bundled WOFF2 file');
    for (const fontFile of fontFiles) {
        assertWoff2(fontFile);
    }
});

test('manifest PNG icons are valid files with declared dimensions', () => {
    const manifest = JSON.parse(readFileSync(path.join(pwaRoot, 'manifest.json'), 'utf8'));
    const pngIcons = (manifest.icons || []).filter((icon) => icon.type === 'image/png');

    assert.ok(pngIcons.length > 0, 'expected at least one PNG icon in manifest');
    for (const icon of pngIcons) {
        const [widthText, heightText] = String(icon.sizes || '').split(/\s+/)[0].split('x');
        const relativePath = path.join('pwa', icon.src.replace(/^\//, ''));
        assertPng(relativePath, {
            width: Number(widthText),
            height: Number(heightText),
        });
    }
});
