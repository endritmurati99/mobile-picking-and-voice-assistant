export const VOICE_STATES = Object.freeze({
    IDLE: 'idle',
    LISTENING: 'listening',
    RECORDING: 'recording',
    SPEAKING: 'speaking',
    COOLDOWN: 'cooldown',
});

// 250 statt 500 ms: nach der Ansage war das Mikro eine halbe Sekunde taub, und
// wer sofort auf den Prompt antwortete, dessen Kommando wurde verworfen ("vorne
// nicht geklappt"). 250 ms reicht, damit der TTS-Ausklang (mit aktiver
// echoCancellation) nicht als Sprache zaehlt, laesst aber die natuerliche,
// unmittelbare Antwort durch.
export const POST_TTS_COOLDOWN_MS = 250;
// Bleibt bei 24 -- der Plan sah 60 vor, um die langsame Piper-Synthese zu
// umgehen. Die Ursache war aber nicht Piper, sondern die gewaehlte
// Qualitaetsstufe: thorsten-HIGH brauchte 1857 ms fuer eine Zeilenansage,
// thorsten-MEDIUM braucht 280 ms bei gleicher Samplerate und gleichem Sprecher
// (siehe piper/Dockerfile). Damit ist der Grund fuer die Anhebung entfallen und
// die natuerliche Stimme bleibt auch fuer kurze Ansagen erhalten. Nur sehr
// kurze Quittungen ("Fertig.") laufen weiter ueber die 80-ms-Browser-Stimme.
const PIPER_MIN_TEXT_LENGTH = 24;

export function normalizePromptText(text) {
    return String(text || '')
        .toLowerCase()
        .replace(/ä/g, 'ae')
        .replace(/ö/g, 'oe')
        .replace(/ü/g, 'ue')
        .replace(/ß/g, 'ss')
        .normalize('NFKD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/[^a-z0-9]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

// Einwort-Antworten, die als Reaktion auf eine Rueckfrage gemeint sind und
// deshalb NIE als Echo verworfen werden duerfen. Der Read-back-Prompt lautet
// "<Produkt>, richtig?" -- die Teilstring-Regel unten hat die Antwort "richtig"
// darin wiedergefunden und die komplette Sprachrunde weggeworfen. Der Nutzer
// antwortete korrekt, und es passierte nichts.
const CONFIRMATION_TOKENS = new Set([
    'ja', 'jawohl', 'genau', 'richtig', 'stimmt', 'klar', 'buchen', 'ok', 'okay',
    'nein', 'abbrechen', 'stopp', 'stop',
]);

export function isLikelyPromptEcho(transcript, prompt) {
    const transcriptNorm = normalizePromptText(transcript);
    const promptNorm = normalizePromptText(prompt);

    if (!transcriptNorm || !promptNorm || transcriptNorm.length < 6) {
        return false;
    }

    if (transcriptNorm === promptNorm) {
        return true;
    }

    // Ein einzelnes Bestaetigungs-/Abbruchwort ist eine Antwort, kein Echo --
    // auch dann, wenn der Prompt dasselbe Wort enthaelt. Die Token-Overlap-
    // Heuristik weiter unten bleibt als eigentliche Echo-Absicherung bestehen.
    if (!transcriptNorm.includes(' ') && CONFIRMATION_TOKENS.has(transcriptNorm)) {
        return false;
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

export function shouldUsePiperTts(text) {
    const normalized = String(text || '').replace(/\s+/g, ' ').trim();
    if (!normalized) return false;
    return normalized.length > PIPER_MIN_TEXT_LENGTH;
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
