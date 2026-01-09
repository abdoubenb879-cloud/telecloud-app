const CACHE_NAME = 'cloudvault-v1';
const ASSETS = [
    '/',
    '/static/style.css',
    '/static/modal.js',
    '/static/logo.png',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css',
    'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS);
        })
    );
});

self.addEventListener('fetch', (event) => {
    // Only cache static assets, let API and page requests go through
    if (event.request.url.includes('/static/') || event.request.url.includes('fonts.googleapis.com')) {
        event.respondWith(
            caches.match(event.request).then((response) => {
                return response || fetch(event.request);
            })
        );
    }
});
