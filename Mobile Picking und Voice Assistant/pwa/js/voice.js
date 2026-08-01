/**
 * Voice-Modul: Browser-TTS + Whisper-STT mit robustem Audio-Interlock.
 *
 * Ziel:
 * - TTS und STT duerfen sich nicht gegenseitig triggern.
 * - Hands-free bleibt moeglich.
 * - Long-Press Push-to-Talk ist als sicherer Fallback verfuegbar.
 */
import { getCsrfToken, recognizeVoice } from './api.js';
import {
    POST_TTS_COOLDOWN_MS,
    VOICE_STATES,
    isLikelyPromptEcho,
    shouldUsePiperTts,
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

const SPEECH_RMS = 18;
const SILENCE_AFTER_SPEECH = 300;
const NO_SPEECH_TIMEOUT = 6000;
const MIN_SPEECH_MS = 100;
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

// Piper TTS health-state: null=unbekannt, true=verfuegbar, false=nicht erreichbar.
// Wird beim ersten speak()-Aufruf ermittelt und dann gecacht.
let _piperHealthy = null;
let _currentPiperAudio = null;

// Epoch-Token gegen TTS-Races: stopSpeaking() erhoeht den Zaehler; verzoegerte
// Sprachstarts (80ms-Browser-Timer, laufender Piper-Fetch) pruefen ihn und
// brechen still ab statt nach dem Cancel doch noch loszureden.
let _speechEpoch = 0;

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

/**
 * Versucht Text via Backend-Piper-TTS abzuspielen.
 * Gibt true zurueck bei Erfolg, false bei Fehler/Unavailability.
 * Cacht den Verfuegbarkeitsstatus um wiederholte Timeouts zu vermeiden.
 */
async function _tryPiper(text, epoch) {
    if (_piperHealthy === false) return false;

    try {
        const controller = new AbortController();
        // 5s Timeout — laengere Saetze koennen 2-4s Synthesezeit brauchen.
        // Kein permanentes Disable bei Timeout — nur bei echten Server-Fehlern.
        const timerId = window.setTimeout(() => controller.abort(), 5000);

        // `/api/voice/tts` liegt seit Task 16 hinter dem Browser-Gate: eine
        // mutierende Methode (POST) braucht das CSRF-Token, sonst 403. Ohne den
        // Token schlug jeder Piper-Aufruf fehl, `_piperHealthy` wurde dauerhaft
        // false, und die App fiel FUER IMMER auf die Browser-Standardstimme
        // zurueck. Der Endpunkt ist idempotency-exempt (reine Synthese), also
        // reicht Session-Cookie + CSRF; kein Idempotency-Key noetig.
        const headers = { 'Content-Type': 'application/json' };
        const csrf = getCsrfToken();
        if (csrf) headers['X-CSRF-Token'] = csrf;

        const response = await fetch('/api/voice/tts', {
            method: 'POST',
            headers,
            credentials: 'same-origin',
            body: JSON.stringify({ text, lang: 'de-DE' }),
            signal: controller.signal,
        });
        window.clearTimeout(timerId);

        if (response.status === 403 || response.status === 401) {
            // Auth-/CSRF-Problem, KEIN toter Piper -- nicht permanent
            // deaktivieren, sonst bleibt die Browser-Stimme kleben, obwohl der
            // Dienst laeuft. Beim naechsten Versuch (mit gueltiger Session)
            // erneut probieren.
            _piperHealthy = null;
            return false;
        }
        if (!response.ok) {
            // Echter Server-Fehler (5xx): Service ist down → deaktivieren
            _piperHealthy = false;
            return false;
        }

        const blob = await response.blob();
        _piperHealthy = true;

        if (epoch !== undefined && epoch !== _speechEpoch) {
            // Waehrend des Fetch abgebrochen — nicht mehr abspielen, aber als
            // Erfolg melden, damit kein Browser-TTS-Fallback nachspricht.
            return true;
        }

        return new Promise((resolve) => {
            const url = URL.createObjectURL(blob);
            const audio = new Audio(url);
            _currentPiperAudio = audio;
            const cleanup = (success) => {
                _currentPiperAudio = null;
                URL.revokeObjectURL(url);
                resolve(success);
            };
            audio.onended = () => cleanup(true);
            // Audio-Fehler: Blob-Format-Problem — retry naechstes Mal
            audio.onerror = () => cleanup(false);
            audio.play().catch(() => cleanup(false));
        });
    } catch {
        // Netzwerkfehler / Timeout: Status auf null setzen → naechstes Mal retry
        _piperHealthy = null;
        return false;
    }
}

function _speakBrowserTTS(text, done, epoch) {
    if (!('speechSynthesis' in window)) {
        done();
        return;
    }
    window.speechSynthesis.cancel();
    window.setTimeout(() => {
        if (epoch !== undefined && epoch !== _speechEpoch) {
            done();
            return;
        }
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'de-DE';
        utterance.rate = 1.15;
        utterance.pitch = 1.0;
        const voice = cachedDeVoice || loadBestDeVoice();
        if (voice) utterance.voice = voice;
        utterance.onend = done;
        utterance.onerror = done;
        window.speechSynthesis.speak(utterance);
    }, 80);
}

export function speak(text) {
    return new Promise((resolve) => {
        if (!ttsUnlocked) {
            pendingSpeech = text;
            resolve();
            return;
        }

        beginSpeechInterlock(text);
        const epoch = _speechEpoch;

        const done = () => {
            ttsBusy = false;
            lastTtsEndedAt = Date.now();
            enterCooldown();
            resolve();
        };

        if (!shouldUsePiperTts(text)) {
            _speakBrowserTTS(text, done, epoch);
            return;
        }

        _tryPiper(text, epoch).then((piperOk) => {
            if (piperOk || epoch !== _speechEpoch) {
                done();
            } else {
                _speakBrowserTTS(text, done, epoch);
            }
        });
    });
}

export function stopSpeaking() {
    _speechEpoch += 1;
    if (_currentPiperAudio) {
        _currentPiperAudio.pause();
        _currentPiperAudio = null;
    }
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
    }
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
