const CACHE_NAME = 'picking-v2';
const PRECACHE = ['/', '/css/app.css', '/js/app.js'];
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
