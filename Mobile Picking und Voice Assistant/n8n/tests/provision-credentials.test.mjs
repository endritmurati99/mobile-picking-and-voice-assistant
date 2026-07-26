import {randomBytes, randomUUID} from 'node:crypto';
import test from 'node:test';
import assert from 'node:assert/strict';

import {
    buildDefinitions,
    indexCredentials,
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
