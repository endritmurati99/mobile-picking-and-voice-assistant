// Unified threshold model (frontend owns the act/read-back decision).
// VOICE_ACT_THRESHOLD: minimum to act on a non-write intent / to consider a
// write for read-back. VOICE_CONFIRM_DIRECT_THRESHOLD: a single confirm books
// directly only at/above this; below it (down to the act threshold) it asks
// for a read-back first. This closes the old [0.73, 0.78) dead band.
export const VOICE_ACT_THRESHOLD = 0.73;
export const VOICE_CONFIRM_DIRECT_THRESHOLD = 0.90;
export const VOICE_UNCERTAIN_THRESHOLD = 0.55;
export const WRITE_INTENTS = new Set(['confirm', 'confirm_all', 'submit_alert']);

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
    // Natuerliche Anweisung statt roboterhafter Komma-Liste "Produkt, Menge,
    // Ort". Der Picker braucht die Information in der Reihenfolge, in der er sie
    // ausfuehrt: erst WOHIN gehen, dann WAS holen.
    const pick = [qty, product].filter(Boolean).join(' ');
    if (loc && pick) return `Gehe zu ${loc} und hole ${pick}.`;
    if (loc) return `Gehe zu ${loc}.`;
    return pick ? `Hole ${pick}.` : '';
}

export function buildReadbackPrompt(intent, { line, remainingCount } = {}) {
    if (intent === 'submit_alert') {
        return 'Qualitätsmeldung absenden?';
    }
    if (intent === 'confirm_all') {
        return `${remainingCount ?? 0} Positionen buchen?`;
    }
    const product = line?.ui_display || line?.product_short_name || line?.product_name || 'Position';
    return `${product}, richtig?`;
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
        || (WRITE_INTENTS.has(intent) && confidence < VOICE_CONFIRM_DIRECT_THRESHOLD)) {
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

// Ergebnis einer Buchung ueber handleScan. Der Aufrufer darf nie aus dem
// blossen Zuruecklaufen der Funktion auf Erfolg schliessen: handleScan endet
// an vierzehn Stellen, und nur drei davon haben tatsaechlich gebucht.
export const SCAN_OUTCOME = {
    NO_LINE: 'no_line',
    STOCK_CHECKING: 'stock_checking',
    OUT_OF_STOCK: 'out_of_stock',
    WRONG_BARCODE: 'wrong_barcode',
    SERIAL_CANCELLED: 'serial_cancelled',
    REJECTED: 'rejected',
    BOOKED: 'booked',
    ABORTED: 'aborted',
    CONFLICT: 'conflict',
    NETWORK_ERROR: 'network_error',
};

// Was der Sprachpfad nach einer Buchung noch sagen muss.
//
// Ein leerer String heisst: nichts sagen. Entweder hat handleScan die Lage
// bereits angesagt -- dann wuerde ein weiterer Satz die wahre Meldung
// abschneiden, denn speak() bricht die laufende Ansage ab -- oder der
// Benutzer hat selbst abgebrochen und braucht keine Erklaerung dafuer.
//
// Ein unbekanntes Ergebnis faellt bewusst auf eine Verneinung, nicht auf
// Schweigen und erst recht nicht auf eine Erfolgsmeldung.
export function describeScanOutcome(status) {
    switch (status) {
        case SCAN_OUTCOME.WRONG_BARCODE:
        case SCAN_OUTCOME.REJECTED:
        case SCAN_OUTCOME.BOOKED:
        case SCAN_OUTCOME.CONFLICT:
        case SCAN_OUTCOME.NETWORK_ERROR:
        case SCAN_OUTCOME.ABORTED:
            return '';
        case SCAN_OUTCOME.NO_LINE:
            return 'Keine Position offen.';
        case SCAN_OUTCOME.STOCK_CHECKING:
            return 'Bestand wird noch geprüft.';
        case SCAN_OUTCOME.OUT_OF_STOCK:
            return 'Kein Bestand.';
        case SCAN_OUTCOME.SERIAL_CANCELLED:
            return 'Abgebrochen.';
        default:
            return 'Nicht gebucht.';
    }
}
