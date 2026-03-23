/**
 * Voice-Modul: TTS + Audio-Recording mit Voice-Toggle-Modus.
 *
 * ARCHITEKTUR:
 * - TTS: SpeechSynthesis (Browser-nativ)
 * - STT: MediaRecorder → Backend → Whisper
 *
 * VOICE-MODUS:
 * - Toggle per Mic-Button oder Taste 'M'
 * - Mikrofon wird während TTS stummgeschaltet (kein Feedback-Loop)
 * - Fester Sprach-Schwellwert (kein Kalibrierungs-Overhead)
 * - Schnelle Stille-Erkennung (400ms nach Sprach-Ende)
 */
import { recognizeVoice } from './api.js';

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

// Voice-Toggle
let voiceModeActive = false;
let audioContext = null;
let analyser = null;
let micStream = null;
let monitorInterval = null;
let ttsBusy = false;

// Schwellwerte (fest, kein Kalibrieren nötig)
const SPEECH_RMS = 25;           // RMS über 25 = Sprache (Rauschen liegt bei 5-15)
const SILENCE_AFTER_SPEECH = 400; // ms Stille nach Sprache → stoppen
const NO_SPEECH_TIMEOUT = 6000;  // ms ohne Sprache → Neustart
const MIN_SPEECH_MS = 150;       // Mindest-Sprechdauer
const MAX_RECORDING_MS = 10000;  // Sicherheits-Timeout
const CHECK_MS = 30;             // Monitor-Intervall

let onIntentCallback = null;
let onModeChangeCallback = null;

// ── Voice-Auswahl ────────────────────────────────────────────
// Lädt deutsche Stimmen asynchron und bevorzugt Enhanced-Qualität.
let _cachedDeVoice = null;

function _loadBestDeVoice() {
    const voices = window.speechSynthesis.getVoices();
    const deVoices = voices.filter(v => v.lang.startsWith('de'));
    if (!deVoices.length) return null;
    // Priorität: 1) Markus/Anna Enhanced, 2) beliebig Enhanced, 3) Markus/Anna Compact, 4) kein Eloquence
    const preferred = ['markus', 'anna'];
    const byName = deVoices.find(v =>
        preferred.some(n => v.name.toLowerCase().includes(n)) &&
        /enhanced/i.test(v.name)
    );
    const anyEnhanced = deVoices.find(v => /enhanced|premium/i.test(v.name) && !/eloquence/i.test(v.name));
    const byNameAny = deVoices.find(v => preferred.some(n => v.name.toLowerCase().includes(n)));
    const noEloquence = deVoices.find(v => !/eloquence|compact/i.test(v.name));
    return byName || anyEnhanced || byNameAny || noEloquence || deVoices[0];
}

if ('speechSynthesis' in window) {
    // iOS lädt Stimmen asynchron — beim voiceschanged-Event cachen
    window.speechSynthesis.addEventListener('voiceschanged', () => {
        _cachedDeVoice = _loadBestDeVoice();
    });
    // Sofort versuchen (Desktop-Browser haben Stimmen synchron verfügbar)
    _cachedDeVoice = _loadBestDeVoice();
}

// ── iOS TTS Unlock ───────────────────────────────────────────
// iOS Safari blocks speechSynthesis until the first speak() from a
// user gesture. We unlock on first touch and replay any queued text.
let _ttsUnlocked = false;
let _pendingSpeech = null;
function _unlockTTS() {
    if (_ttsUnlocked || !('speechSynthesis' in window)) return;
    _ttsUnlocked = true;
    // Dummy utterance to unlock the audio path
    const u = new SpeechSynthesisUtterance(' ');
    u.volume = 0.01;
    u.lang = 'de-DE';
    window.speechSynthesis.speak(u);
    // Replay queued speech after unlock
    if (_pendingSpeech) {
        const text = _pendingSpeech;
        _pendingSpeech = null;
        setTimeout(() => speak(text), 200);
    }
}
document.addEventListener('touchstart', _unlockTTS, { once: true, passive: true });
document.addEventListener('pointerdown', _unlockTTS, { once: true, passive: true });

// ── TTS ─────────────────────────────────────────────────────

