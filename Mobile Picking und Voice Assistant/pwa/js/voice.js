/**
 * Voice-Modul: Browser-TTS + Whisper-STT mit robustem Audio-Interlock.
 *
 * Ziel:
 * - TTS und STT duerfen sich nicht gegenseitig triggern.
 * - Hands-free bleibt moeglich.
 * - Long-Press Push-to-Talk ist als sicherer Fallback verfuegbar.
 */
import { recognizeVoice } from './api.js';
import {
    POST_TTS_COOLDOWN_MS,
    VOICE_STATES,
    isLikelyPromptEcho,
    transitionVoiceState,
} from './voice-helpers.mjs';

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

let voiceModeActive = false;
let audioContext = null;
let analyser = null;
let micStream = null;
let monitorInterval = null;
let cooldownTimer = null;
let ttsBusy = false;
let voiceState = VOICE_STATES.IDLE;

const SPEECH_RMS = 25;
const SILENCE_AFTER_SPEECH = 300;
const NO_SPEECH_TIMEOUT = 6000;
const MIN_SPEECH_MS = 150;
const MAX_RECORDING_MS = 10000;
const CHECK_MS = 30;

let onIntentCallback = null;
let onModeChangeCallback = null;
let onStateChangeCallback = null;
let requestContextProvider = null;

let recognitionGeneration = 0;
let lastPromptText = '';
let lastTtsEndedAt = 0;
let ignoreFirstTranscriptAfterTts = false;

let pushToTalkSession = null;
let pushToTalkActive = false;

// Recovery-dialog state: set when backend returns requires_confirmation=true.
// Cleared on explicit yes, no, or when a different intent overrides it.
let _pendingConfirmAction = null;
let _pendingConfirmValue = null;

let cachedDeVoice = null;

function _resetConfirmationState() {
    _pendingConfirmAction = null;
    _pendingConfirmValue = null;
}

/**
 * Wraps onIntentCallback with a 3-way recovery-dialog state machine.
 *
 *  1. Pending confirmation active + user says "confirm" → execute stored action.
 *  2. Pending confirmation active + user says pause/unknown → abort silently.
 *  3. Pending confirmation active + user says something else → discard pending,
 *     fall through and process the new intent normally.
 *  4. Backend sets requires_confirmation → speak prompt, store action, wait.
 *  5. Normal high-confidence result → forward to onIntentCallback directly.
 */
function _handleIntentWithRecovery(result) {
    if (_pendingConfirmAction) {
        if (result.intent === 'confirm') {
            const action = _pendingConfirmAction;
            const value = _pendingConfirmValue;
            _resetConfirmationState();
            if (onIntentCallback) onIntentCallback({ ...result, intent: action, value });
            return;
        }
        if (result.intent === 'pause' || result.intent === 'unknown') {
            speak('Abgebrochen.');
            _resetConfirmationState();
            return;
        }
        // User said something else entirely — discard pending, handle new intent.
        _resetConfirmationState();
    }

    if (result.requires_confirmation && result.confirmation_prompt) {
        speak(result.confirmation_prompt);
        _pendingConfirmAction = result.intent;
        _pendingConfirmValue = result.value ?? null;
        return;
    }

    if (onIntentCallback) onIntentCallback(result);
}

function setVoiceState(event, options = {}) {
    voiceState = transitionVoiceState(voiceState, event, options);
    if (onStateChangeCallback) onStateChangeCallback(voiceState);
}

function getRecognitionOptions() {
    if (!requestContextProvider) return {};
    try {
        return requestContextProvider() || {};
    } catch (error) {
        console.warn('[Voice] Konnte Recognition-Kontext nicht ableiten:', error);
        return {};
    }
}

