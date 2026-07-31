import {randomBytes, randomUUID} from 'node:crypto';
import {chmod, mkdtemp, rm, symlink, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';

import {
    assertSecretFileSafe,
    buildDefinitions,
    indexCredentials,
    readSecretFile,
    resolveCredentialId,
} from '../scripts/provision-credentials.mjs';

// Test-only secret material generated fresh at runtime. Nothing
// secret-shaped (no fixed string, no fixed base64 blob) is ever committed:
// these values only ever exist in this process's memory.
const randomBase64Secret = () => randomBytes(32).toString('base64');
const randomOpaqueValue = () => randomUUID();

test('indexes credentials by exact name and type and rejects duplicates', () => {
    const index = indexCredentials([
        {id: 'id-1', name: 'pwr.v2.inbound-header', type: 'httpHeaderAuth'},
    ]);
    assert.equal(
        index.get('pwr.v2.inbound-header\0httpHeaderAuth')[0].id,
        'id-1',
    );
    assert.throws(
        () => resolveCredentialId(
            'pwr.v2.inbound-header',
            'httpHeaderAuth',
            new Map([[
                'pwr.v2.inbound-header\0httpHeaderAuth',
                [{id: 'a'}, {id: 'b'}],
            ]]),
        ),
        /duplicate/,
    );
});

test('preserves existing id and builds the three exact logical credentials', () => {
    const existing = new Map([[
        'pwr.v2.inbound-header\0httpHeaderAuth',
        [{id: 'stable-id'}],
    ]]);
    assert.equal(
        resolveCredentialId(
            'pwr.v2.inbound-header', 'httpHeaderAuth', existing,
        ),
        'stable-id',
    );
    const definitions = buildDefinitions({
        ids: {
            inboundHeader: 'stable-id',
            inboundHmac: randomOpaqueValue(),
            outboundHmac: randomOpaqueValue(),
        },
        nativeHeaderSecret: randomOpaqueValue(),
        backendToN8n: {
            activeKeyId: randomOpaqueValue(),
            activeSecretBase64: randomBase64Secret(),
            previousKeyId: '',
            previousSecretBase64: '',
        },
        n8nToBackend: {
            baseUrl: 'http://backend:8000',
            activeKeyId: randomOpaqueValue(),
            activeSecretBase64: randomBase64Secret(),
            legacyCallbackSecret: randomOpaqueValue(),
        },
    });
    assert.deepEqual(
        definitions.map(item => [item.name, item.type]),
        [
            ['pwr.v2.inbound-header', 'httpHeaderAuth'],
            ['pwr.v2.backend-to-n8n-hmac', 'pwrInboundHmac'],
            ['pwr.v2.n8n-to-backend-hmac', 'pwrOutboundHmac'],
        ],
    );
});

test('resolveCredentialId generates a fresh id when nothing exists yet', () => {
    const id = resolveCredentialId('pwr.v2.inbound-header', 'httpHeaderAuth', new Map());
    assert.equal(typeof id, 'string');
    assert.ok(id.length > 0);
});

// ---------------------------------------------------------------------------
// readSecretFile: the ONLY permission check that counts. The host-side check
// in infrastructure/scripts/provision-n8n-credentials.sh inspects a different
// file with the same name in a different namespace; this one sits immediately
// before the read, inside the container.
// ---------------------------------------------------------------------------

test('readSecretFile reads a 0600 regular file owned by the runtime user', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'pwr-secret-ok-'));
    try {
        const path = join(dir, 'secret');
        await writeFile(path, ' opaque-value \n', {mode: 0o600});
        await chmod(path, 0o600);
        assert.equal(await readSecretFile(path), 'opaque-value');
    } finally {
        await rm(dir, {recursive: true, force: true});
    }
});

test('readSecretFile treats a missing file as absent, not as an error', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'pwr-secret-missing-'));
    try {
        assert.equal(await readSecretFile(join(dir, 'nope')), '');
    } finally {
        await rm(dir, {recursive: true, force: true});
    }
});

