import test from 'node:test';
import assert from 'node:assert/strict';

import {
    assistVoice,
    clearActivePicker,
    confirmLine,
    getActiveInstance,
    getCachedPickers,
    getInstances,
    getPickings,
    getTraceabilityDemo,
    loginPickerSession,
    recognizeVoice,
    setActivePicker,
    setActiveInstance,
    setCachedPickers,
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

test('picker catalog cache round-trips through localStorage', () => {
    const store = new Map();
    const originalStorage = global.localStorage;
    global.localStorage = {
        getItem(key) { return store.has(key) ? store.get(key) : null; },
        setItem(key, value) { store.set(key, value); },
        removeItem(key) { store.delete(key); },
    };

    try {
        setCachedPickers([
            { id: 17, name: 'Administrator' },
            { id: 18, name: 'Lena Lager' },
        ]);
        assert.deepEqual(getCachedPickers(), [
            { id: 17, name: 'Administrator' },
            { id: 18, name: 'Lena Lager' },
        ]);
    } finally {
        global.localStorage = originalStorage;
    }
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

test('getInstances requests GET /instances', async () => {
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
        const list = await getInstances();
        assert.equal(capturedUrl, '/api/instances');
        assert.deepEqual(list, [{ name: 'local', display_name: 'Lokal' }]);
    } finally {
        global.fetch = originalFetch;
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
