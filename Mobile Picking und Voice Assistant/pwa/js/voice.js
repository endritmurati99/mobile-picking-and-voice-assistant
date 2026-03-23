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

// ── TTS ─────────────────────────────────────────────────────

export function speak(text) {
    return new Promise((resolve) => {
        if (!('speechSynthesis' in window)) { resolve(); return; }

        // Mikrofon stummschalten während TTS
        ttsBusy = true;
        muteMic(true);
        stopCurrentRecording();

        window.speechSynthesis.cancel();
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

        const voices = window.speechSynthesis.getVoices();
        const deVoice = voices.find(v => v.lang.startsWith('de'));
        if (deVoice) utterance.voice = deVoice;
        window.speechSynthesis.speak(utterance);
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

export function toggleVoiceMode(onIntent, onModeChange) {
    onIntentCallback = onIntent;
    onModeChangeCallback = onModeChange;
    if (voiceModeActive) deactivateVoiceMode();
    else activateVoiceMode();
}

export function isVoiceModeActive() { return voiceModeActive; }

async function activateVoiceMode() {
    if (voiceModeActive) return;
    try {
        micStream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1, sampleRate: 16000 }
        });
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
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
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1, sampleRate: 16000 }
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
