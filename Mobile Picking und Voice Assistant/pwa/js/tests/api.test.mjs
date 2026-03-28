import test from 'node:test';
import assert from 'node:assert/strict';

import {
    assistVoice,
    clearActivePicker,
    getCachedPickers,
    getPickings,
    recognizeVoice,
    setActivePicker,
    setCachedPickers,
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
        setActivePicker({ id: 7, name: 'Endrit Murati' });
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
            { id: 18, name: 'Endrit Murati' },
        ]);
        assert.deepEqual(getCachedPickers(), [
            { id: 17, name: 'Administrator' },
            { id: 18, name: 'Endrit Murati' },
        ]);
    } finally {
        global.localStorage = originalStorage;
    }
});