function loadBestDeVoice() {
    const voices = window.speechSynthesis.getVoices();
    const deVoices = voices.filter((voice) => voice.lang.startsWith('de'));
    if (!deVoices.length) return null;

    const preferred = ['markus', 'anna'];
    const byName = deVoices.find(
        (voice) =>
            preferred.some((name) => voice.name.toLowerCase().includes(name)) &&
            /enhanced/i.test(voice.name),
    );
    const anyEnhanced = deVoices.find(
        (voice) => /enhanced|premium/i.test(voice.name) && !/eloquence/i.test(voice.name),
    );
    const byNameAny = deVoices.find((voice) =>
        preferred.some((name) => voice.name.toLowerCase().includes(name)),
    );
    const noEloquence = deVoices.find((voice) => !/eloquence|compact/i.test(voice.name));

    return byName || anyEnhanced || byNameAny || noEloquence || deVoices[0];
}

if ('speechSynthesis' in window) {
    window.speechSynthesis.addEventListener('voiceschanged', () => {
        cachedDeVoice = loadBestDeVoice();
    });
    cachedDeVoice = loadBestDeVoice();
}

let ttsUnlocked = false;
let pendingSpeech = null;

function unlockTTS() {
    if (ttsUnlocked || !('speechSynthesis' in window)) return;
    ttsUnlocked = true;
    const utterance = new SpeechSynthesisUtterance(' ');
    utterance.volume = 0.01;
    utterance.lang = 'de-DE';
    window.speechSynthesis.speak(utterance);

    if (pendingSpeech) {
        const text = pendingSpeech;
        pendingSpeech = null;
        window.setTimeout(() => {
            speak(text);
        }, 200);
    }
}

document.addEventListener('touchstart', unlockTTS, { once: true, passive: true });
document.addEventListener('pointerdown', unlockTTS, { once: true, passive: true });

function clearCooldown() {
    if (cooldownTimer) {
        window.clearTimeout(cooldownTimer);
        cooldownTimer = null;
    }
}

function muteMic(mute) {
    if (!micStream) return;
    micStream.getAudioTracks().forEach((track) => {
        track.enabled = !mute;
    });
}

function stopMonitor() {
    if (monitorInterval) {
        window.clearInterval(monitorInterval);
        monitorInterval = null;
    }
}

function stopCurrentRecording() {
    stopMonitor();
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        try {
            mediaRecorder.stop();
        } catch {
            // Recorder was already closing.
        }
    }
}

function getRMS() {
    if (!analyser) return 0;
    const buffer = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(buffer);
    let sum = 0;
    for (let index = 0; index < buffer.length; index += 1) {
        sum += buffer[index] * buffer[index];
    }
    return Math.sqrt(sum / buffer.length);
}

function enterCooldown() {
    clearCooldown();
    setVoiceState('tts-end', { voiceModeActive });
    cooldownTimer = window.setTimeout(() => {
        cooldownTimer = null;
        muteMic(false);
        setVoiceState('cooldown-end', { voiceModeActive });
        if (voiceModeActive && !ttsBusy && !isRecording && !pushToTalkActive) {
            startListeningCycle();
        }
    }, POST_TTS_COOLDOWN_MS);
}

function beginSpeechInterlock(promptText) {
    ttsBusy = true;
    recognitionGeneration += 1;
    lastPromptText = promptText || '';
    ignoreFirstTranscriptAfterTts = Boolean(promptText);
    clearCooldown();
    stopCurrentRecording();
    muteMic(true);
    setVoiceState('tts-start', { voiceModeActive });
}

export function speak(text) {
    return new Promise((resolve) => {
        if (!('speechSynthesis' in window)) {
            resolve();
            return;
        }

        if (!ttsUnlocked) {
            pendingSpeech = text;
            resolve();
            return;
        }

        beginSpeechInterlock(text);
        window.speechSynthesis.cancel();

        window.setTimeout(() => {
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = 'de-DE';
            utterance.rate = 1.15;
            utterance.pitch = 1.0;

            const voice = cachedDeVoice || loadBestDeVoice();
            if (voice) utterance.voice = voice;

            const done = () => {
                ttsBusy = false;
                lastTtsEndedAt = Date.now();
                enterCooldown();
                resolve();
            };

            utterance.onend = done;
            utterance.onerror = done;
            window.speechSynthesis.speak(utterance);
        }, 80);
    });
}

