// 자동 생성 파일 — scripts/generate_site.py 가 매주 배포 시점마다 다시 씀.
// CACHE_VERSION이 바뀌면(=매주 월요일 재배포) 아래 activate 단계에서
// 이전 주 캐시를 지우고 새 캐시로 자동 교체한다.
const CACHE_VERSION = "20260713100200";
const CACHE_NAME = "gbsa-menu-" + CACHE_VERSION;
const PRECACHE_URLS = ["./", "index.html", "styles.css", "manifest.json", "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png"];
const FONT_HOSTS = ["fonts.googleapis.com", "fonts.gstatic.com"];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(PRECACHE_URLS);
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys
          .filter(function (key) { return key !== CACHE_NAME; })
          .map(function (key) { return caches.delete(key); })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

function staleWhileRevalidate(request) {
  return caches.open(CACHE_NAME).then(function (cache) {
    return cache.match(request).then(function (cached) {
      var networkFetch = fetch(request).then(function (response) {
        if (response && response.status === 200) {
          cache.put(request, response.clone());
        }
        return response;
      }).catch(function () { return cached; });
      return cached || networkFetch;
    });
  });
}

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET") return;

  var url = new URL(request.url);

  // 페이지 이동(주소창 진입, 새로고침 등): 캐시 우선, 네트워크는 폴백.
  // 매주 배포 시 CACHE_VERSION이 바뀌어 캐시가 자동 교체되므로
  // 평소에는 서버 요청 없이 즉시 로드된다.
  if (request.mode === "navigate") {
    event.respondWith(
      caches.match("index.html").then(function (cached) {
        return cached || fetch(request);
      })
    );
    return;
  }

  // 구글 폰트: 자주 안 바뀌므로 캐시 우선 + 백그라운드 갱신.
  if (FONT_HOSTS.indexOf(url.hostname) !== -1) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  // 같은 출처의 정적 자산(css, manifest, 아이콘 등): 캐시 우선.
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(request).then(function (cached) {
        return cached || fetch(request).then(function (response) {
          if (response && response.status === 200) {
            var copy = response.clone();
            caches.open(CACHE_NAME).then(function (cache) { cache.put(request, copy); });
          }
          return response;
        });
      })
    );
  }
});
