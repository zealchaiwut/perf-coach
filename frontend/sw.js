/* PWA service worker. Cache name includes the repo VERSION. */
var CACHE = "pc-shell-v0.2.0";
var PRECACHE = [
  "/m/today",
  "/m/gym",
  "/m/body",
  "/css/m.css",
  "/js/lib/app-common.js",
  "/js/m/store.js",
  "/js/m/sync.js",
  "/js/m/status.js",
  "/js/m/shell.js",
  "/js/m/today.js",
  "/js/m/gym.js",
  "/js/m/timer.js",
  "/js/m/body.js",
  "/js/m/tss.js",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/manifest.webmanifest"
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll(PRECACHE);
    }).catch(function () {
      return undefined;
    })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) {
        return caches.delete(k);
      }));
    }).then(function () {
      return self.clients.claim();
    })
  );
});

function networkWithTimeout(request, ms) {
  var ctrl = new AbortController();
  var t = setTimeout(function () { ctrl.abort(); }, ms);
  return fetch(request, { signal: ctrl.signal, credentials: "same-origin" }).finally(function () {
    clearTimeout(t);
  });
}

self.addEventListener("fetch", function (event) {
  var req = event.request;
  var url = new URL(req.url);
  if (req.method !== "GET") return;

  if (url.pathname === "/api/mobile/bundle") {
    event.respondWith(
      networkWithTimeout(req, 4000).catch(function () {
        return new Response("", { status: 504, statusText: "bundle-timeout" });
      })
    );
    return;
  }

  if (url.pathname.indexOf("/api/") === 0) {
    event.respondWith(fetch(req));
    return;
  }

  var isFont = url.hostname.indexOf("fonts.g") !== -1 || url.hostname.indexOf("gstatic") !== -1;
  if (isFont) {
    event.respondWith(
      caches.open(CACHE).then(function (cache) {
        return cache.match(req).then(function (hit) {
          var net = fetch(req).then(function (res) {
            if (res && res.ok) cache.put(req, res.clone());
            return res;
          }).catch(function () { return hit; });
          return hit || net;
        });
      })
    );
    return;
  }

  event.respondWith(
    caches.match(req).then(function (hit) {
      if (hit) return hit;
      if (url.pathname.indexOf("/m/") === 0) {
        return caches.match("/m/today").then(function (shell) {
          return shell || fetch(req);
        });
      }
      return fetch(req).then(function (res) {
        return res;
      }).catch(function () {
        return caches.match("/m/today");
      });
    })
  );
});

self.addEventListener("message", function (event) {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});
