/**
 * Voice-Modul: TTS (Browser) + Audio-Recording (MediaRecorder).
 * 
 * ARCHITEKTUR-ENTSCHEIDUNG:
 * - TTS: SpeechSynthesis (Browser-nativ, funktioniert auf iOS + Android)
 * - STT: MediaRecorder → Backend → Vosk (NICHT Browser-SpeechRecognition!)
 *   Grund: SpeechRecognition funktioniert nicht in iOS PWA Standalone.
 */
import { recognizeVoice } from './api.js';

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

// ── TTS ─────────────────────────────────────────────────────

/**
 * Text vorlesen (deutsch).
 * WICHTIG: Muss durch User-Geste ausgelöst werden (iOS-Anforderung).
 */
export function speak(text) {
    return new Promise((resolve) => {
        if (!('speechSynthesis' in window)) {
            console.warn('SpeechSynthesis nicht verfügbar');
            resolve();
            return;
        }

        // Vorherige Ausgabe abbrechen
        window.speechSynthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'de-DE';
        utterance.rate = 1.0;
        utterance.pitch = 1.0;
        utterance.onend = resolve;
        utterance.onerror = () => resolve();

        // iOS Workaround: Voices laden manchmal verzögert
        const voices = window.speechSynthesis.getVoices();
        const deVoice = voices.find(v => v.lang.startsWith('de'));
        if (deVoice) utterance.voice = deVoice;

        window.speechSynthesis.speak(utterance);
    });
}

// ── Audio Recording (für Server-Side STT) ───────────────────

/**
 * Audio-Aufnahme starten (Push-to-Talk).
 * Gibt Promise zurück das mit dem Audio-Blob resolved.
 */
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

    // Format-Erkennung: iOS = mp4, Chrome = webm
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

/**
 * Audio-Aufnahme stoppen und Blob zurückgeben.
 */
export function stopRecording() {
    return new Promise((resolve) => {
        if (!mediaRecorder || !isRecording) {
            resolve(null);
            return;
        }

        mediaRecorder.onstop = () => {
            const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType });
            // Stream-Tracks stoppen (Mikrofon freigeben)
            mediaRecorder.stream.getTracks().forEach(t => t.stop());
            isRecording = false;
            resolve(blob);
        };

        mediaRecorder.stop();
    });
}

/**
 * Vollständiger Voice-Flow: Aufnehmen → Backend → Intent.
 * Gibt Intent-Objekt zurück.
 */
export async function captureAndRecognize() {
    await startRecording();

    // Warte auf PTT-Release oder Timeout
    // (wird vom UI gesteuert — hier nur die Logik)
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

export function isVoiceSupported() {
    return 'mediaDevices' in navigator && 'getUserMedia' in navigator.mediaDevices;
}
