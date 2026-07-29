import {randomBytes, randomUUID} from 'node:crypto';
import {chmod, mkdtemp, rm, symlink, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';

import {
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
            /group- or world-accessible/,
        );
    } finally {
        await rm(dir, {recursive: true, force: true});
    }
});

test('readSecretFile refuses a symlink even when its target looks fine', async () => {
    // This is precisely why the check must use lstat and not stat: with
    // stat, the symlink would report the TARGET's mode (0600, ours) and
    // sail through, while the link itself is the thing an attacker can
    // repoint at any file the runtime user may read.
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
