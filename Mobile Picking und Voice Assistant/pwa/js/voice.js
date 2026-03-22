/**
 * Voice-Modul: TTS (Browser) + Audio-Recording mit Voice-Toggle-Modus.
 *
 * ARCHITEKTUR-ENTSCHEIDUNG:
 * - TTS: SpeechSynthesis (Browser-nativ, funktioniert auf iOS + Android)
 * - STT: MediaRecorder → Backend → Whisper (NICHT Browser-SpeechRecognition!)
 *   Grund: SpeechRecognition funktioniert nicht in iOS PWA Standalone.
 *
 * VOICE-MODUS:
 * - Toggle per Mic-Button oder Taste 'M'
 * - Adaptive Stille-Erkennung: kalibriert sich auf Hintergrundlärm
 * - Nach Verarbeitung hört er automatisch wieder zu (Loop)
 */
import { recognizeVoice } from './api.js';

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

// Voice-Toggle-Modus
let voiceModeActive = false;
let audioContext = null;
let analyser = null;
let micStream = null;
let monitorRAF = null;

// Adaptive Stille-Erkennung
const SPEECH_MULTIPLIER = 2.0;   // Sprache = Grundrauschen × diesen Faktor
const SILENCE_DURATION = 1200;   // ms Stille nach Sprache bevor Aufnahme stoppt
const NO_SPEECH_TIMEOUT = 8000;  // ms ohne Sprache → Aufnahme verwerfen, neu starten
const MIN_SPEECH_MS = 300;       // Mindest-Sprechdauer damit Aufnahme gesendet wird
const MAX_RECORDING_MS = 15000;  // Max-Aufnahmezeit (Sicherheit)
const CALIBRATION_MS = 500;      // Kalibrierungszeit für Grundrauschen

// Callback für Intent-Ergebnisse (wird von app.js gesetzt)
let onIntentCallback = null;
let onModeChangeCallback = null;

// ── TTS ─────────────────────────────────────────────────────

export function speak(text) {
    return new Promise((resolve) => {
        if (!('speechSynthesis' in window)) {
            console.warn('SpeechSynthesis nicht verfügbar');
            resolve();
            return;
        }

        window.speechSynthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'de-DE';
        utterance.rate = 1.0;
        utterance.pitch = 1.0;
        utterance.onend = resolve;
        utterance.onerror = () => resolve();

        const voices = window.speechSynthesis.getVoices();
        const deVoice = voices.find(v => v.lang.startsWith('de'));
        if (deVoice) utterance.voice = deVoice;

        window.speechSynthesis.speak(utterance);
    });
}

// ── Voice-Toggle-Modus ──────────────────────────────────────

export function toggleVoiceMode(onIntent, onModeChange) {
    onIntentCallback = onIntent;
    onModeChangeCallback = onModeChange;

    if (voiceModeActive) {
        deactivateVoiceMode();
    } else {
        activateVoiceMode();
    }
}

export function isVoiceModeActive() {
    return voiceModeActive;
}

async function activateVoiceMode() {
    if (voiceModeActive) return;

    try {
        micStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                channelCount: 1,
                sampleRate: 16000,
            }
        });

        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 512;
        const source = audioContext.createMediaStreamSource(micStream);
        source.connect(analyser);

        voiceModeActive = true;
        if (onModeChangeCallback) onModeChangeCallback(true);

        startListeningCycle();
    } catch (e) {
        console.error('Mikrofon-Zugriff fehlgeschlagen:', e);
        voiceModeActive = false;
        if (onModeChangeCallback) onModeChangeCallback(false);
    }
}

