// Unified threshold model (frontend owns the act/read-back decision).
// VOICE_ACT_THRESHOLD: minimum to act on a non-write intent / to consider a
// write for read-back. VOICE_CONFIRM_DIRECT_THRESHOLD: a single confirm books
// directly only at/above this; below it (down to the act threshold) it asks
// for a read-back first. This closes the old [0.73, 0.78) dead band.
export const VOICE_ACT_THRESHOLD = 0.73;
export const VOICE_CONFIRM_DIRECT_THRESHOLD = 0.90;
export const VOICE_UNCERTAIN_THRESHOLD = 0.55;
export const WRITE_INTENTS = new Set(['confirm', 'confirm_all']);

export function buildVoiceRequestContext({ view, currentPicking, currentLineIndex }) {
    const lines = currentPicking?.move_lines || [];
    const hasActiveLine = Boolean(currentPicking && currentLineIndex < lines.length);

    let surface = 'detail';
    switch (view) {
        case 'list':
        case 'picker':
        case 'locked':
            surface = 'list';
            break;
        case 'alert':
            surface = 'quality_alert';
            break;
        case 'complete':
            surface = 'complete';
            break;
        default:
            surface = 'detail';
            break;
    }

    return {
        context: hasActiveLine ? 'awaiting_command' : 'idle',
        surface,
        remaining_line_count: hasActiveLine
            ? Math.max(lines.length - currentLineIndex - 1, 0)
            : 0,
        active_line_present: hasActiveLine,
    };
}

export function buildVoiceAssistPayload({ result, view, currentPicking, currentLineIndex }) {
    const lines = currentPicking?.move_lines || [];
    const activeLine = currentPicking && currentLineIndex < lines.length
        ? lines[currentLineIndex]
        : null;
    const surface = buildVoiceRequestContext({
        view,
        currentPicking,
        currentLineIndex,
    }).surface;

    return {
        text: result?.text || '',
        intent: result?.intent || 'unknown',
        surface,
        picking_id: currentPicking?.id ?? null,
        move_line_id: activeLine?.id ?? null,
        product_id: activeLine?.product_id ?? null,
        location_id: activeLine?.location_src_id ?? null,
        remaining_line_count: activeLine
            ? Math.max(lines.length - currentLineIndex - 1, 0)
            : 0,
    };
}

export function formatLocationForSpeech(line) {
    // A human zone/short label ("Regal 3"), never a spelled-out fach code.
    // A token with a 3+ digit run is a raw code, not speakable — skip it.
    const zone = line?.location_src_zone;
    const short = line?.location_src_short;
    if (zone && !/\d{3,}/.test(zone)) return zone;
    if (short && !/\d{3,}/.test(short)) return short;
    // Only a raw code available: drop the location rather than read digits.
    return '';
}

export function buildSpeechPrompt(line) {
    if (!line) return '';
    if (line.voice_instruction_short) return line.voice_instruction_short;
    const product = line.ui_display || line.product_short_name || line.product_name || 'Produkt';
    const qty = line.quantity_demand != null ? `${line.quantity_demand} Stück` : '';
    const loc = formatLocationForSpeech(line);
    return [product, qty, loc].filter(Boolean).join(', ');
}

export function classifyVoiceResult(result) {
    const confidence = Number(result?.confidence ?? 0);
    const intent = result?.intent;

    if (!result || intent === 'error') {
        return { kind: 'error', canHandle: false, promptText: null };
    }

    if (intent === 'unknown' || confidence < VOICE_UNCERTAIN_THRESHOLD) {
        return { kind: 'unknown', canHandle: false, promptText: null };
    }

    if (confidence < VOICE_ACT_THRESHOLD) {
        return {
            kind: 'uncertain',
            canHandle: false,
            promptText: 'Unsicher, bitte wiederholen oder tippen.',
        };
    }

    // Write intents must be confirmed before booking: confirm_all always,
    // and a single confirm below the direct threshold. A misrecognition can
    // therefore never silently write to Odoo.
    if (intent === 'confirm_all'
        || (intent === 'confirm' && confidence < VOICE_CONFIRM_DIRECT_THRESHOLD)) {
        return { kind: 'readback', canHandle: false, promptText: null };
    }

    return { kind: 'recognized', canHandle: true, promptText: null };
}

export function getVoiceStatusPresentation(kind) {
    switch (kind) {
        case 'listening':
        case 'recording':
            return { label: 'Hört zu', tone: 'listening' };
        case 'speaking':
        case 'cooldown':
            return { label: 'Spricht', tone: 'speaking' };
        case 'recognized':
            return { label: 'Erkannt', tone: 'recognized' };
        case 'uncertain':
        case 'unknown':
        case 'error':
            return { label: 'Unsicher', tone: 'uncertain' };
        case 'idle':
        default:
            return { label: 'Bereit', tone: 'idle' };
    }
}
