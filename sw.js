/* NOVA v62 PWA shell: scope-relative paths support GitHub Pages project sites. */
const CACHE_NAME = 'nova-shell-v62-8';
const BASE_URL = new URL('./', self.registration.scope);
const SHELL = ['', 'manifest.webmanifest', 'nova-192.png', 'nova-512.png', 'nova-maskable-512.png', 'nova-badge-96.png'].map(path => new URL(path, BASE_URL).toString());
const APP_URL = new URL('./', BASE_URL).toString();
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('nova-shell-') && key !== CACHE_NAME).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).then(response => {
      if (response && response.ok) caches.open(CACHE_NAME).then(cache => cache.put(request, response.clone()));
      return response;
    }).catch(() => caches.match(request).then(cached => cached || caches.match(APP_URL).then(home => home || new Response('NOVA آفلاین است و نسخهٔ ذخیره‌شده‌ای در دسترس نیست.', {status: 503, headers: {'Content-Type':'text/plain; charset=utf-8'}})))));
    return;
  }
  if (url.pathname.endsWith('/news.json')) {
    event.respondWith(fetch(request, {cache: 'no-store'}).then(response => {
      if (response && response.ok) caches.open(CACHE_NAME).then(cache => cache.put(request, response.clone()));
      return response;
    }).catch(() => caches.match(request, {ignoreSearch: true}).then(cached => cached || new Response('{}', {status: 503, headers: {'Content-Type':'application/json'}}))));
    return;
  }
  event.respondWith(caches.match(request).then(cached => cached || fetch(request).then(response => {
    if (response && response.ok && response.type === 'basic') caches.open(CACHE_NAME).then(cache => cache.put(request, response.clone()));
    return response;
  })));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || './', BASE_URL).toString();
  event.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(list => {
    for (const client of list) {
      if (client.url.startsWith(APP_URL) && 'focus' in client) return client.focus();
    }
    return self.clients.openWindow(target);
  }));
});
