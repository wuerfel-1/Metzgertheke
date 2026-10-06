/* Metzgertheke – Service Worker (Offline-Betrieb) */
const CACHE = "metzgertheke-v1";
const SHELL = [
  "./", "index.html", "manifest.json",
  "icon.svg", "apple-touch-icon.png",
  "icon-192.png", "icon-512.png", "icon-maskable-512.png",
  "logos/geisselmeier.png", "logos/voelk.png", "logos/struller.png",
  "logos/woerlein.svg", "logos/schneck.png"
];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()).catch(() => {})
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;  // Fonts etc. -> Browser-Standard

  const isData = url.pathname.endsWith("data.json") || url.pathname.endsWith("mittagstisch.json");

  if (isData) {
    // Daten: Netz zuerst, bei Offline letzte gespeicherte Version (Query ?v= ignorieren)
    const keyReq = new Request(url.pathname);
    e.respondWith(
      fetch(req).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(keyReq, copy)).catch(() => {});
        return res;
      }).catch(() => caches.match(keyReq))
    );
    return;
  }

  // App-Shell: Cache zuerst, im Hintergrund aktualisieren
  e.respondWith(
    caches.match(req, { ignoreSearch: true }).then(cached => {
      const net = fetch(req).then(res => {
        if (res && res.ok) caches.open(CACHE).then(c => c.put(req, res.clone())).catch(() => {});
        return res;
      }).catch(() => cached);
      return cached || net;
    })
  );
});
