import assert from 'node:assert/strict';
import test from 'node:test';

class Element {
    constructor() {
        this.children = [];
        this.classList = { add() {}, remove() {}, toggle() {} };
        this.dataset = {};
        this.style = { setProperty() {} };
    }

    addEventListener() {}
    appendChild(child) { this.children.push(child); }
    querySelector() { return null; }
    querySelectorAll() { return []; }
    setAttribute() {}
    toggleAttribute() {}
}

test('header renders both warehouses from the public instance list when /api/instances is 404', async () => {
    const original = {
        document: global.document,
        fetch: global.fetch,
        localStorage: global.localStorage,
        navigator: Object.getOwnPropertyDescriptor(global, 'navigator'),
        window: global.window,
    };
    const select = new Element();
    const main = new Element();
    const requests = [];
    const elements = new Map([['instance-switch', select], ['main', main]]);

    global.document = {
        body: new Element(),
        documentElement: new Element(),
        addEventListener() {},
        createElement() { return new Element(); },
        getElementById(id) { return elements.get(id) || null; },
        querySelector() { return null; },
        querySelectorAll() { return []; },
    };
    global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
    Object.defineProperty(global, 'navigator', {
        configurable: true,
        value: { onLine: true },
    });
    global.window = { _app: {}, addEventListener() {}, clearTimeout() {}, setTimeout() {} };
    global.fetch = async (url) => {
        requests.push(url);
        if (url === '/api/instances') {
            return { ok: false, status: 404, json: async () => ({ detail: 'Not Found' }) };
        }
        if (url === '/api/auth/instances') {
            return {
                ok: true,
                status: 200,
                json: async () => ([
                    { name: 'local', display_name: 'Lager 1' },
                    { name: 'lager2', display_name: 'Lager 2' },
                ]),
            };
        }
        if (url === '/api/health/live') return { ok: true, status: 200, json: async () => ({}) };
        return { ok: false, status: 401, json: async () => ({ detail: 'Nicht angemeldet' }) };
    };

    try {
        const appUrl = new URL('../app.js', import.meta.url);
        await import(`${appUrl.href}?instance-switch-test=${Date.now()}`);
        for (let attempt = 0; attempt < 10 && select.children.length < 2; attempt += 1) {
            await new Promise(resolve => setImmediate(resolve));
        }
    } finally {
        global.document = original.document;
        global.fetch = original.fetch;
        global.localStorage = original.localStorage;
        if (original.navigator) Object.defineProperty(global, 'navigator', original.navigator);
        else delete global.navigator;
        global.window = original.window;
    }

    assert.deepEqual(select.children.map(option => option.textContent), ['Lager 1', 'Lager 2']);
    assert.deepEqual(requests, ['/api/health/live', '/api/auth/instances', '/api/auth/me', '/api/auth/instances']);
});
