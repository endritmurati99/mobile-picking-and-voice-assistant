import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

const root = new URL('../..', import.meta.url);
const source = await fs.readFile(new URL('pwa/js/app.js', root), 'utf8');
const runtime = await fs.readFile(new URL('pwa/js/voice-runtime.mjs', root), 'utf8');

async function setup() {
    const elements = new Map();
    const element = (id) => {
        if (!elements.has(id)) elements.set(id, {
            hidden: true, textContent: '', dataset: {}, style: {}, inert: false,
            classList: { add() {}, remove() {}, toggle() {} },
            setAttribute() {}, removeAttribute() {}, focus() {},
            addEventListener(event, handler) { this[event] = handler; },
        });
        return elements.get(id);
    };
    const state = { currentPicking: { id: 7, move_lines: [
        { id: 71, product_barcode: 'A', quantity_demand: 1 },
        { id: 72, product_barcode: 'B', quantity_demand: 1 },
    ] }, currentLineIndex: 0, currentPicker: { id: 1 } };
    let resolveBooking;
    const calls = [];
    const speech = [];
    const timers = new Map();
    let timerId = 0;
    const noop = () => {};
    const overrides = {
        getState: () => state,
        setState: (patch) => Object.assign(state, patch),
        speak: async (text) => { speech.push(text); },
        getStoredSearchQuery: () => '',
        createIdempotencyKey: () => 'test-key',
        ApiError: class extends Error {},
        confirmLine: async (...args) => {
            calls.push(args);
            return new Promise((resolve) => { resolveBooking = resolve; });
        },
    };
    const window = {
        setTimeout: (fn) => { timers.set(++timerId, fn); return timerId; },
        clearTimeout: (id) => timers.delete(id), addEventListener: noop,
    };
    const context = vm.createContext({
        console, window, Date, AbortController,
        document: { getElementById: element, addEventListener: noop,
            body: { dataset: { view: 'detail' } }, querySelector: () => null },
        navigator: { onLine: true },
    });
    const dependencies = new Map();
    for (const match of source.matchAll(/import\s*\{([^}]+)\}\s*from\s*['"]([^'"]+)['"]/g)) {
        const names = match[1].split(',').map((name) => name.trim()).filter(Boolean);
        const module = match[2] === './voice-runtime.mjs'
            ? new vm.SourceTextModule(runtime, { context })
            : new vm.SyntheticModule(names, function () {
                for (const name of names) this.setExport(name, overrides[name] || noop);
            }, { context });
        await module.link(() => {});
        await module.evaluate();
        dependencies.set(match[2], module);
    }
    // Execute the real handlers; only page startup and unrelated rendering/RPC
    // boundaries are replaced. No implementation is copied into this test.
    const app = new vm.SourceTextModule(source.replace(/\ninit\(\);\s*$/, '\n') + `
        renderResponsiveCurrentLine = () => {};
        releaseCurrentClaim = async () => {};
        refreshActivePickingDetail = async () => {};
        if (typeof initVoiceActionPanel === 'function') initVoiceActionPanel();
        export { handleScan, handleVoiceIntent, triggerConfirmAll };
    `, { context });
    await app.link((specifier) => dependencies.get(specifier));
    await app.evaluate();
    return { app: app.namespace, state, element, calls, speech, timers,
        release: (response) => resolveBooking(response) };
}
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const bulk = { intent: 'confirm_all', text: 'alle bestätigen', confidence: 0.95 };
const yes = { intent: 'confirm', text: 'ja', confidence: 0.95 };

const t = await setup();
await t.app.handleVoiceIntent(bulk);
assert.equal(t.element('voice-action').hidden, false, 'readback remains visible');
assert.match(t.element('voice-action-text').textContent, /2 Positionen buchen/);
await t.app.handleScan('A');
assert.equal(t.calls.length, 0, 'scan cannot bypass an unanswered readback');
await t.element('voice-action-no').click();
assert.equal(t.element('voice-action').hidden, true, 'No dismisses without booking');
assert.equal(t.calls.length, 0);

await t.app.handleVoiceIntent(bulk);
const booking = t.element('voice-action-yes').click();
await flush();
assert.equal(t.calls.length, 1);
assert.match(t.element('voice-action-text').textContent, /1 von 2/);
await t.app.handleScan('A');
await t.app.handleVoiceIntent(yes);
await t.app.triggerConfirmAll();
assert.equal(t.calls.length, 1, 'bulk blocks competing scans, speech, and bulk');
t.release({ success: true, picking_complete: false });
await flush();
assert.equal(t.calls.length, 2);
assert.match(t.element('voice-action-text').textContent, /2 von 2/);
t.release({ success: true, picking_complete: true });
await booking;
assert.equal(t.element('voice-action').hidden, true);
assert.equal(t.state.currentLineIndex, 2);

const changed = await setup();
await changed.app.handleVoiceIntent(bulk);
changed.state.currentLineIndex = 1;
await changed.element('voice-action-yes').click();
assert.equal(changed.calls.length, 0, 'a confirmation is bound to its original position');

const expired = await setup();
await expired.app.handleVoiceIntent(bulk);
await flush();
// Fire the actual readback expiry callback, then deliver a late affirmative.
for (const callback of [...expired.timers.values()]) callback();
await expired.app.handleVoiceIntent(yes);
assert.equal(expired.calls.length, 0, 'late Yes must not become a new single booking');
assert.equal(expired.element('voice-action').hidden, true);
await expired.app.handleVoiceIntent({ ...yes, text: 'bestätigen' });
assert.equal(expired.calls.length, 0, 'fresh explicit command reopens readback without booking');
assert.equal(expired.element('voice-action').hidden, false);
await expired.element('voice-action-no').click();

const negative = await setup();
await negative.app.handleVoiceIntent(bulk);
await negative.app.handleVoiceIntent({ ...yes, text: 'ja, doch nicht' });
assert.equal(negative.calls.length, 0, 'negation wins over an affirmative');
assert.equal(negative.element('voice-action').hidden, true);

const single = await setup();
const first = single.app.handleScan('A');
await flush();
await single.app.handleScan('A');
await single.app.triggerConfirmAll();
assert.equal(single.calls.length, 1, 'single booking shares the same exclusion');
single.release({ success: false, message: 'Rejected' });
await first;
assert.equal(single.element('voice-action').hidden, true, 'failure releases booking UI');
console.log('voice action checks passed');
