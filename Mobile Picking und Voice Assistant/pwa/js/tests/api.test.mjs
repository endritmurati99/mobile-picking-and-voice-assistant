import test from 'node:test';
import assert from 'node:assert/strict';

import {
    assistVoice,
    clearActivePicker,
    confirmClusterLine,
    confirmLine,
    getActiveInstance,
    getAuthInstances,
    getCurrentSession,
    getDeviceId,
    getPickings,
    getTraceabilityDemo,
    loginPickerSession,
    logoutPickerSession,
    recognizeVoice,
    setActivePicker,
    setActiveInstance,
    setTraceabilityDemoMode,
} from '../api.js';

test('recognizeVoice sends the UI context as additive form fields', async () => {
    const originalFetch = global.fetch;
    let capturedBody = null;

    global.fetch = async (_url, options) => {
        capturedBody = options.body;
        return {
            ok: true,
            status: 200,
            json: async () => ({ intent: 'confirm', text: 'ja', confidence: 0.95 }),
        };
    };

    try {
        const blob = new Blob(['voice'], { type: 'audio/webm' });
        await recognizeVoice(blob, {
            context: 'awaiting_command',
            surface: 'detail',
            remaining_line_count: 2,
            active_line_present: true,
        });
    } finally {
        global.fetch = originalFetch;
    }

    assert.ok(capturedBody instanceof FormData);
    assert.equal(capturedBody.get('context'), 'awaiting_command');
    assert.equal(capturedBody.get('surface'), 'detail');
    assert.equal(capturedBody.get('remaining_line_count'), '2');
    assert.equal(capturedBody.get('active_line_present'), 'true');
    assert.equal(capturedBody.get('audio').name, 'recording.webm');
});

test('recognizeVoice carries session CSRF, because the app-wide gate now refuses a bare POST', async () => {
    // Task 16: `/api/voice/recognize` sits behind the browser gate at router
    // inclusion. It used to send no headers at all and would take a 403. It is
    // in `route_policy.IDEMPOTENCY_EXEMPT_ROUTES`, so it must NOT send a key.
    const originalFetch = global.fetch;
    const originalSessionStorage = global.sessionStorage;
    const store = new Map([['picking-assistant-csrf', 'csrf-voice']]);
    global.sessionStorage = {
        getItem: key => store.get(key) ?? null,
        setItem: (key, value) => store.set(key, value),
        removeItem: key => store.delete(key),
    };
    let captured = null;
    global.fetch = async (url, options) => {
        captured = { url, options };
        return { ok: true, status: 200, json: async () => ({ intent: 'confirm' }) };
    };

    try {
        await recognizeVoice(new Blob(['voice'], { type: 'audio/webm' }));
    } finally {
        global.fetch = originalFetch;
        global.sessionStorage = originalSessionStorage;
    }

    assert.equal(captured.url, '/api/voice/recognize');
    assert.equal(captured.options.credentials, 'same-origin');
    assert.equal(captured.options.headers['X-CSRF-Token'], 'csrf-voice');
    assert.equal(captured.options.headers['Idempotency-Key'], undefined);
    // FormData must keep its own multipart boundary Content-Type.
    assert.equal(captured.options.headers['Content-Type'], undefined);
});

test('getAuthInstances uses the pre-auth instance list, not the dev-only router', async () => {
    // `/api/instances` lives on a router `create_app` does not include in
    // production, and it is behind the session gate anyway. A login screen that
    // reads it can never render before someone is already logged in.
    const originalFetch = global.fetch;
    let capturedUrl = null;
    global.fetch = async (url) => {
        capturedUrl = url;
        return {
            ok: true,
            status: 200,
            json: async () => ([{ name: 'local', display_name: 'Lokal' }]),
        };
    };
    try {
        const list = await getAuthInstances();
        assert.deepEqual(list, [{ name: 'local', display_name: 'Lokal' }]);
    } finally {
        global.fetch = originalFetch;
    }
    assert.equal(capturedUrl, '/api/auth/instances');
});