export function speak(text) {
    return new Promise((resolve) => {
        if (!('speechSynthesis' in window)) { resolve(); return; }

        // iOS: queue speech until first user gesture unlocks TTS
        if (!_ttsUnlocked) {
            _pendingSpeech = text;
            resolve();
            return;
        }

        // Mikrofon stummschalten während TTS
        ttsBusy = true;
        muteMic(true);
        stopCurrentRecording();

        window.speechSynthesis.cancel();

        // iOS needs a tick after cancel() before the next speak() is accepted
        setTimeout(() => {
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = 'de-DE';
            utterance.rate = 1.1;
            utterance.pitch = 1.0;

            function done() {
                ttsBusy = false;
                muteMic(false);
                // Nach TTS: Aufnahme-Zyklus neu starten
                if (voiceModeActive) {
                    setTimeout(() => {
                        if (voiceModeActive && !isRecording && !ttsBusy) startListeningCycle();
                    }, 200);
                }
                resolve();
            }

            utterance.onend = done;
            utterance.onerror = done;

            const allVoices = window.speechSynthesis.getVoices();
            const deVoice = _cachedDeVoice || _loadBestDeVoice();
            if (deVoice) utterance.voice = deVoice;
            // DEBUG: Stimmen-Info in Konsole (kann später entfernt werden)
            const deNames = allVoices.filter(v => v.lang.startsWith('de')).map(v => v.name).join(' | ');
            console.log(`[TTS] Verfügbare DE-Stimmen: ${deNames}`);
            console.log(`[TTS] Gewählt: ${deVoice?.name ?? 'keine (Browser-Default)'}`);
            window.speechSynthesis.speak(utterance);
        }, 80);
    });
}

function muteMic(mute) {
    if (micStream) {
        micStream.getAudioTracks().forEach(t => { t.enabled = !mute; });
    }
}

function stopCurrentRecording() {
    stopMonitor();
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        try { mediaRecorder.stop(); } catch {}
    }
}

// ── RMS ─────────────────────────────────────────────────────

function getRMS() {
    if (!analyser) return 0;
    const buf = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    return Math.sqrt(sum / buf.length);
}

function stopMonitor() {
    if (monitorInterval) { clearInterval(monitorInterval); monitorInterval = null; }
}

// ── Voice-Toggle ────────────────────────────────────────────

export function toggleVoiceMode(onIntent, onModeChange, onError) {
    onIntentCallback = onIntent;
    onModeChangeCallback = onModeChange;
    if (voiceModeActive) deactivateVoiceMode();
    else activateVoiceMode(onError);
}

export function isVoiceModeActive() { return voiceModeActive; }

async function activateVoiceMode(onError) {
    if (voiceModeActive) return;
    try {
        // getUserMedia must be called as close to the user gesture as
        // possible. We await it directly here; callers must ensure this
        // function is invoked from within a click/pointerdown handler
        // without any intervening await before this line.
        micStream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 }
        });

        audioContext = new (window.AudioContext || window.webkitAudioContext)();

        // iOS Safari creates AudioContext in 'suspended' state even from
        // within a user-gesture frame. resume() must be called explicitly.
        if (audioContext.state === 'suspended') {
            await audioContext.resume();
        }

        analyser = audioContext.createAnalyser();
        analyser.fftSize = 512;
        audioContext.createMediaStreamSource(micStream).connect(analyser);

        voiceModeActive = true;
        if (onModeChangeCallback) onModeChangeCallback(true);

        // Wenn TTS gerade spricht, warte bis fertig
        if (!ttsBusy) startListeningCycle();
    } catch (e) {
        console.error('Mikrofon-Zugriff fehlgeschlagen:', e);
        voiceModeActive = false;
        if (onModeChangeCallback) onModeChangeCallback(false);
        if (onError) onError(e);
    }
}

function deactivateVoiceMode() {
    voiceModeActive = false;
    stopMonitor();
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        try { mediaRecorder.stop(); } catch {}
    }
    if (micStream) {
        micStream.getTracks().forEach(t => t.stop());
        micStream = null;
    }
    if (audioContext) {
        audioContext.close().catch(() => {});
        audioContext = null;
        analyser = null;
    }
    isRecording = false;
    if (onModeChangeCallback) onModeChangeCallback(false);
}

