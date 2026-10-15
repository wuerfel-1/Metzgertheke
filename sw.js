/* Metzgertheke – Service Worker (Offline-Betrieb) */
const CACHE = "metzgertheke-v2";
const NAV_TIMEOUT = 3000;  // ms: so lange aufs Netz warten, dann gespeicherte Seite zeigen
const SHELL = [
  "./", "index.html", "manifest.json",
  "icon.svg", "apple-touch-icon.png",
  "icon-192.png", "icon-512.png", "icon-maskable-512.png",
  "logos/geisselmeier.png", "logos/voelk.png", "logos/struller.png",
  "logos/woerlein.svg", "logos/schneck.png"
];

self.addEventListener("install", e => {
  e.waitUntil(
    // cache:"reload" -> am HTTP-Cache vorbei (GitHub Pages: max-age=600), sonst landet evtl. eine alte Kopie im Cache.
    // Jede Datei einzeln: schlägt eine fehl, die Kopie aus dem alten Cache übernehmen statt die ganze Installation abzubrechen.
    caches.open(CACHE).then(c => Promise.all(SHELL.map(u =>
      c.add(new Request(u, { cache: "reload" }))
        .catch(() => caches.match(u).then(old => old && c.put(u, old)))
        .catch(() => {})
    ))).then(() => self.skipWaiting())
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

  // Seite selbst (HTML): Netz zuerst, damit Änderungen sofort ankommen; offline bzw. nach NAV_TIMEOUT gespeicherte Seite
  if (req.mode === "navigate") {
    const net = fetch(req.url, { cache: "no-cache", credentials: "same-origin" }).then(res => {
      if (res && res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put("./", copy)).catch(() => {}); }
      return res;
    });
    const fallback = () => caches.match(req, { ignoreSearch: true }).then(r => r || caches.match("./"));
    e.respondWith(new Promise(resolve => {
      const timer = setTimeout(() => fallback().then(r => r && resolve(r)), NAV_TIMEOUT);
      net.then(res => { clearTimeout(timer); resolve(res); })
         .catch(() => { clearTimeout(timer); fallback().then(r => resolve(r || Response.error())); });
    }));
    return;
  }

  // Übrige App-Shell (Icons, Logos …): Cache zuerst, im Hintergrund am HTTP-Cache vorbei aktualisieren
  e.respondWith(
    caches.match(req, { ignoreSearch: true }).then(cached => {
      const net = fetch(req, { cache: "no-cache" }).then(res => {
        if (res && res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {}); }
        return res;
      }).catch(() => cached);
      return cached || net;
    })
  );
});
