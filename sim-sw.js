/* sim-sw.js — Service Worker for SqueezeOS Trading Simulator */
'use strict';

const CACHE_NAME = 'squeezeos-sim-v1';
const STATIC_CACHE = 'squeezeos-static-v1';
const DATA_CACHE = 'squeezeos-data-v1';

const STATIC_ASSETS = [
  '/trading-simulator.html',
  '/trading-sim-styles.css',
  '/trading-sim-engine.js',
  '/trading-sim-options.js',
  '/trading-sim-education.js',
  '/trading-sim-social.js',
  '/trading-sim-ai.js',
  '/sim-manifest.json',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js'
];

const NETWORK_FIRST_PATTERNS = [
  /api\.openai\.com/,
  /api\.anthropic\.com/,
  /api\.groq\.com/,
  /generativelanguage\.googleapis\.com/
];

const CACHE_FIRST_PATTERNS = [
  /cdn\.jsdelivr\.net/,
  /fonts\.googleapis\.com/,
  /fonts\.gstatic\.com/
];

/* ── Install ── */
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => cache.addAll(STATIC_ASSETS.filter(u => !u.startsWith('http'))))
      .then(() => self.skipWaiting())
      .catch(err => console.warn('[SW] Static cache failed:', err))
  );
});

/* ── Activate ── */
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys
        .filter(k => k !== STATIC_CACHE && k !== DATA_CACHE && k !== CACHE_NAME)
        .map(k => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

/* ── Fetch ── */
self.addEventListener('fetch', event => {
  const url = event.request.url;

  // Skip non-GET and Chrome extensions
  if (event.request.method !== 'GET') return;
  if (url.startsWith('chrome-extension://')) return;
  if (url.includes('localhost') && url.includes(':')) {
    // Dev environment — pass through
  }

  // AI API calls — network only, no cache
  if (NETWORK_FIRST_PATTERNS.some(p => p.test(url))) {
    event.respondWith(fetch(event.request).catch(() =>
      new Response(JSON.stringify({ error: 'Offline — AI features require internet connection' }), {
        headers: { 'Content-Type': 'application/json' },
        status: 503
      })
    ));
    return;
  }

  // CDN assets — cache first
  if (CACHE_FIRST_PATTERNS.some(p => p.test(url))) {
    event.respondWith(cacheFirst(event.request, DATA_CACHE));
    return;
  }

  // App shell — stale while revalidate
  event.respondWith(staleWhileRevalidate(event.request));
});

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    return new Response('Offline', { status: 503 });
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(request);

  const fetchPromise = fetch(request).then(response => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => null);

  return cached || fetchPromise || new Response('Offline', { status: 503 });
}

/* ── Background Sync ── */
self.addEventListener('sync', event => {
  if (event.tag === 'sync-portfolio') {
    event.waitUntil(_syncPortfolio());
  }
});

async function _syncPortfolio() {
  // Placeholder for future backend sync
  const clients = await self.clients.matchAll();
  clients.forEach(client => client.postMessage({ type: 'SYNC_COMPLETE', ts: Date.now() }));
}

/* ── Push Notifications ── */
self.addEventListener('push', event => {
  if (!event.data) return;

  let data;
  try { data = event.data.json(); } catch { data = { title: 'SqueezeOS', body: event.data.text() }; }

  const options = {
    body: data.body || 'Check your trading simulator!',
    icon: '/icons/sim-icon-192.png',
    badge: '/icons/sim-icon-72.png',
    vibrate: [200, 100, 200],
    data: { url: data.url || '/trading-simulator.html' },
    actions: [
      { action: 'open', title: 'Open Simulator' },
      { action: 'dismiss', title: 'Dismiss' }
    ],
    tag: data.tag || 'squeezeos-notification',
    renotify: true
  };

  event.waitUntil(self.registration.showNotification(data.title || 'SqueezeOS Simulator', options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  if (event.action === 'dismiss') return;

  const url = event.notification.data?.url || '/trading-simulator.html';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      const existing = windowClients.find(c => c.url.includes('trading-simulator'));
      if (existing) return existing.focus();
      return clients.openWindow(url);
    })
  );
});

/* ── Message handler ── */
self.addEventListener('message', event => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();

  if (event.data?.type === 'CACHE_URLS') {
    const urls = event.data.urls || [];
    caches.open(STATIC_CACHE).then(cache => cache.addAll(urls));
  }
});
