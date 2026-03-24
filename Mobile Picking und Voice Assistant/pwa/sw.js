const CACHE_NAME = 'picking-v4';
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
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
