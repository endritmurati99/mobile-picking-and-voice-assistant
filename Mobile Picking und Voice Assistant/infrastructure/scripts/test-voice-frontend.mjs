import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

const root = new URL('../..', import.meta.url);
const source = await fs.readFile(new URL('pwa/js/voice.js', root), 'utf8');
const helpers = await fs.readFile(new URL('pwa/js/voice-helpers.mjs', root), 'utf8');

async function loadVoice({ samples, recognize, getUserMedia = null, fetch = null }) {
  let now = 1_000;
  let monitor;
  let recorder;
  const recorders = [];
  const stream = { getTracks: () => [{ stop() {}, enabled: true }], getAudioTracks: () => [{ enabled: true }] };
  const analyser = {
    fftSize: 512,
    getFloatTimeDomainData(buffer) { buffer.fill(samples.shift() ?? 0); },
    getByteFrequencyData() { throw new Error('FFT path must not be used'); },
  };
  const documentListeners = new Map();
  const context = vm.createContext({
    AbortController, Blob, console, Float32Array, Promise, URL, setTimeout, clearTimeout, queueMicrotask,
    Date: { now: () => now },
    document: { addEventListener(event, callback) { documentListeners.set(event, callback); } },
    navigator: { mediaDevices: { async getUserMedia() { return getUserMedia ? getUserMedia() : stream; } } },
    window: {
      setInterval(callback) { monitor = callback; return 1; }, clearInterval() {}, setTimeout, clearTimeout,
      speechSynthesis: { getVoices: () => [], addEventListener() {}, cancel() {}, speak(utterance) { queueMicrotask(() => utterance.onend?.()); } },
      AudioContext: class {
        state = 'running'; async resume() {}
        createAnalyser() { return analyser; }
        createMediaStreamSource() { return { connect() {} }; }
        close() { return Promise.resolve(); }
      },
    },
    fetch: fetch || (async () => { throw new Error('unexpected fetch'); }),
    Audio: class {
      constructor() { this.onended = null; this.onerror = null; }
      play() { queueMicrotask(() => this.onended?.()); return Promise.resolve(); }
      pause() {}
    },
    SpeechSynthesisUtterance: class { constructor(text) { this.text = text; } },
    MediaRecorder: class {
      static isTypeSupported() { return true; }
      constructor() { recorder = this; recorders.push(this); this.stream = stream; this.state = 'inactive'; this.mimeType = 'audio/webm;codecs=opus'; }
      start() { this.state = 'recording'; }
      stop() {
        if (this.state !== 'recording') return;
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['audio']) });
        this.onstop?.();
      }
    },
  });
  const api = new vm.SyntheticModule(['getCsrfToken', 'recognizeVoice'], function init() {
    this.setExport('getCsrfToken', () => 'csrf');
    this.setExport('recognizeVoice', recognize);
  }, { context });
  const helper = new vm.SourceTextModule(helpers, { context });
  const voice = new vm.SourceTextModule(source, { context });
  await helper.link(() => { throw new Error('helpers have no imports'); });
  await helper.evaluate();
  await voice.link((specifier) => specifier === './api.js' ? api : helper);
  await api.evaluate();
  await voice.evaluate();
  return {
    voice: voice.namespace,
    tick(value) { samples.push(value); now += 30; monitor(); },
    async flush() { await new Promise((resolve) => setImmediate(resolve)); },
    get recorder() { return recorder; },
    get recorders() { return recorders; },
    unlockTts() { documentListeners.get('pointerdown')?.(); },
    helpers: helper.namespace,
  };
}

const received = [];
const handsFree = await loadVoice({ samples: [], recognize: async () => ({ intent: 'unknown', text: '', confidence: 0 }) });
handsFree.voice.toggleVoiceMode((result) => received.push(result), () => {});
await handsFree.flush();
await handsFree.flush();
for (let tick = 0; tick < 4; tick += 1) handsFree.tick(0.08);
for (let tick = 0; tick < 20; tick += 1) handsFree.tick(0.01);
await handsFree.flush();
await handsFree.flush();
assert.equal(handsFree.recorders[0].state, 'inactive', '0.08 speech followed by 0.01 background stops after 550 ms');
assert.equal(received.length, 1, 'an empty, non-stale STT result reaches recovery handling');
await handsFree.voice.cancelPushToTalk();
assert.equal(handsFree.recorder.state, 'recording', 'cancelling PTT does not stop an active hands-free capture');