test('the device id stays a syntactic UUID without crypto.randomUUID', async () => {
    // `PickerSessionLoginRequest.device_id` is typed `UUID`; anything else is a
    // 422 and the login is simply impossible. `crypto.randomUUID` requires a
    // secure context, so this is the http:// LAN case.
    const originalCrypto = globalThis.crypto;
    const originalStorage = global.localStorage;
    const store = new Map();
    global.localStorage = {
        getItem(key) { return store.has(key) ? store.get(key) : null; },
        setItem(key, value) { store.set(key, value); },
        removeItem(key) { store.delete(key); },
    };
    Object.defineProperty(globalThis, 'crypto', {
        value: { getRandomValues: originalCrypto.getRandomValues.bind(originalCrypto) },
        configurable: true,
        writable: true,
    });

    try {
        const deviceId = getDeviceId();
        assert.match(
            deviceId,
            /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
        );
        // Stable across calls, or every request would look like a new device.
        assert.equal(getDeviceId(), deviceId);
    } finally {
        Object.defineProperty(globalThis, 'crypto', {
            value: originalCrypto,
            configurable: true,
            writable: true,
        });
        global.localStorage = originalStorage;
    }
});

test('logout sends the CSRF token, or the server keeps the session alive', async () => {
    const originalFetch = global.fetch;
    const originalSessionStorage = global.sessionStorage;
    const store = new Map([['picking-assistant-csrf', 'csrf-logout']]);
    global.sessionStorage = {
        getItem: key => store.get(key) ?? null,
        setItem: (key, value) => store.set(key, value),
        removeItem: key => store.delete(key),
    };
    let captured = null;
    global.fetch = async (url, options) => {
        captured = { url, options };
        return { ok: true, status: 204, json: async () => null };
    };
    try {
        await logoutPickerSession();
    } finally {
        global.fetch = originalFetch;
        global.sessionStorage = originalSessionStorage;
    }
    assert.equal(captured.url, '/api/auth/logout');
    assert.equal(captured.options.method, 'POST');
    assert.equal(captured.options.headers['X-CSRF-Token'], 'csrf-logout');
});

test('assistVoice sends a JSON payload without authority headers', async () => {
    const originalFetch = global.fetch;
    let capturedHeaders = null;
    let capturedBody = null;

    global.fetch = async (_url, options) => {
        capturedHeaders = options.headers;
        capturedBody = options.body;
        return {
            ok: true,
            status: 200,
            json: async () => ({
                status: 'ok',
                tts_text: 'Antwort',
                source: 'n8n',
                correlation_id: 'corr-1',
                latency_ms: 123,
            }),
        };
    };

    try {
        setActivePicker({ id: 7, name: 'Lena Lager' });
        await assistVoice({
            text: 'Was baue ich hier?',
            intent: 'unknown',
            surface: 'detail',
            picking_id: 7,
        });
    } finally {
        clearActivePicker();
        global.fetch = originalFetch;
    }

    assert.equal(capturedHeaders['Content-Type'], 'application/json');
    assert.equal(capturedHeaders['X-Picker-User-Id'], undefined);
    assert.equal(capturedHeaders['X-Device-Id'], undefined);
    assert.deepEqual(JSON.parse(capturedBody), {
        text: 'Was baue ich hier?',
        intent: 'unknown',
        surface: 'detail',
        picking_id: 7,
    });
});

test('authenticated reads send cookie credentials and no authority headers', async () => {
    const originalFetch = global.fetch;
    let captured = null;
    global.fetch = async (_url, options) => {
        captured = options;
        return { ok: true, status: 200, json: async () => [] };
    };
    try {
        setActivePicker({ id: 18, name: 'Max Picker' });
        setActiveInstance('logilab');
        await getPickings();
        assert.equal(captured.credentials, 'same-origin');
        assert.equal(captured.headers['X-Picker-User-Id'], undefined);
        assert.equal(captured.headers['X-Device-Id'], undefined);
        assert.equal(captured.headers['X-Odoo-Instance'], undefined);
    } finally {
        clearActivePicker();
        setActiveInstance('local');
        global.fetch = originalFetch;
    }
});