function deactivateVoiceMode() {
    voiceModeActive = false;
    cancelAnimationFrame(monitorRAF);
    monitorRAF = null;

    if (mediaRecorder && isRecording) {
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
 * Misst das Grundrauschen über CALIBRATION_MS.
 * Gibt den Durchschnitt-RMS zurück.
 */
function calibrateNoise() {
    return new Promise((resolve) => {
        if (!analyser) { resolve(20); return; }

        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        const samples = [];
        const start = Date.now();

        function sample() {
            if (Date.now() - start > CALIBRATION_MS) {
                const avg = samples.length > 0
                    ? samples.reduce((a, b) => a + b) / samples.length
                    : 20;
                resolve(avg);
                return;
            }
            analyser.getByteFrequencyData(dataArray);
            let sum = 0;
            for (let i = 0; i < dataArray.length; i++) {
                sum += dataArray[i] * dataArray[i];
            }
            samples.push(Math.sqrt(sum / dataArray.length));
            requestAnimationFrame(sample);
        }
        sample();
    });
}

function getRMS() {
    if (!analyser) return 0;
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(dataArray);
    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) {
        sum += dataArray[i] * dataArray[i];
    }
    return Math.sqrt(sum / dataArray.length);
}

/**
 * Eine Aufnahme-Runde:
 * 1. Kalibriere Grundrauschen
 * 2. Warte auf Sprache (RMS > Grundrauschen × Faktor)
 * 3. Nimm auf bis Stille erkannt (RMS fällt zurück)
 * 4. Sende an Backend
 * 5. Loop
 */
async function startListeningCycle() {
    if (!voiceModeActive || !micStream) return;

    // Schritt 1: Grundrauschen kalibrieren
    const noiseFloor = await calibrateNoise();
    const speechThreshold = Math.max(noiseFloor * SPEECH_MULTIPLIER, noiseFloor + 10);

    console.log(`[Voice] Grundrauschen: ${noiseFloor.toFixed(1)}, Sprech-Schwelle: ${speechThreshold.toFixed(1)}`);

    if (!voiceModeActive) return;

    // Schritt 2: Warte auf Sprache
    const speechDetected = await waitForSpeech(speechThreshold);
    if (!speechDetected || !voiceModeActive) {
        if (voiceModeActive) startListeningCycle();
        return;
    }

    // Schritt 3: Aufnehmen bis Stille
    const blob = await recordUntilSilence(speechThreshold);
    if (!blob || !voiceModeActive) {
        if (voiceModeActive) startListeningCycle();
        return;
    }

    console.log(`[Voice] Aufnahme: ${blob.size} bytes`);

    // Schritt 4: An Backend senden
    try {
        const result = await recognizeVoice(blob);
        console.log(`[Voice] Ergebnis:`, result);
        if (result && result.text && onIntentCallback) {
            onIntentCallback(result);
        }
    } catch (e) {
        console.error('[Voice] STT Fehler:', e);
    }

    // Schritt 5: Nächste Runde
    if (voiceModeActive) {
        startListeningCycle();
    }
}

/**
 * Wartet bis Sprache erkannt wird (RMS über Schwelle).
 * Gibt false zurück bei Timeout oder Deaktivierung.
 */
function waitForSpeech(threshold) {
    return new Promise((resolve) => {
        const start = Date.now();

        function check() {
            if (!voiceModeActive) { resolve(false); return; }
            if (Date.now() - start > NO_SPEECH_TIMEOUT) {
                console.log('[Voice] Keine Sprache erkannt, warte weiter…');
                resolve(false);
                return;
            }

            const rms = getRMS();
            if (rms > threshold) {
                resolve(true);
                return;
            }

            monitorRAF = requestAnimationFrame(check);
        }
        check();
    });
}

/**
 * Nimmt auf bis Stille nach Sprache erkannt wird.
 * Gibt Audio-Blob zurück.
 */
function recordUntilSilence(threshold) {
    return new Promise((resolve) => {
        if (!voiceModeActive || !micStream) { resolve(null); return; }

        audioChunks = [];

        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? 'audio/webm;codecs=opus'
            : 'audio/mp4';

        const recorder = new MediaRecorder(micStream, { mimeType });
        mediaRecorder = recorder;

        recorder.ondataavailable = (e) => {
            if (e.data.size > 0) audioChunks.push(e.data);
        };

        let speechMs = 0;
        let silenceStart = null;
        const recordStart = Date.now();

        recorder.onstop = () => {
            isRecording = false;
            cancelAnimationFrame(monitorRAF);

            if (audioChunks.length === 0 || speechMs < MIN_SPEECH_MS) {
                resolve(null);
                return;
            }

            resolve(new Blob(audioChunks, { type: mimeType }));
        };

        recorder.start(250);
        isRecording = true;

        // Stille-Monitor
        function monitor() {
            if (!isRecording || recorder.state !== 'recording') return;

            // Sicherheits-Timeout
            if (Date.now() - recordStart > MAX_RECORDING_MS) {
                recorder.stop();
                return;
            }

            const rms = getRMS();

            if (rms > threshold) {
                speechMs += 16; // ~1 frame bei 60fps
                silenceStart = null;
            } else {
                if (!silenceStart) {
                    silenceStart = Date.now();
                } else if (speechMs >= MIN_SPEECH_MS && Date.now() - silenceStart > SILENCE_DURATION) {
                    // Sprache gehört, jetzt still → stoppen
                    recorder.stop();
                    return;
                }
            }

            monitorRAF = requestAnimationFrame(monitor);
        }
        monitor();
    });
}

// ── Legacy PTT API (Rückwärtskompatibilität) ─────────────────

export async function startRecording() {
    if (isRecording) return;

    const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
            echoCancellation: true,
            noiseSuppression: true,
            channelCount: 1,
            sampleRate: 16000,
        }
    });

    audioChunks = [];

    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/mp4';

    mediaRecorder = new MediaRecorder(stream, { mimeType });

    mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunks.push(e.data);
    };

    mediaRecorder.start();
    isRecording = true;
}

export function stopRecording() {
    return new Promise((resolve) => {
        if (!mediaRecorder || !isRecording) {
            resolve(null);
            return;
        }

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
            try {
                return await recognizeVoice(blob);
            } catch (e) {
                console.error('STT Fehler:', e);
                return { intent: 'error', text: '', confidence: 0 };
            }
        }
    };
}

export function stopSpeaking() {
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
    }
}

export function isVoiceSupported() {
    return 'mediaDevices' in navigator && 'getUserMedia' in navigator.mediaDevices;
}
