export const VOICE_AUTOMATION_THRESHOLD = 0.78;
export const VOICE_UNCERTAIN_THRESHOLD = 0.55;

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

export function classifyVoiceResult(result) {
    const confidence = Number(result?.confidence ?? 0);

    if (!result || result.intent === 'error') {
        return { kind: 'error', canHandle: false, promptText: null };
    }

    if (result.intent === 'unknown' || confidence < VOICE_UNCERTAIN_THRESHOLD) {
        return { kind: 'unknown', canHandle: false, promptText: null };
    }

    if (confidence < VOICE_AUTOMATION_THRESHOLD) {
        return {
            kind: 'uncertain',
            canHandle: false,
            promptText: 'Unsicher, bitte wiederholen oder tippen.',
        };
    }

    return { kind: 'recognized', canHandle: true, promptText: null };
}

export function getVoiceStatusPresentation(kind) {
    switch (kind) {
        case 'listening':
        case 'recording':
            return { label: 'Hoert zu', tone: 'listening' };
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