test('mutation uses csrf from sessionStorage and stable idempotency only', async () => {
    const originalFetch = global.fetch;
    const originalSessionStorage = global.sessionStorage;
    const store = new Map([['picking-assistant-csrf', 'csrf-1']]);
    global.sessionStorage = {
        getItem: key => store.get(key) ?? null,
        setItem: (key, value) => store.set(key, value),
        removeItem: key => store.delete(key),
    };
    let captured = null;
    global.fetch = async (_url, options) => {
        captured = options;
        return { ok: true, status: 200, json: async () => ({ success: true }) };
    };
    try {
        await confirmLine(4, { move_line_id: 9, quantity: 1 }, {
            idempotencyKey: 'confirm:4:9',
        });
        assert.equal(captured.headers['X-CSRF-Token'], 'csrf-1');
        assert.equal(captured.headers['Idempotency-Key'], 'confirm:4:9');
        assert.equal(captured.headers['X-Device-Id'], undefined);
    } finally {
        global.fetch = originalFetch;
        global.sessionStorage = originalSessionStorage;
    }
});

test('login sends device and selected instance then stores csrf in sessionStorage', async () => {
    const originalFetch = global.fetch;
    const originalSessionStorage = global.sessionStorage;
    const store = new Map();
    global.sessionStorage = {
        getItem: key => store.get(key) ?? null,
        setItem: (key, value) => store.set(key, value),
        removeItem: key => store.delete(key),
    };
    let requestBody;
    global.fetch = async (_url, options) => {
        requestBody = JSON.parse(options.body);
        return {
            ok: true,
            status: 200,
            json: async () => ({
                principal: {
                    picker_user_id: 7,
                    picker_name: 'Mina Muster',
                    device_id: requestBody.device_id,
                    odoo_instance: 'o19',
                    roles: ['picker'],
                    session_id: '4ddb2442-e58a-47fe-9a6f-1ec1d779ef88',
                    expires_at: '2026-07-23T20:00:00Z',
                },
                csrf_token: 'csrf-login',
            }),
        };
    };
    try {
        const session = await loginPickerSession({
            login: 'mina',
            password: 'secret',
            odoo_instance: 'o19',
        });
        assert.equal(requestBody.login, 'mina');
        assert.equal(requestBody.odoo_instance, 'o19');
        assert.ok(requestBody.device_id);
        assert.equal(requestBody.picker_user_id, undefined);
        assert.equal(store.get('picking-assistant-csrf'), 'csrf-login');
        assert.equal(session.principal.picker_user_id, 7);
    } finally {
        global.fetch = originalFetch;
        global.sessionStorage = originalSessionStorage;
    }
});

test('restored cookie session refreshes csrf before a cluster write', async () => {
    const originalFetch = global.fetch;
    const originalSessionStorage = global.sessionStorage;
    const store = new Map();
    global.sessionStorage = {
        getItem: key => store.get(key) ?? null,
        setItem: (key, value) => store.set(key, value),
        removeItem: key => store.delete(key),
    };
    const calls = [];
    global.fetch = async (url, options) => {
        calls.push({ url, options });
        if (url === '/api/auth/me') {
            return {
                ok: true,
                status: 200,
                json: async () => ({
                    picker_user_id: 5,
                    picker_name: 'Lena Lager',
                    device_id: '3f9a1c22-0000-4000-8000-0000000000ff',
                    odoo_instance: 'local',
                    roles: ['picker'],
                    session_id: '4ddb2442-e58a-47fe-9a6f-1ec1d779ef88',
                    expires_at: '2026-08-22T20:00:00Z',
                }),
            };
        }
        if (url === '/api/auth/csrf') {
            return { ok: true, status: 200, json: async () => ({ csrf_token: 'csrf-restored' }) };
        }
        return { ok: true, status: 200, json: async () => ({ success: true }) };
    };

    try {
        await getCurrentSession();
        await confirmClusterLine(14, {
            picking_id: 71,
            move_line_id: 485,
            scanned_barcode: '6023350',
            scanned_package: 'CLUSTER-B1/L1/OUT/00071',
            quantity: 2,
        }, { idempotencyKey: 'cluster-confirm-restored-session' });
    } finally {
        clearActivePicker();
        global.fetch = originalFetch;
        global.sessionStorage = originalSessionStorage;
    }

    assert.deepEqual(calls.map(call => call.url), [
        '/api/auth/me',
        '/api/auth/csrf',
        '/api/cluster/batches/14/confirm-line',
    ]);
    assert.equal(calls[2].options.headers['X-CSRF-Token'], 'csrf-restored');
});

