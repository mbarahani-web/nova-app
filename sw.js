/* NOVA PWA shell — safe for GitHub Pages sub-path (/nova-app/). Network-first for the app page so updates are not trapped in cache. */
const CACHE_NAME = 'nova-shell-v61-2';
const SCOPE = self.registration.scope; // e.g. https://mbarahani-web.github.io/nova-app/
const HOME = new URL('./', SCOPE).href;
const EXTRA = ['./index.html', './manifest.webmanifest', './nova.svg', './icons/nova.svg'].map(p => new URL(p, SCOPE).href);

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(async cache => {
        await cache.add(HOME); // the app page itself is required
        await Promise.allSettled(EXTRA.map(url => cache.add(url))); // the rest is best-effort
      })
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k.startsWith('nova-shell-') && k !== CACHE_NAME).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(HOME, copy));
          }
          return response;
        })
        .catch(() => caches.match(HOME).then(cached => cached || new Response('NOVA آفلاین است و نسخهٔ ذخیره‌شده‌ای در دسترس نیست.', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } })))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response && response.ok && response.type === 'basic') {
        const copy = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
      }
      return response;
    }))
  );
});
