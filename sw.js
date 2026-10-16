/* NOVA PWA shell — safe for GitHub Pages sub-path (/nova-app/).
   - App page: network-first, offline fallback from cache.
   - Leaflet 1.9.4 files (pinned) are cached so the map layer starts offline.
   - OpenStreetMap tiles you have viewed are cached (max 300) so those areas show offline. */
const CACHE_NAME = 'nova-shell-v61-3';
const LIB_CACHE = 'nova-lib-leaflet-1.9.4';
const TILE_CACHE = 'nova-tiles-v1';
const TILE_MAX = 300;

const SCOPE = self.registration.scope; // e.g. https://mbarahani-web.github.io/nova-app/
const HOME = new URL('./', SCOPE).href;
const EXTRA = ['./index.html', './manifest.webmanifest', './nova.svg', './icons/nova.svg'].map(p => new URL(p, SCOPE).href);

const LEAFLET_BASE = 'https://unpkg.com/leaflet@1.9.4/dist/';
const LEAFLET_FILES = ['leaflet.js', 'leaflet.css', 'images/marker-icon.png', 'images/marker-icon-2x.png', 'images/marker-shadow.png', 'images/layers.png', 'images/layers-2x.png'].map(f => LEAFLET_BASE + f);
const TILE_RE = /^https:\/\/[abc]\.tile\.openstreetmap\.org\/\d+\/\d+\/\d+\.png$/;

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(async cache => {
        await cache.add(HOME); // the app page itself is required
        await Promise.allSettled(EXTRA.map(url => cache.add(url))); // the rest is best-effort
      })
      .then(() => caches.open(LIB_CACHE))
      .then(lib => Promise.allSettled(LEAFLET_FILES.map(url => lib.add(new Request(url, { mode: 'cors' }))))) // never blocks install
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

function tileKey(url) {
  return 'https://tile.openstreetmap.org' + new URL(url).pathname; // a/b/c servers share one cache entry
}

async function trimTiles(cache) {
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - TILE_MAX; i++) await cache.delete(keys[i]);
}

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;

  /* Leaflet library files: cache-first, store on first use */
  if (LEAFLET_FILES.includes(request.url)) {
    event.respondWith(
      caches.match(request.url, { ignoreVary: true }).then(cached => cached || fetch(request).then(response => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(LIB_CACHE).then(cache => cache.put(request.url, copy));
        }
        return response;
      }))
    );
    return;
  }

  /* Map tiles: network-first; viewed tiles are kept for offline use */
  if (TILE_RE.test(request.url)) {
    const key = tileKey(request.url);
    event.respondWith(
      fetch(new Request(request.url, { mode: 'cors' }))
        .then(response => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(TILE_CACHE).then(cache => cache.put(key, copy).then(() => trimTiles(cache)));
          }
          return response;
        })
        .catch(() => caches.match(key).then(cached => cached || fetch(request)))
    );
    return;
  }

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
