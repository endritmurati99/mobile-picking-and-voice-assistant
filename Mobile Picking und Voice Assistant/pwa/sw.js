// v31: CSRF-Erneuerung beim Wiederherstellen einer Cookie-Sitzung (api.js).
// v26: Kamera-Barcode-Fallback fuer iOS (scanner.js + /vendor/zxing/*). Unter iOS
// gibt es in KEINEM Browser einen BarcodeDetector -- ohne Bump behaelt jedes iPhone
// die alte scanner.js, die nur eine Vorschau ohne jede Erkennung zeigt, und der
// neue /vendor/zxing/-Pfad liegt in keinem Cache.
// v24: Lagerwechsel tauscht die Sitzung (`/auth/switch-instance`), statt nur
// den localStorage zu setzen (app.js, api.js). Ohne Bump behaelt jedes Geraet
// den alten Umschalter, der still im ersten Lager bleibt.
// v23: Cluster-Artikel-/Kartonscan und mobile Rundgangsdarstellung.
// v22: Idempotenzschluessel prozentkodiert + gefaltet (api.js) -- ohne Bump
// schickt der alte Worker weiter rohe Umlaute und Leerzeichen im Header und
// jede Qualitaetsmeldung mit deutschem Beschreibungstext bleibt bei 400.
// v16: Piper TTS CSRF + natural speech phrasing (voice.js, voice-runtime.mjs).
// v15: order-completion fix in app.js. v14 was the session login.
//
// Bumping this is NOT
// cosmetic -- all three files are precached below, so a browser that has ever
// opened this app keeps serving the pre-login versions until the name changes:
// no login screen, legacy identity headers that the backend no longer honours,
// and a health probe against a route that does not exist. The symptom is an app
// that looks merely broken, which is the worst kind of stale cache.
const CACHE_NAME = 'picking-v31';
const PRECACHE = [
    '/',
    '/index.html',
    '/manifest.json',
    '/css/app.css',
    '/fonts/outfit-latin-variable.woff2',
    '/fonts/jetbrains-mono-latin-variable.woff2',
    '/icons/icon-192.png',
    '/icons/icon-512.png',
    '/js/api.js',
    '/js/app.js',
    '/js/camera.js',
    '/js/feedback.js',
    '/js/pwa.js',
    '/js/scanner.js',
    '/js/ui.js',
    '/js/voice.js',
    '/js/voice-helpers.mjs',
    '/js/voice-runtime.mjs',
    // Kamera-Fallback fuer iOS/WebKit. Muss offline im Lager-WLAN verfuegbar sein,
    // deshalb vorgeladen -- geholt wird er per dynamischem import() nur dort, wo
    // BarcodeDetector fehlt.
    '/vendor/zxing/reader/index.js',
    '/vendor/zxing/share.js',
    '/vendor/zxing/zxing_reader.wasm',
];

function isSameOrigin(url) {
    return url.origin === self.location.origin;
}

function shouldHandleRequest(request) {
    if (request.method !== 'GET') return false;

    const url = new URL(request.url);
    if (!isSameOrigin(url)) return false;
    if (url.pathname.startsWith('/api/')) return false;

    return request.mode === 'navigate' || PRECACHE.includes(url.pathname);
}

async function precacheShell() {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(PRECACHE.map((asset) => new Request(asset, { cache: 'reload' })));
}

async function networkFirst(request) {
    const cache = await caches.open(CACHE_NAME);

    try {
        const response = await fetch(request, { cache: 'no-store' });
        if (response.ok) {
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        const cached = await cache.match(request, { ignoreSearch: request.mode === 'navigate' });
        if (cached) return cached;

        if (request.mode === 'navigate') {
            const fallback = await cache.match('/index.html');
            if (fallback) return fallback;
        }

        throw error;
    }
}

self.addEventListener('install', (event) => {
    // skipWaiting is NOT optional here. Without it a new service worker installs
    // but WAITS until every tab of the old one is closed, so the old worker keeps
    // serving the old cached app.js/api.js against a backend that has already
    // moved on -- session login gone, legacy headers rejected, health probe 404.
    // The symptom is a screen that silently breaks or blanks on a machine where
    // the deployed files are provably current. Activate the new worker at once;
    // `clients.claim()` below then makes it control the open page immediately.
    event.waitUntil(precacheShell().then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('message', (event) => {
    if (event.data?.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});

self.addEventListener('fetch', (event) => {
    if (!shouldHandleRequest(event.request)) return;
    event.respondWith(networkFirst(event.request));
});
