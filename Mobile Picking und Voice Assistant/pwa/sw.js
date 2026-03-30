const CACHE_NAME = 'picking-v11';
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
    event.waitUntil(precacheShell());
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
