// Service worker — mahdollistaa asennuksen puhelimeen (PWA) ja offline-rungon.
const CACHE = "treeni-v1";
const ASSETS = ["/", "/static/style.css", "/static/app.js", "/icon.svg", "/manifest.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // API: aina verkosta (data on tuoretta), ei välimuistia.
  if (url.pathname.startsWith("/api/")) return;
  // Staattinen runko: välimuisti ensin, päivitä taustalla.
  e.respondWith(
    caches.match(e.request).then((cached) =>
      cached ||
      fetch(e.request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      }).catch(() => cached)
    )
  );
});
