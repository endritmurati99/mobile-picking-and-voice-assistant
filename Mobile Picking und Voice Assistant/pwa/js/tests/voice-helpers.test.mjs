import test from 'node:test';
import assert from 'node:assert/strict';

import {
    POST_TTS_COOLDOWN_MS,
    VOICE_STATES,
    isLikelyPromptEcho,
    normalizePromptText,
    transitionVoiceState,
} from '../voice-helpers.mjs';

test('normalizePromptText strips punctuation and compacts whitespace', () => {
    assert.equal(
        normalizePromptText('A-12. 5 Stueck. Bremsscheibe.'),
        'a 12 5 stueck bremsscheibe',
    );
});

test('isLikelyPromptEcho detects transcripts that mirror the last prompt', () => {
    assert.equal(
        isLikelyPromptEcho('a 12 5 stueck bremsscheibe', 'A-12. 5 Stueck. Bremsscheibe.'),
        true,
    );
    assert.equal(
        isLikelyPromptEcho('bestaetigen', 'A-12. 5 Stueck. Bremsscheibe.'),
        false,
    );
});

test('transitionVoiceState follows the intended cycle', () => {
    let state = VOICE_STATES.IDLE;
    state = transitionVoiceState(state, 'activate', { voiceModeActive: true });
    assert.equal(state, VOICE_STATES.LISTENING);

    state = transitionVoiceState(state, 'speech-start', { voiceModeActive: true });
    assert.equal(state, VOICE_STATES.RECORDING);

    state = transitionVoiceState(state, 'tts-start', { voiceModeActive: true });
    assert.equal(state, VOICE_STATES.SPEAKING);

    state = transitionVoiceState(state, 'tts-end', { voiceModeActive: true });
    assert.equal(state, VOICE_STATES.COOLDOWN);

    state = transitionVoiceState(state, 'cooldown-end', { voiceModeActive: true });
    assert.equal(state, VOICE_STATES.LISTENING);

    state = transitionVoiceState(state, 'cooldown-end', { voiceModeActive: false });
    assert.equal(state, VOICE_STATES.IDLE);
});

test('cooldown remains conservative enough for post-TTS gating', () => {
    assert.equal(POST_TTS_COOLDOWN_MS, 900);
});