export function stopSpeaking() {
    if (!('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    if (!ttsBusy) return;
    ttsBusy = false;
    lastTtsEndedAt = Date.now();
    enterCooldown();
}

export function isVoiceSupported() {
    return 'mediaDevices' in navigator && 'getUserMedia' in navigator.mediaDevices;
}

export function isVoiceModeActive() {
    return voiceModeActive;
}

export function isPushToTalkActive() {
    return pushToTalkActive;
}

export function setVoiceStatusListener(listener) {
    onStateChangeCallback = listener;
    if (onStateChangeCallback) onStateChangeCallback(voiceState);
}

export function setVoiceRequestContextProvider(provider) {
    requestContextProvider = provider;
}

export function toggleVoiceMode(onIntent, onModeChange, onError) {
    onIntentCallback = onIntent;
    onModeChangeCallback = onModeChange;
    if (voiceModeActive) {
        deactivateVoiceMode();
        return;
    }
    activateVoiceMode(onError);
}

async function activateVoiceMode(onError) {
    if (voiceModeActive) return;

    try {
        micStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
                channelCount: 1,
            },
        });

        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        if (audioContext.state === 'suspended') {
            await audioContext.resume();
        }

        analyser = audioContext.createAnalyser();
        analyser.fftSize = 512;
        audioContext.createMediaStreamSource(micStream).connect(analyser);

        voiceModeActive = true;
        setVoiceState('activate', { voiceModeActive: true });
        if (onModeChangeCallback) onModeChangeCallback(true);

        if (!ttsBusy && voiceState !== VOICE_STATES.COOLDOWN) {
            startListeningCycle();
        }
    } catch (error) {
        console.error('Mikrofon-Zugriff fehlgeschlagen:', error);
        voiceModeActive = false;
        setVoiceState('deactivate', { voiceModeActive: false });
        if (onModeChangeCallback) onModeChangeCallback(false);
        if (onError) onError(error);
    }
}

function deactivateVoiceMode() {
    voiceModeActive = false;
    recognitionGeneration += 1;
    clearCooldown();
    stopMonitor();

    if (mediaRecorder && mediaRecorder.state === 'recording') {
        try {
            mediaRecorder.stop();
        } catch {
            // Recorder was already closing.
        }
    }

    if (micStream) {
        micStream.getTracks().forEach((track) => track.stop());
        micStream = null;
    }

    if (audioContext) {
        audioContext.close().catch(() => {});
        audioContext = null;
    }

    analyser = null;
    isRecording = false;
    setVoiceState('deactivate', { voiceModeActive: false });
    if (onModeChangeCallback) onModeChangeCallback(false);
}

