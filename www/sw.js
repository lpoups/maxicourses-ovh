// Maxicourses Service Worker
const CACHE = 'maxicourses-v1';
const CORE = [
  '/',
  '/index.html',
  '/assets/favicons/favicon-32x32.png',
  '/assets/favicons/android-chrome-192x192.png',
  '/assets/favicons/android-chrome-512x512.png',
  '/assets/logo_blanc_maxicourses.png',
  '/assets/splash_screen.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(CORE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.map(k => k !== CACHE ? caches.delete(k) : null)))
    .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // App shell for navigations
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(() => caches.match('/index.html'))
    );
    return;
  }

  // Cache-first for local assets
  if (url.origin === location.origin && url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.open(CACHE).then(cache =>
        cache.match(req).then(res =>
          res || fetch(req).then(net => { cache.put(req, net.clone()); return net; })
        )
      )
    );
    return;
  }

  // Network-first otherwise (fallback to cache if available)
  event.respondWith(
    fetch(req).catch(() => caches.match(req))
  );
});