test('readSecretFile refuses a group- or world-accessible secret', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'pwr-secret-mode-'));
    try {
        const path = join(dir, 'secret');
        await writeFile(path, randomOpaqueValue(), {mode: 0o600});
        await chmod(path, 0o644);
        await assert.rejects(
            () => readSecretFile(path),
            /must have no group or other permission bits/,
        );
    } finally {
        await rm(dir, {recursive: true, force: true});
    }
});

test('readSecretFile refuses a symlink even when its target looks fine', async () => {
    // The target is a perfectly good 0600 file we own, so nothing about the
    // CONTENT is wrong -- only the indirection is. Following the link is
    // what lets an attacker with write access to the secret directory
    // repoint it at any file the runtime user may read. O_NOFOLLOW makes
    // that fail at open(), before any check the attacker could outrace.
    const dir = await mkdtemp(join(tmpdir(), 'pwr-secret-symlink-'));
    try {
        const target = join(dir, 'target');
        const link = join(dir, 'secret');
        await writeFile(target, randomOpaqueValue(), {mode: 0o600});
        await chmod(target, 0o600);
        await symlink(target, link);
        await assert.rejects(() => readSecretFile(link), /not a regular file/);
    } finally {
        await rm(dir, {recursive: true, force: true});
    }
});


// --- assertSecretFileSafe: the three assertions, in isolation --------------
// No root and no real file needed -- a synthetic stat-like object drives
// every branch, including the ownership one. `process.getuid` is a writable
// property, so the uid branch is reachable by shifting the runtime's own uid
// rather than by creating a foreign-owned file.

const statLike = (overrides = {}) => ({
    isFile: () => true,
    mode: 0o100600,
    uid: process.getuid(),
    ...overrides,
});

test('assertSecretFileSafe accepts a 0600 regular file owned by the runtime user', () => {
    assert.doesNotThrow(() => assertSecretFileSafe(statLike(), '/run/secrets/x'));
});

test('assertSecretFileSafe rejects anything that is not a regular file', () => {
    assert.throws(
        () => assertSecretFileSafe(statLike({isFile: () => false}), '/run/secrets/x'),
        /not a regular file/,
    );
});

test('assertSecretFileSafe rejects group- and world-accessible modes', () => {
    for (const mode of [0o100640, 0o100604, 0o100666, 0o100610, 0o100601]) {
        assert.throws(
            () => assertSecretFileSafe(statLike({mode}), '/run/secrets/x'),
            /must have no group or other permission bits/,
            `mode ${mode.toString(8)} must be rejected`,
        );
    }
});

test('assertSecretFileSafe rejects a file owned by another user', () => {
    const realGetuid = process.getuid;
    process.getuid = () => realGetuid() + 1;
    try {
        assert.throws(
            () => assertSecretFileSafe(statLike({uid: realGetuid()}), '/run/secrets/x'),
            /must be owned by the account that reads it/,
        );
    } finally {
        process.getuid = realGetuid;
    }
});

test('readSecretFile resolves the path exactly once, with O_NOFOLLOW', () => {
    // TOCTOU: resolving by path for the check and again for the read leaves
    // a window in which an attacker with write access to the secret
    // directory swaps the regular 0600 file for a symlink -- the very door
    // rejecting symlinks was meant to close. The fix is structural: open
    // once with O_NOFOLLOW (so a symlink fails at open, before any check it
    // could outrace) and then use only that descriptor, so fstat and read
    // necessarily see the same object.
    //
    // This is asserted on the function's SOURCE, deliberately. A timing-based
    // version of this test was written first and thrown away: reverting the
    // implementation to lstat-then-readFile-by-path left it green, because
    // the two lookups complete before a test can interleave anything between
    // them. A race the test cannot reliably win is not a regression test --
    // it is a coin flip that reads like one. The property here is structural,
    // so it is checked structurally.
    const source = readSecretFile.toString();
    assert.match(source, /O_NOFOLLOW/, 'must open with O_NOFOLLOW');
    assert.match(source, /handle\.stat\(\)/, 'must fstat the open descriptor');
    assert.match(source, /handle\.readFile\(/, 'must read from the open descriptor');
    assert.doesNotMatch(
        source, /\breadFile\(path\b/,
        'must never re-resolve the path for the read',
    );
    assert.doesNotMatch(
        source, /\b(?:lstat|stat)\(path\b/,
        'must never resolve the path a second time for the check',
    );
});