async function startListeningCycle() {
    if (!voiceModeActive || !micStream || ttsBusy || pushToTalkActive) return;
    if (voiceState === VOICE_STATES.SPEAKING || voiceState === VOICE_STATES.COOLDOWN) return;

    clearCooldown();
    audioChunks = [];

    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/mp4';

    const recorder = new MediaRecorder(micStream, { mimeType });
    const cycleGeneration = recognitionGeneration;
    mediaRecorder = recorder;
    recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunks.push(event.data);
    };

    const capture = await new Promise((resolve) => {
        let speechMs = 0;
        let silenceStart = null;
        let hasSpeech = false;
        const startedAt = Date.now();

        recorder.onstop = () => {
            isRecording = false;
            stopMonitor();

            const staleCapture =
                cycleGeneration !== recognitionGeneration ||
                ttsBusy ||
                startedAt <= lastTtsEndedAt + POST_TTS_COOLDOWN_MS;

            if (staleCapture || audioChunks.length === 0 || !hasSpeech || speechMs < MIN_SPEECH_MS) {
                resolve(null);
                return;
            }

            resolve({
                blob: new Blob(audioChunks, { type: mimeType }),
                startedAt,
                generation: cycleGeneration,
            });
        };

        setVoiceState('capture-start', { voiceModeActive });
        recorder.start(200);
        isRecording = true;

        monitorInterval = window.setInterval(() => {
            if (ttsBusy || !voiceModeActive || pushToTalkActive || recorder.state !== 'recording') {
                stopMonitor();
                if (recorder.state === 'recording') recorder.stop();
                return;
            }

            const elapsed = Date.now() - startedAt;
            if (elapsed > MAX_RECORDING_MS) {
                stopMonitor();
                recorder.stop();
                return;
            }

            const rms = getRMS();
            if (rms > SPEECH_RMS) {
                if (!hasSpeech) {
                    setVoiceState('speech-start', { voiceModeActive });
                }
                hasSpeech = true;
                speechMs += CHECK_MS;
                silenceStart = null;
                return;
            }

            if (hasSpeech) {
                if (!silenceStart) {
                    silenceStart = Date.now();
                    return;
                }
                if (Date.now() - silenceStart > SILENCE_AFTER_SPEECH) {
                    stopMonitor();
                    recorder.stop();
                }
                return;
            }

            if (elapsed > NO_SPEECH_TIMEOUT) {
                stopMonitor();
                recorder.stop();
            }
        }, CHECK_MS);
    });

    if (!voiceModeActive || ttsBusy || pushToTalkActive) return;

    if (capture?.blob) {
        try {
            const result = await recognizeVoice(capture.blob, getRecognitionOptions());
            const transcript = result?.text || '';
            const staleResult =
                capture.generation !== recognitionGeneration ||
                capture.startedAt <= lastTtsEndedAt + POST_TTS_COOLDOWN_MS;

            if (!staleResult && transcript) {
                const shouldDropEcho =
                    ignoreFirstTranscriptAfterTts && isLikelyPromptEcho(transcript, lastPromptText);

                if (shouldDropEcho) {
                    ignoreFirstTranscriptAfterTts = false;
                } else {
                    ignoreFirstTranscriptAfterTts = false;
                    _handleIntentWithRecovery(result);
                }
            }
        } catch (error) {
            console.error('[Voice] STT Fehler:', error);
        }
    }

    if (voiceModeActive && !ttsBusy && !pushToTalkActive) {
        startListeningCycle();
    }
}

export async function startRecording() {
    if (isRecording) return;
    const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            channelCount: 1,
        },
    });
    audioChunks = [];
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/mp4';
    mediaRecorder = new MediaRecorder(stream, { mimeType });
    mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunks.push(event.data);
    };
    mediaRecorder.start();
    isRecording = true;
    setVoiceState('capture-start', { voiceModeActive: true });
}

export function stopRecording() {
    return new Promise((resolve) => {
        if (!mediaRecorder || !isRecording) {
            resolve(null);
            return;
        }

        mediaRecorder.onstop = () => {
            const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType });
            mediaRecorder.stream.getTracks().forEach((track) => track.stop());
            isRecording = false;
            setVoiceState('deactivate', { voiceModeActive: false });
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
                return await recognizeVoice(blob, getRecognitionOptions());
            } catch {
                return { intent: 'error', text: '', confidence: 0 };
            }
        },
    };
}

export async function startPushToTalk(onIntent, onError) {
    if (pushToTalkActive || voiceModeActive) return false;

    onIntentCallback = onIntent || onIntentCallback;

    try {
        if (ttsBusy || voiceState === VOICE_STATES.SPEAKING || voiceState === VOICE_STATES.COOLDOWN) {
            stopSpeaking();
        }
        pushToTalkSession = await captureAndRecognize();
        pushToTalkActive = true;
        return true;
    } catch (error) {
        console.error('Push-to-Talk konnte nicht gestartet werden:', error);
        if (onError) onError(error);
        return false;
    }
}

export async function stopPushToTalk() {
    if (!pushToTalkActive || !pushToTalkSession) return null;

    const session = pushToTalkSession;
    pushToTalkSession = null;
    pushToTalkActive = false;

    const result = await session.stop();
    if (result?.text) {
        _handleIntentWithRecovery(result);
    }
    return result;
}

export function stopVoiceMode() {
    if (voiceModeActive) deactivateVoiceMode();
}