const pttResults = [];
const ptt = await loadVoice({ samples: [], recognize: async () => ({ intent: 'error', text: '', confidence: 0 }) });
assert.equal(await ptt.voice.startPushToTalk((result) => pttResults.push(result)), true);
await ptt.voice.stopPushToTalk();
assert.equal(pttResults.length, 1, 'push-to-talk forwards a failed STT result to recovery handling');

const cancelledPttResults = [];
const cancelledPtt = await loadVoice({ samples: [], recognize: async () => ({ intent: 'confirm', text: 'ja', confidence: 1 }) });
assert.equal(await cancelledPtt.voice.startPushToTalk((result) => cancelledPttResults.push(result)), true);
await cancelledPtt.voice.cancelPushToTalk();
assert.equal(cancelledPttResults.length, 0, 'a cancelled push-to-talk gesture never dispatches its result');

const writeIntentResults = [];
const writeIntent = await loadVoice({
  samples: [],
  recognize: async () => ({ intent: 'confirm_all', text: 'alle bestaetigen', confidence: 0.91, requires_confirmation: true, confirmation_prompt: 'Richtig?' }),
});
assert.equal(await writeIntent.voice.startPushToTalk((result) => writeIntentResults.push(result)), true);
await writeIntent.voice.stopPushToTalk();
assert.deepEqual(writeIntentResults, [{ intent: 'confirm_all', text: 'alle bestaetigen', confidence: 0.91, requires_confirmation: true, confirmation_prompt: 'Richtig?' }], 'write intents reach app.js directly so it owns the only confirmation prompt');

let releaseOldPtt;
let pttRecognitionCount = 0;
const overlappingPtt = await loadVoice({
  samples: [],
  recognize: () => {
    pttRecognitionCount += 1;
    return pttRecognitionCount === 1
      ? new Promise((resolve) => { releaseOldPtt = resolve; })
      : Promise.resolve({ intent: 'unknown', text: '', confidence: 0 });
  },
});
const overlappingResults = [];
assert.equal(await overlappingPtt.voice.startPushToTalk((result) => overlappingResults.push(result)), true);
const oldStop = overlappingPtt.voice.stopPushToTalk();
await overlappingPtt.flush();
assert.equal(await overlappingPtt.voice.startPushToTalk((result) => overlappingResults.push(result)), true);
releaseOldPtt({ intent: 'confirm', text: 'ja', confidence: 1 });
await oldStop;
assert.equal(overlappingResults.length, 0, 'an older push-to-talk result cannot dispatch after a newer session starts');
await overlappingPtt.voice.cancelPushToTalk();

let releaseMicrophone;
let microphoneRequests = 0;
const delayedStream = { getTracks: () => [{ stop() {}, enabled: true }], getAudioTracks: () => [{ enabled: true }] };
const pendingPtt = await loadVoice({
  samples: [],
  recognize: async () => ({ intent: 'confirm', text: 'ja', confidence: 1 }),
  getUserMedia: () => (++microphoneRequests === 1 ? new Promise((resolve) => { releaseMicrophone = resolve; }) : delayedStream),
});
const pendingStart = pendingPtt.voice.startPushToTalk(() => { throw new Error('cancelled acquisition dispatched'); });
assert.equal(await pendingPtt.voice.startPushToTalk(() => {}), false, 'a second PTT start cannot replace a pending recorder');
await pendingPtt.voice.cancelPushToTalk();
releaseMicrophone(delayedStream);
assert.equal(await pendingStart, false, 'a cancelled microphone acquisition cannot create a live PTT session');

