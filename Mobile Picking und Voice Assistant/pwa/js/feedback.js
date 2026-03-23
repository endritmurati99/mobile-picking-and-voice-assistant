/**
 * Haptisches und akustisches Feedback für Scan-Ereignisse.
 * Kein externes Asset — Web Audio API generiert Töne direkt.
 */

let audioCtx = null;

function getAudioContext() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    return audioCtx;
}

function beep(frequency, duration, type = 'sine', volume = 0.3) {
    try {
        const ctx = getAudioContext();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = type;
        osc.frequency.setValueAtTime(frequency, ctx.currentTime);
        gain.gain.setValueAtTime(volume, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration / 1000);
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + duration / 1000);
    } catch {}
}

function vibrate(pattern) {
    if ('vibrate' in navigator) navigator.vibrate(pattern);
}

/** Erfolg: heller Doppel-Piep + kurze Vibration */
export function feedbackSuccess() {
    beep(880, 100);
    setTimeout(() => beep(1100, 150), 120);
    vibrate([50, 30, 50]);
}

/** Fehler: tiefer Brummton + lange Vibration */
export function feedbackError() {
    beep(180, 400, 'square', 0.4);
    vibrate([200, 100, 200]);
}

/** Warnung / Prioritäts-Alarm: markante Tonfolge */
export function feedbackAlert() {
    beep(660, 150);
    setTimeout(() => beep(550, 150), 170);
    setTimeout(() => beep(660, 300), 340);
    vibrate([100, 50, 100, 50, 300]);
}
