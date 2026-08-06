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
const CACHE_NAME = 'picking-v22';
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
