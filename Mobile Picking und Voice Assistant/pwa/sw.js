const CACHE_NAME = 'picking-v10';
const PRECACHE = [
    '/',
    '/index.html',
    '/css/app.css',
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
self.addEventListener('install', e => {
    e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys()
            .then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});
self.addEventListener('fetch', e => {
    // API-Calls nie intercepten — direkt ans Netzwerk
    if (e.request.url.includes('/api/')) return;
    // Cache-first fuer Shell-Assets: schnellere Antwort, Netzwerk als Fallback
    e.respondWith(
        caches.match(e.request).then(cached => cached || fetch(e.request).then(response => {
            // Nur erfolgreiche GET-Antworten nachtraeglich cachen
            if (e.request.method === 'GET' && response.ok) {
                caches.open(CACHE_NAME).then(c => c.put(e.request, response.clone()));
            }
            return response;
        }))
    );
});
