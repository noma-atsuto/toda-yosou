// オフラインでも前回の予想を見られるようにするための仕組み
const CACHE = "toda-v1";
const SHELL = ["./", "index.html", "style.css", "app.js", "icon-180.png", "manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

// 予想データは「まずネット、だめなら保存済み」、画面の部品も新しいものを優先
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request).then((res) => {
      const copy = res.clone();
      const url = new URL(e.request.url);
      url.search = "";
      caches.open(CACHE).then((c) => c.put(url.toString(), copy));
      return res;
    }).catch(() => {
      const url = new URL(e.request.url);
      url.search = "";
      return caches.match(url.toString());
    })
  );
});
