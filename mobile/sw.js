// 오프라인으로 쓰려고 파일 몇 개를 캐시에 둔다.
// 판을 올리면 CACHE 이름을 바꾼다 - 옛 캐시가 남아 새 화면이 안 나오는 것을 막는다.
const CACHE = "jangbu-v1";
const 파일 = ["./", "./index.html", "./manifest.webmanifest",
              "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(파일)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// 캐시부터 주고, 없으면 받아 온다. 글꼴은 받아 오지 못해도 기기 글꼴로 돈다.
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  e.respondWith(caches.match(e.request).then((맞음) => 맞음 || fetch(e.request)
    .then((답) => {
      if (답 && 답.status === 200 && 답.type === "basic") {
        const 복 = 답.clone();
        caches.open(CACHE).then((c) => c.put(e.request, 복));
      }
      return 답;
    })
    .catch(() => caches.match("./index.html"))));
});