const pause = await loadVoice({ samples: [], recognize: async () => ({ intent: 'next', text: 'weiter', confidence: 1 }) });
pause.voice.toggleVoiceMode(() => {}, () => {});
await pause.flush();
pause.tick(0.08);
for (let tick = 0; tick < 10; tick += 1) pause.tick(0.01);
pause.tick(0.08);
assert.equal(pause.recorder.state, 'recording', 'a 300 ms pause inside a command does not stop recording');
pause.voice.stopVoiceMode();

let release;
const stale = await loadVoice({ samples: [], recognize: () => new Promise((resolve) => { release = resolve; }) });
const staleResults = [];
stale.voice.toggleVoiceMode((result) => staleResults.push(result), () => {});
await stale.flush();
await stale.flush();
for (let tick = 0; tick < 4; tick += 1) stale.tick(0.08);
for (let tick = 0; tick < 20; tick += 1) stale.tick(0.01);
await stale.flush();
stale.voice.stopVoiceMode();
release({ intent: 'confirm', text: 'ja', confidence: 1 });
await stale.flush();
assert.equal(staleResults.length, 0, 'a stale response cannot execute an action');

let rejectLate;
const staleFailure = await loadVoice({ samples: [], recognize: () => new Promise((_resolve, reject) => { rejectLate = reject; }) });
const staleFailureResults = [];
staleFailure.voice.toggleVoiceMode((result) => staleFailureResults.push(result), () => {});
await staleFailure.flush();
for (let tick = 0; tick < 4; tick += 1) staleFailure.tick(0.08);
for (let tick = 0; tick < 20; tick += 1) staleFailure.tick(0.01);
await staleFailure.flush();
staleFailure.voice.stopVoiceMode();
rejectLate(new Error('late network failure'));
await staleFailure.flush();
assert.equal(staleFailureResults.length, 0, 'a late stale STT failure cannot alter recovery state');

const shortPromptCalls = [];
const shortPrompt = await loadVoice({
  samples: [],
  recognize: async () => ({ intent: 'unknown', text: '', confidence: 0 }),
  fetch: async (...args) => {
    shortPromptCalls.push(args);
    return new Response(new Blob(['audio']), { status: 200 });
  },
});
shortPrompt.unlockTts();
await shortPrompt.voice.speak('Fertig.');
assert.equal(shortPromptCalls.length, 1, 'short prompts use Piper when it is available');
assert.equal(shortPrompt.helpers.shouldUsePiperTts('Fertig.'), true, 'every non-empty prompt is eligible for Piper');

let retryPiperCalls = 0;
const retryPiper = await loadVoice({
  samples: [],
  recognize: async () => ({ intent: 'unknown', text: '', confidence: 0 }),
  fetch: async () => {
    retryPiperCalls += 1;
    return retryPiperCalls === 1
      ? new Response('', { status: 503 })
      : new Response(new Blob(['audio']), { status: 200 });
  },
});
retryPiper.unlockTts();
await retryPiper.voice.speak('Erste Ansage.');
await retryPiper.voice.speak('Zweite Ansage.');
assert.equal(retryPiperCalls, 2, 'a failed Piper attempt does not permanently disable later retries');

let firstRequest;
const piperRequests = [];
const overlappingSpeech = await loadVoice({
  samples: [],
  recognize: async () => ({ intent: 'unknown', text: '', confidence: 0 }),
  fetch: (_url, options) => {
    piperRequests.push(options);
    if (piperRequests.length === 1) return new Promise((resolve) => { firstRequest = resolve; });
    return Promise.resolve(new Response(new Blob(['audio']), { status: 200 }));
  },
});
const speechStates = [];
overlappingSpeech.voice.setVoiceStatusListener((state) => speechStates.push(state));
overlappingSpeech.unlockTts();
const firstSpeech = overlappingSpeech.voice.speak('Erste Ansage.');
const secondSpeech = overlappingSpeech.voice.speak('Neue Ansage.');
await secondSpeech;
firstRequest(new Response(new Blob(['audio']), { status: 200 }));
await firstSpeech;
assert.equal(piperRequests[0].signal.aborted, true, 'starting newer speech aborts the older Piper request');
assert.equal(speechStates.filter((state) => state === 'cooldown').length, 2, 'a late Piper completion cannot finish newer speech twice');

console.log('voice frontend checks passed');
