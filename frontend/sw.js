// Service worker — mahdollistaa asennuksen puhelimeen (PWA) ja offline-rungon.
//
// TÄRKEÄÄ: käytä network-first-strategiaa sovelluksen rungolle. Sovellus
// päivittyy usein, ja se ajetaan omalta koneelta — joten haetaan AINA tuorein
// versio verkosta kun palvelin on tavoitettavissa, ja turvaudutaan välimuistiin
// vain offline-tilassa. (Aiempi cache-first jätti vanhan app.js:n näkyviin
// päivitysten jälkeen.)
//
// Versionumeroa nostamalla vanha välimuisti tyhjenee aktivoinnissa.
const CACHE = "treeni-v26";
const ASSETS = ["/", "/static/style.css", "/static/app.js", "/static/vendor/three.min.js", "/static/vendor/qrcode.min.js",
  "/static/vendor/icons.svg", "/static/vendor/outfit-latin-wght-normal.woff2",
  "/static/vendor/inter-latin-wght-normal.woff2", "/icon.svg", "/manifest.json"];

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
  // Staattinen runko: VERKKO ENSIN, päivitä välimuisti; offline -> välimuisti.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
