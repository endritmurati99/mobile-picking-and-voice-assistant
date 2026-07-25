import test from 'node:test';
import assert from 'node:assert/strict';

import {
    VOICE_ACT_THRESHOLD,
    VOICE_CONFIRM_DIRECT_THRESHOLD,
    VOICE_UNCERTAIN_THRESHOLD,
    buildSpeechPrompt,
    buildVoiceAssistPayload,
    buildVoiceRequestContext,
    classifyVoiceResult,
    formatLocationForSpeech,
    getVoiceStatusPresentation,
} from '../voice-runtime.mjs';

test('buildVoiceRequestContext derives detail context from the active line', () => {
    const context = buildVoiceRequestContext({
        view: 'detail',
        currentPicking: {
            move_lines: [{ id: 1 }, { id: 2 }, { id: 3 }],
        },
        currentLineIndex: 1,
    });

    assert.deepEqual(context, {
        context: 'awaiting_command',
        surface: 'detail',
        remaining_line_count: 1,
        active_line_present: true,
    });
});

test('buildVoiceRequestContext maps non-detail views to safe surfaces', () => {
    assert.deepEqual(
        buildVoiceRequestContext({
            view: 'list',
            currentPicking: null,
            currentLineIndex: 0,
        }),
        {
            context: 'idle',
            surface: 'list',
            remaining_line_count: 0,
            active_line_present: false,
        },
    );

    assert.deepEqual(
        buildVoiceRequestContext({
            view: 'alert',
            currentPicking: { move_lines: [{ id: 1 }] },
            currentLineIndex: 0,
        }),
        {
            context: 'awaiting_command',
            surface: 'quality_alert',
            remaining_line_count: 0,
            active_line_present: true,
        },
    );
});

test('buildVoiceAssistPayload reuses the active line and derived surface', () => {
    const payload = buildVoiceAssistPayload({
        result: { text: 'noch da', intent: 'stock_query' },
        view: 'detail',
        currentPicking: {
            id: 44,
            move_lines: [
                { id: 20, product_id: 5, location_src_id: 9 },
                { id: 21, product_id: 6, location_src_id: 10 },
            ],
        },
        currentLineIndex: 1,
    });

    assert.deepEqual(payload, {
        text: 'noch da',
        intent: 'stock_query',
        surface: 'detail',
        picking_id: 44,
        move_line_id: 21,
        product_id: 6,
        location_id: 10,
        remaining_line_count: 0,
    });
});

test('classifyVoiceResult gates low confidence results', () => {
    assert.deepEqual(
        classifyVoiceResult({ intent: 'confirm', confidence: 0.6 }),
        {
            kind: 'uncertain',
            canHandle: false,
            promptText: 'Unsicher, bitte wiederholen oder tippen.',
        },
    );

    assert.deepEqual(
        classifyVoiceResult({ intent: 'unknown', confidence: VOICE_UNCERTAIN_THRESHOLD }),
        { kind: 'unknown', canHandle: false, promptText: null },
    );
});

test('confirm_all always needs read-back even at high confidence', () => {
    const c = classifyVoiceResult({ intent: 'confirm_all', confidence: 0.99 });
    assert.equal(c.kind, 'readback');
    assert.equal(c.canHandle, false);
});

test('single confirm books directly at/above direct threshold', () => {
    const c = classifyVoiceResult({ intent: 'confirm', confidence: VOICE_CONFIRM_DIRECT_THRESHOLD });
    assert.equal(c.kind, 'recognized');
    assert.equal(c.canHandle, true);
});

test('single confirm in mid band needs read-back', () => {
    const c = classifyVoiceResult({ intent: 'confirm', confidence: 0.80 });
    assert.equal(c.kind, 'readback');
    assert.equal(c.canHandle, false);
});

test('non-write intent acts from the act threshold (no dead band)', () => {
    const c = classifyVoiceResult({ intent: 'next', confidence: VOICE_ACT_THRESHOLD });
    assert.equal(c.kind, 'recognized');
    assert.equal(c.canHandle, true);
});

test('speech prompt is product, qty, short location', () => {
    const line = { product_short_name: 'Pink Brick', quantity_demand: 2, location_src_zone: 'Regal 3' };
    assert.equal(buildSpeechPrompt(line), 'Pink Brick, 2 Stück, Regal 3');
});

test('location never spells out a raw fach code digit by digit', () => {
    const line = { product_short_name: 'Pink Brick', quantity_demand: 1, location_src: 'WH/Stock/A3-8848' };
    const spoken = buildSpeechPrompt(line);
    assert.ok(!/8 8 4 8/.test(spoken), spoken);
    assert.ok(!/A 3 8848/.test(spoken), spoken);
});

test('voice_instruction_short wins when present', () => {
    const line = { voice_instruction_short: 'Pink Brick holen', product_short_name: 'x', location_src_zone: 'Regal 3' };
    assert.equal(buildSpeechPrompt(line), 'Pink Brick holen');
});

test('formatLocationForSpeech prefers a clean zone label', () => {
    assert.equal(formatLocationForSpeech({ location_src_zone: 'Regal 3' }), 'Regal 3');
});

test('getVoiceStatusPresentation exposes the intended labels', () => {
    assert.deepEqual(getVoiceStatusPresentation('idle'), { label: 'Bereit', tone: 'idle' });
    assert.deepEqual(getVoiceStatusPresentation('recording'), { label: 'Hört zu', tone: 'listening' });
    assert.deepEqual(getVoiceStatusPresentation('recognized'), { label: 'Erkannt', tone: 'recognized' });
    assert.deepEqual(getVoiceStatusPresentation('unknown'), { label: 'Unsicher', tone: 'uncertain' });
});