/**
 * Aufnahme-Zyklus:
 * 1. Aufnahme sofort starten (kein Kalibrieren)
 * 2. Warte auf Sprache (RMS > 25)
 * 3. Sprache erkannt → warte auf 400ms Stille → stoppen
 * 4. An Whisper senden
 * 5. Loop
 */
async function startListeningCycle() {
    if (!voiceModeActive || !micStream || ttsBusy) return;

    audioChunks = [];
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus' : 'audio/mp4';

    const recorder = new MediaRecorder(micStream, { mimeType });
    mediaRecorder = recorder;
    recorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data); };

    const blob = await new Promise((resolve) => {
        let speechMs = 0;
        let silenceStart = null;
        let hasSpeech = false;
        const t0 = Date.now();

        recorder.onstop = () => {
            isRecording = false;
            stopMonitor();
            if (ttsBusy || audioChunks.length === 0 || !hasSpeech || speechMs < MIN_SPEECH_MS) {
                resolve(null);
            } else {
                resolve(new Blob(audioChunks, { type: mimeType }));
            }
        };

        recorder.start(200);
        isRecording = true;

        monitorInterval = setInterval(() => {
            if (ttsBusy || !voiceModeActive || recorder.state !== 'recording') {
                stopMonitor();
                if (recorder.state === 'recording') recorder.stop();
                return;
            }

            const elapsed = Date.now() - t0;
            if (elapsed > MAX_RECORDING_MS) {
                stopMonitor(); recorder.stop(); return;
            }

            const rms = getRMS();

            if (rms > SPEECH_RMS) {
                hasSpeech = true;
                speechMs += CHECK_MS;
                silenceStart = null;
            } else if (hasSpeech) {
                if (!silenceStart) silenceStart = Date.now();
                else if (Date.now() - silenceStart > SILENCE_AFTER_SPEECH) {
                    console.log(`[Voice] Stille nach ${speechMs}ms → senden`);
                    stopMonitor(); recorder.stop(); return;
                }
            } else if (elapsed > NO_SPEECH_TIMEOUT) {
                stopMonitor(); recorder.stop(); return;
            }
        }, CHECK_MS);
    });

    if (!voiceModeActive || ttsBusy) return;

    if (blob) {
        console.log(`[Voice] ${blob.size} bytes → Whisper`);
        try {
            const result = await recognizeVoice(blob);
            console.log(`[Voice] "${result?.text}" → ${result?.intent}`);
            if (result && result.text && onIntentCallback) {
                onIntentCallback(result);
            }
        } catch (e) {
            console.error('[Voice] STT Fehler:', e);
        }
    }

    if (voiceModeActive && !ttsBusy) startListeningCycle();
}

// ── Legacy PTT ──────────────────────────────────────────────

export async function startRecording() {
    if (isRecording) return;
    const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 }
    });
    audioChunks = [];
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/mp4';
    mediaRecorder = new MediaRecorder(stream, { mimeType });
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data); };
    mediaRecorder.start();
    isRecording = true;
}

export function stopRecording() {
    return new Promise((resolve) => {
        if (!mediaRecorder || !isRecording) { resolve(null); return; }
        mediaRecorder.onstop = () => {
            const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType });
            mediaRecorder.stream.getTracks().forEach(t => t.stop());
            isRecording = false;
            resolve(blob);
        };
        mediaRecorder.stop();
    });
}

export async function captureAndRecognize() {
    await startRecording();
    return {
        stop: async () => {
            const blob = await stopRecording();
            if (!blob) return { intent: 'unknown', text: '', confidence: 0 };
            try { return await recognizeVoice(blob); }
            catch { return { intent: 'error', text: '', confidence: 0 }; }
        }
    };
}

export function stopSpeaking() {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
}

export function isVoiceSupported() {
    return 'mediaDevices' in navigator && 'getUserMedia' in navigator.mediaDevices;
}

export function stopVoiceMode() {
    if (voiceModeActive) deactivateVoiceMode();
}
