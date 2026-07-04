import test from 'node:test';
import assert from 'node:assert/strict';

import {
    assistVoice,
    clearActivePicker,
    getActiveInstance,
    getCachedPickers,
    getInstances,
    getPickings,
    getTraceabilityDemo,
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

test('assistVoice sends a JSON payload with picker headers', async () => {
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
    assert.equal(capturedHeaders['X-Picker-User-Id'], '7');
    assert.deepEqual(JSON.parse(capturedBody), {
        text: 'Was baue ich hier?',
        intent: 'unknown',
        surface: 'detail',
        picking_id: 7,
    });
});

test('getPickings sends the active picker id as read header', async () => {
    const originalFetch = global.fetch;
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
        setActivePicker({ id: 18, name: 'Max Picker' });
        await getPickings();
    } finally {
        clearActivePicker();
        global.fetch = originalFetch;
    }

    assert.equal(capturedHeaders['X-Picker-User-Id'], '18');
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

test('request adds X-Odoo-Instance only when a non-local instance is active', async () => {
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
        await getPickings();
        assert.equal(getActiveInstance(), 'local');
        assert.equal(capturedHeaders['X-Odoo-Instance'], undefined);

        setActiveInstance('LogiLab');
        await getPickings();
        assert.equal(getActiveInstance(), 'logilab');
        assert.equal(capturedHeaders['X-Odoo-Instance'], 'logilab');

        setActiveInstance('local');
        await getPickings();
        assert.equal(getActiveInstance(), 'local');
        assert.equal(capturedHeaders['X-Odoo-Instance'], undefined);
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

test('traceability demo endpoints include instance, picker, and idempotency headers', async () => {
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
        assert.equal(calls[0].options.headers['X-Picker-User-Id'], '23');
        assert.equal(calls[0].options.headers['X-Odoo-Instance'], 'o19-trial');

        assert.equal(calls[1].url, '/api/demo/traceability');
        assert.equal(calls[1].options.method, 'POST');
        assert.equal(calls[1].options.headers['Idempotency-Key'], 'demo-key');
        assert.equal(calls[1].options.headers['X-Picker-User-Id'], '23');
        assert.equal(calls[1].options.headers['X-Odoo-Instance'], 'o19-trial');
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
