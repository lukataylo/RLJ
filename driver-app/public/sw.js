// Minimal offline shell service worker for the RLJ Driver PWA.
// Cache-first for the app shell; network passthrough (never caches) for the
// orchestrator API and map tiles so live data / telemetry are always fresh.
const CACHE = "rlj-driver-v1";
const SHELL = ["/", "/index.html", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // Never intercept cross-origin (tiles, fonts CDN) or API calls.
  if (url.origin !== self.location.origin) return;
  e.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).catch(() => caches.match("/index.html"))),
  );
});