test('getActiveInstance/setActiveInstance remain a pre-login selection preference only', async () => {
    // `request()` no longer injects `X-Odoo-Instance` -- the header carries no
    // authority once a session exists. `setActiveInstance`/`getActiveInstance`
    // still round-trip through localStorage so the login screen can preselect
    // an instance before a Principal exists.
    const originalFetch = global.fetch;
    const originalStorage = global.localStorage;
    const store = new Map();
    global.localStorage = {
        getItem(key) { return store.has(key) ? store.get(key) : null; },
        setItem(key, value) { store.set(key, value); },
        removeItem(key) { store.delete(key); },
    };

    let capturedHeaders = null;
    global.fetch = async (_url, options) => {
        capturedHeaders = options.headers;
        return {
            ok: true,
            status: 200,
            json: async () => ([]),
        };
    };

    try {
        assert.equal(getActiveInstance(), 'local');

        setActiveInstance('LogiLab');
        assert.equal(getActiveInstance(), 'logilab');
        await getPickings();
        assert.equal(capturedHeaders['X-Odoo-Instance'], undefined);

        setActiveInstance('local');
        assert.equal(getActiveInstance(), 'local');
    } finally {
        global.fetch = originalFetch;
        global.localStorage = originalStorage;
    }
});

test('traceability demo endpoints send cookie credentials and idempotency without authority headers', async () => {
    const originalFetch = global.fetch;
    const originalStorage = global.localStorage;
    const store = new Map();
    global.localStorage = {
        getItem(key) { return store.has(key) ? store.get(key) : null; },
        setItem(key, value) { store.set(key, value); },
        removeItem(key) { store.delete(key); },
    };

    const calls = [];
    global.fetch = async (url, options) => {
        calls.push({ url, options });
        return {
            ok: true,
            status: 200,
            json: async () => ({ enabled: true, mode: 'component_lot', modes: [] }),
        };
    };

    try {
        setActivePicker({ id: 23, name: 'Mira Picker' });
        setActiveInstance('o19-trial');

        await getTraceabilityDemo();
        await setTraceabilityDemoMode('none', { idempotencyKey: 'demo-key' });

        assert.equal(calls[0].url, '/api/demo/traceability');
        assert.equal(calls[0].options.method, 'GET');
        assert.equal(calls[0].options.credentials, 'same-origin');
        assert.equal(calls[0].options.headers['X-Picker-User-Id'], undefined);
        assert.equal(calls[0].options.headers['X-Odoo-Instance'], undefined);

        assert.equal(calls[1].url, '/api/demo/traceability');
        assert.equal(calls[1].options.method, 'POST');
        assert.equal(calls[1].options.headers['Idempotency-Key'], 'demo-key');
        assert.equal(calls[1].options.headers['X-Picker-User-Id'], undefined);
        assert.equal(calls[1].options.headers['X-Odoo-Instance'], undefined);
        assert.deepEqual(JSON.parse(calls[1].options.body), { mode: 'none' });
    } finally {
        clearActivePicker();
        setActiveInstance('local');
        global.fetch = originalFetch;
        global.localStorage = originalStorage;
    }
});

test('traceability demo endpoints use POST body without mutating local instance state', async () => {
    const originalFetch = global.fetch;
    let capturedBody = null;

    global.fetch = async (_url, options) => {
        capturedBody = options.body;
        return {
            ok: true,
            status: 200,
            json: async () => ({ mode: 'finished_lot' }),
        };
    };

    try {
        await setTraceabilityDemoMode('finished_lot');
        assert.deepEqual(JSON.parse(capturedBody), { mode: 'finished_lot' });
    } finally {
        global.fetch = originalFetch;
    }
});
