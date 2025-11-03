const swUrl = new URL(self.location.href);
const CACHE_VERSION = swUrl.searchParams.get('v') || 'v1';
const CACHE_NAME = `etna-monitor-${CACHE_VERSION}`;
const STATIC_CACHE = `etna-static-${CACHE_VERSION}`;
const API_CACHE = `etna-api-${CACHE_VERSION}`;
const VERSION_SUFFIX = `?v=${CACHE_VERSION}`;

const STATIC_ASSETS = [
  '/',
  `/static/css/style.css${VERSION_SUFFIX}`,
  `/static/css/theme.css${VERSION_SUFFIX}`,
  `/static/css/accessibility.css${VERSION_SUFFIX}`,
  `/static/js/dashboard.js${VERSION_SUFFIX}`,
  `/static/js/chart.js${VERSION_SUFFIX}`,
  `/static/js/nav.js${VERSION_SUFFIX}`,
  `/static/manifest.json${VERSION_SUFFIX}`,
  'https://cdn.plot.ly/plotly-2.32.0.min.js',
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap'
];

const API_ENDPOINTS = [
  '/api/status',
  '/api/curva',
  '/healthz'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== STATIC_CACHE && cacheName !== API_CACHE) {
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);
  
  if (API_ENDPOINTS.some(endpoint => url.pathname.startsWith(endpoint))) {
    event.respondWith(
      caches.open(API_CACHE).then(cache => {
        return fetch(request).then(response => {
          if (response.ok) {
            const responseClone = response.clone();
            cache.put(request, responseClone);
          }
          return response;
        }).catch(() => {
          return cache.match(request);
        });
      })
    );
    return;
  }
  
  const assetKey = `${url.pathname}${url.search}`;
  if (STATIC_ASSETS.includes(assetKey) || STATIC_ASSETS.includes(url.pathname) || request.destination === 'style' || request.destination === 'script') {
    event.respondWith(
      caches.match(request).then(response => {
        return response || fetch(request).then(fetchResponse => {
          return caches.open(STATIC_CACHE).then(cache => {
            cache.put(request, fetchResponse.clone());
            return fetchResponse;
          });
        });
      })
    );
    return;
  }
  
  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
});

self.addEventListener('sync', event => {
  if (event.tag === 'background-sync') {
    event.waitUntil(doBackgroundSync());
  }
});

function doBackgroundSync() {
  return fetch('/api/status').catch(() => {});
}
