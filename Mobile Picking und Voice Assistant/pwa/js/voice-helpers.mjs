export const VOICE_STATES = Object.freeze({
    IDLE: 'idle',
    LISTENING: 'listening',
    RECORDING: 'recording',
    SPEAKING: 'speaking',
    COOLDOWN: 'cooldown',
});

export const POST_TTS_COOLDOWN_MS = 900;

export function normalizePromptText(text) {
    return String(text || '')
        .toLowerCase()
        .normalize('NFKD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/[^a-z0-9]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

export function isLikelyPromptEcho(transcript, prompt) {
    const transcriptNorm = normalizePromptText(transcript);
    const promptNorm = normalizePromptText(prompt);

    if (!transcriptNorm || !promptNorm || transcriptNorm.length < 6) {
        return false;
    }

    if (transcriptNorm === promptNorm) {
        return true;
    }

    if (promptNorm.includes(transcriptNorm) || transcriptNorm.includes(promptNorm)) {
        return true;
    }

    const transcriptTokens = [...new Set(transcriptNorm.split(' ').filter(Boolean))];
    const promptTokens = [...new Set(promptNorm.split(' ').filter(Boolean))];

    if (transcriptTokens.length < 2 || promptTokens.length < 2) {
        return false;
    }

    let overlap = 0;
    for (const token of transcriptTokens) {
        if (promptTokens.includes(token)) overlap += 1;
    }

    const transcriptCoverage = overlap / transcriptTokens.length;
    const promptCoverage = overlap / promptTokens.length;

    return transcriptCoverage >= 0.75 || (transcriptCoverage >= 0.6 && promptCoverage >= 0.4);
}

export function transitionVoiceState(currentState, event, { voiceModeActive = true } = {}) {
    switch (event) {
        case 'activate':
        case 'capture-start':
            return voiceModeActive ? VOICE_STATES.LISTENING : VOICE_STATES.IDLE;
        case 'speech-start':
            return VOICE_STATES.RECORDING;
        case 'tts-start':
            return VOICE_STATES.SPEAKING;
        case 'tts-end':
            return VOICE_STATES.COOLDOWN;
        case 'cooldown-end':
            return voiceModeActive ? VOICE_STATES.LISTENING : VOICE_STATES.IDLE;
        case 'deactivate':
        default:
            return VOICE_STATES.IDLE;
    }
}
