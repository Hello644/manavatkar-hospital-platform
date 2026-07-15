// Minimal service worker so the kiosk is installable and the shell survives a
// brief network drop. Punch store-and-forward is handled in the page via
// IndexedDB (see kiosk.html), not here.
const CACHE = "attendance-kiosk-v1";

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  // Never cache the punch POST; let it hit the network (page queues on failure).
  if (event.request.method !== "GET") return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
