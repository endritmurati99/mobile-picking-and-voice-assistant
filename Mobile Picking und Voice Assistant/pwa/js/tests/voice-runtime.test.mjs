import test from 'node:test';
import assert from 'node:assert/strict';

import {
    VOICE_AUTOMATION_THRESHOLD,
    VOICE_UNCERTAIN_THRESHOLD,
    buildVoiceAssistPayload,
    buildVoiceRequestContext,
    classifyVoiceResult,
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
        classifyVoiceResult({ intent: 'confirm', confidence: VOICE_AUTOMATION_THRESHOLD }),
        { kind: 'recognized', canHandle: true, promptText: null },
    );

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

test('getVoiceStatusPresentation exposes the intended labels', () => {
    assert.deepEqual(getVoiceStatusPresentation('idle'), { label: 'Bereit', tone: 'idle' });
    assert.deepEqual(getVoiceStatusPresentation('recording'), { label: 'Hoert zu', tone: 'listening' });
    assert.deepEqual(getVoiceStatusPresentation('recognized'), { label: 'Erkannt', tone: 'recognized' });
    assert.deepEqual(getVoiceStatusPresentation('unknown'), { label: 'Unsicher', tone: 'uncertain' });
});
