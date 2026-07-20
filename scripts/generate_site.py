"""
[6단계] 웹페이지 생성 스크립트 (v4 — Tailwind 기반 목업 디자인을 실제 데이터에 그대로 적용)

이 스크립트는 순수 "렌더러"다. 분류/예외처리/공휴일 판정은 모두
merge_archive.py에서 끝내고, data/archive.json에 정리된 결과만 그림으로 그린다.

v4에서 바뀐 것:
- 사용자가 검토/승인한 Tailwind 기반 프리뷰(index-desktop.html / index-mobile.html)의
  마크업·클래스·색상·인터랙션을 그대로 프로덕션에 이식했다.
- 서버(Python)는 이제 HTML 조각을 만들지 않고, archive.json을 그대로 JSON으로
  임베드만 한다. 화면 렌더링은 전부 클라이언트 JS(아래 PAGE_TEMPLATE 안의 <script>)가
  담당한다 (데스크톱 3열 + 공용 날짜바 / 모바일 아코디언을 하나의 반응형 페이지에서
  같은 로직으로 처리).
- 데스크톱 공용 날짜바는 3개 건물의 날짜를 합집합(union)한 뒤 5일 단위로 슬라이딩
  윈도우를 유지한다 — 날짜가 계속 쌓여도 레이아웃이 깨지지 않는다.
"""

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

ARCHIVE_PATH = Path(__file__).parent.parent / "data" / "archive.json"
SITE_DIR = Path(__file__).parent.parent / "output" / "site"
ASSETS_DIR = Path(__file__).parent.parent / "assets"

KST = timezone(timedelta(hours=9))

# 서비스 워커가 캐시할 정적 자산 목록 (sw.js 기준 상대경로).
# 매주 배포 때마다 CACHE_VERSION이 바뀌므로, 이 목록 자체는 안 바뀌어도
# 브라우저는 새 버전의 캐시로 자동 교체한다.
SW_PRECACHE_URLS = [
    "./",
    "index.html",
    "styles.css",
    "manifest.json",
    "icons/icon-192.png",
    "icons/icon-512.png",
    "icons/apple-touch-icon.png",
]

SW_TEMPLATE = """// 자동 생성 파일 — scripts/generate_site.py 가 매주 배포 시점마다 다시 씀.
// CACHE_VERSION이 바뀌면(=매주 월요일 재배포) 아래 activate 단계에서
// 이전 주 캐시를 지우고 새 캐시로 자동 교체한다.
const CACHE_VERSION = "__SW_CACHE_VERSION__";
const CACHE_NAME = "gbsa-menu-" + CACHE_VERSION;
const PRECACHE_URLS = __SW_PRECACHE_URLS_JSON__;
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
"""

CHANNEL_ORDER = ["gbsa", "rdb_center", "nano_gaeram"]


def build_menu_data(archive: dict) -> dict:
    """archive.json(day가 dict)을 프론트에서 쓰기 좋은 형태(day가 정렬된 list)로 변환."""
    menu_data = {}
    for name, channel in archive.items():
        days = sorted(channel.get("days", {}).values(), key=lambda d: d["date"])
        menu_data[name] = {
            "label": channel.get("label", name),
            "post_url": channel.get("post_url"),
            "days": days,
        }
    return menu_data


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>광교테크노밸리 구내식당 식단표</title>
<link rel="manifest" href="manifest.json">
<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">
<link rel="icon" href="icons/icon-192.png">
<meta name="theme-color" content="#00288e">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="구내식당 식단표">
<link rel="stylesheet" href="styles.css">
<link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;600;700;800&display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap" rel="stylesheet"/>
<style>
  .material-symbols-outlined { font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24; }
  body { font-family: 'Hanken Grotesk', 'Pretendard', 'Noto Sans KR', sans-serif; background-color: #f7f9fb; color: #191c1e; -webkit-font-smoothing: antialiased; }
</style>
</head>
<body class="bg-surface">

<header class="sticky top-0 z-50 w-full bg-surface-container-low/80 backdrop-blur-md border-b border-outline-variant">
  <div class="max-w-[1280px] mx-auto px-4 md:px-8 py-3 md:py-4 flex items-center justify-between">
    <div class="flex items-center gap-2">
      <span class="material-symbols-outlined text-primary text-[20px] md:text-[24px]">restaurant</span>
      <h1 class="text-[16px] md:text-headline-md font-bold text-primary leading-tight whitespace-nowrap">광교테크노밸리 구내식당 식단표</h1>
    </div>
    <span class="hidden md:inline text-label-md text-on-surface-variant">마지막 업데이트: __UPDATED_AT__</span>
  </div>
</header>

<main class="max-w-[1280px] mx-auto px-4 md:px-8 py-5 md:py-8 space-y-4 md:space-y-6">
  <p class="md:hidden text-label-md text-on-surface-variant">마지막 업데이트 : __UPDATED_AT__</p>

  <div id="installBanner" class="hidden items-start justify-between gap-3 bg-blue-50 border border-blue-100 rounded-xl p-3 md:p-4">
    <div class="flex items-start gap-2 md:gap-3">
      <span class="material-symbols-outlined text-accent-blue text-[18px] md:text-[24px]">install_mobile</span>
      <p id="installMsg" class="text-body-sm text-blue-900 flex-1"></p>
    </div>
    <div class="flex items-center gap-2 flex-shrink-0">
      <button id="installBtn" type="button" style="display:none;" class="text-label-md font-semibold text-white bg-primary rounded-lg px-3 py-1.5 whitespace-nowrap">설치</button>
      <button id="installDismiss" type="button" class="text-label-md text-blue-700 hover:text-blue-900">닫기</button>
    </div>
  </div>

  <div id="global-date-bar" class="hidden md:flex justify-center py-2"></div>

  <div id="accordion-root" class="space-y-3 md:space-y-0 md:grid md:grid-cols-3 md:gap-6 md:items-start"></div>
</main>

<p class="md:hidden max-w-[1280px] mx-auto px-4 pb-4 text-[12px] text-slate-400 leading-relaxed">실제 운영 사정에 따라 메뉴가 변경될 수 있으니, 정확한 정보는 원본 게시글을 확인해주세요.</p>
<div class="md:hidden h-6"></div>

<footer class="hidden md:block w-full py-8 px-8 bg-surface-container-low border-t border-outline-variant mt-6">
  <div class="max-w-[1280px] mx-auto flex justify-between items-center">
    <p class="text-body-sm text-on-surface-variant">실제 운영 사정에 따라 메뉴가 변경될 수 있으니, 정확한 정보는 원본 게시글을 확인해주세요.</p>
    <p class="text-label-md font-bold text-secondary">광교테크노밸리 구내식당 식단표</p>
  </div>
</footer>

<script>
const MENU_DATA = __MENU_DATA_JSON__;
const FACILITY_ORDER = __FACILITY_ORDER_JSON__;
</script>
<script>
(function () {
  var BREAKPOINT = 768;
  function IS_DESKTOP() { return window.matchMedia("(min-width: " + BREAKPOINT + "px)").matches; }

  var GROUP_COLORS = ["text-accent-blue", "text-emerald-600", "text-violet-600", "text-amber-600", "text-rose-500"];
  var GROUP_BORDER_COLORS = [
    "border-blue-200 group-hover:border-blue-300",
    "border-emerald-200 group-hover:border-emerald-300",
    "border-violet-200 group-hover:border-violet-300",
    "border-amber-200 group-hover:border-amber-300",
    "border-rose-200 group-hover:border-rose-300",
  ];
  var WEEKDAY_KR = ["일", "월", "화", "수", "목", "금", "토"];

  var state = {}; // 모바일 전용: { key: { expanded, dateIndex } }
  var ALL_DATES = [];
  var WINDOW_SIZE = 5;
  var windowStart = 0;
  var globalActiveDate = null;

  function pad(n) { return String(n).padStart(2, "0"); }
  function todayISO() {
    var d = new Date();
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function unionDates() {
    var seen = {};
    var all = [];
    FACILITY_ORDER.forEach(function (key) {
      (MENU_DATA[key].days || []).forEach(function (d) {
        if (!seen[d.date]) { seen[d.date] = true; all.push(d.date); }
      });
    });
    return all.sort();
  }

  // 날짜 배열(오름차순 정렬)에서 "오늘"에 해당하는 기본 인덱스를 찾는다.
  // 1) 오늘과 정확히 일치하는 날짜가 있으면 그 인덱스.
  // 2) 없으면(주말/공휴일/데이터 누락 등) 오늘보다 이전인 날짜 중 가장 최근 날짜.
  //    -- 이전 버전은 "오늘이 마지막 날짜보다 미래인지"만 판별해서, 두 주 사이의
  //       주말처럼 배열 "중간"에 뚫린 구멍에 오늘이 걸리면 무조건 배열의
  //       첫 번째(가장 오래된) 날짜로 튕겨버리는 버그가 있었다.
  // 3) 오늘보다 이전 날짜가 하나도 없으면(아카이브 시작 전) 가장 이른 날짜.
  function findDefaultIndex(dates, t) {
    if (!dates.length) return 0;
    var exact = dates.indexOf(t);
    if (exact !== -1) return exact;
    for (var i = dates.length - 1; i >= 0; i--) {
      if (dates[i] < t) return i;
    }
    return 0;
  }

  function initState() {
    ALL_DATES = unionDates();
    var t = todayISO();
    var idx = findDefaultIndex(ALL_DATES, t);
    globalActiveDate = ALL_DATES.length ? ALL_DATES[idx] : null;
    windowStart = Math.min(
      Math.max(0, idx - Math.floor(WINDOW_SIZE / 2)),
      Math.max(0, ALL_DATES.length - WINDOW_SIZE)
    );

    FACILITY_ORDER.forEach(function (key) {
      var fDays = MENU_DATA[key].days || [];
      var fDates = fDays.map(function (d) { return d.date; });
      var fIdx = findDefaultIndex(fDates, t);
      state[key] = { expanded: false, dateIndex: fIdx };
    });
  }

  function fmtDatePillShort(day) {
    var m = parseInt(day.date.slice(5, 7), 10);
    var d = parseInt(day.date.slice(8, 10), 10);
    var weekdayShort = (day.weekday_label || "").replace("요일", "");
    return weekdayShort + " · " + m + "월 " + d + "일";
  }

  function fmtDateButtonLabel(dateStr) {
    var p = dateStr.split("-").map(Number);
    var dt = new Date(p[0], p[1] - 1, p[2]);
    return p[1] + "월 " + p[2] + "일 (" + WEEKDAY_KR[dt.getDay()] + ")";
  }

  function stripMealPrefix(name) {
    return (name || "").replace(/^(중식|석식)\\s*/, "");
  }

  function renderMealSection(title, badgeClass, groups) {
    var nonEmpty = (groups || []).filter(function (g) { return g.items && g.items.length > 0; });
    if (nonEmpty.length === 0) {
      return (
        '<section class="space-y-3">' +
          '<div class="flex items-center gap-2">' +
            '<span class="px-2 py-1 ' + badgeClass + ' text-white text-[10px] font-bold rounded uppercase tracking-wider">' + title + '</span>' +
            '<div class="h-px flex-1 bg-slate-100"></div>' +
          '</div>' +
          '<p class="text-body-sm text-on-surface-variant py-2">정보 없음</p>' +
        '</section>'
      );
    }
    var cards = nonEmpty.map(function (g, i) {
      var color = GROUP_COLORS[i % GROUP_COLORS.length];
      var borderColor = GROUP_BORDER_COLORS[i % GROUP_BORDER_COLORS.length];
      var displayName = stripMealPrefix(g.group_name);
      var items = g.items.map(function (item) {
        return '<li class="text-body-sm text-on-surface-variant leading-relaxed">' + item + '</li>';
      }).join("");
      return (
        '<div class="group">' +
          '<div class="flex justify-between items-baseline mb-1">' +
            '<span class="text-label-md ' + color + ' font-extrabold tracking-wide">' + displayName + '</span>' +
          '</div>' +
          '<div class="p-4 rounded-lg border bg-white ' + borderColor + ' transition-colors">' +
            '<ul class="space-y-1">' + items + '</ul>' +
          '</div>' +
        '</div>'
      );
    }).join("");
    return (
      '<section class="space-y-3">' +
        '<div class="flex items-center gap-2">' +
          '<span class="px-2 py-1 ' + badgeClass + ' text-white text-[10px] font-bold rounded uppercase tracking-wider">' + title + '</span>' +
          '<div class="h-px flex-1 bg-slate-100"></div>' +
        '</div>' +
        cards +
      '</section>'
    );
  }

  function renderDayContent(day) {
    if (!day) {
      return '<p class="text-body-sm text-on-surface-variant py-2">정보 없음</p>';
    }
    if (day.is_holiday) {
      return (
        '<div class="bg-blue-50 border border-blue-100 rounded-xl p-4 flex items-start gap-3">' +
          '<span class="material-symbols-outlined text-accent-blue">celebration</span>' +
          '<div>' +
            '<p class="text-body-sm font-semibold text-blue-900">' + (day.holiday_name || "공휴일") + '</p>' +
            '<p class="text-body-sm text-blue-700">구내식당이 운영되지 않습니다.</p>' +
          '</div>' +
        '</div>'
      );
    }
    return (
      '<div class="grid grid-cols-1 gap-6">' +
        renderMealSection("중식", "bg-accent-blue", day.lunch_groups || []) +
        renderMealSection("석식", "bg-slate-800", day.dinner_groups || []) +
      '</div>'
    );
  }

  // ---------- 데스크톱: 상단 공용 날짜 선택바 (합집합 + 5일 슬라이딩 윈도우) ----------
  function renderGlobalDateBar() {
    if (ALL_DATES.length === 0) return "";
    var maxStart = Math.max(0, ALL_DATES.length - WINDOW_SIZE);
    windowStart = Math.min(Math.max(0, windowStart), maxStart);
    var atMin = windowStart <= 0;
    var atMax = windowStart + WINDOW_SIZE >= ALL_DATES.length;
    var slice = ALL_DATES.slice(windowStart, windowStart + WINDOW_SIZE);

    var buttons = slice.map(function (dateStr) {
      var active = dateStr === globalActiveDate;
      return (
        '<button type="button" data-action="global-date" data-date="' + dateStr + '" class="px-4 py-2 rounded-full text-body-sm font-semibold transition-colors ' +
        (active ? "bg-primary text-white shadow-sm" : "text-on-surface-variant hover:bg-slate-100") + '">' +
          fmtDateButtonLabel(dateStr) +
        '</button>'
      );
    }).join("");

    return (
      '<div class="flex items-center gap-1 bg-white rounded-full p-1.5 border border-slate-200 shadow-sm w-fit mx-auto">' +
        '<button type="button" data-action="global-prev" ' + (atMin ? "disabled" : "") + ' class="w-9 h-9 flex items-center justify-center rounded-full hover:bg-slate-100 transition-colors disabled:opacity-30 disabled:hover:bg-transparent">' +
          '<span class="material-symbols-outlined text-on-surface-variant text-[20px]">chevron_left</span>' +
        '</button>' +
        buttons +
        '<button type="button" data-action="global-next" ' + (atMax ? "disabled" : "") + ' class="w-9 h-9 flex items-center justify-center rounded-full hover:bg-slate-100 transition-colors disabled:opacity-30 disabled:hover:bg-transparent">' +
          '<span class="material-symbols-outlined text-on-surface-variant text-[20px]">chevron_right</span>' +
        '</button>' +
      '</div>'
    );
  }

  function renderFacilityDesktop(key) {
    var facility = MENU_DATA[key];
    var day = (facility.days || []).find(function (d) { return d.date === globalActiveDate; });
    return (
      '<div class="bg-white border-2 border-accent-blue shadow-md rounded-xl overflow-hidden transition-all" data-key="' + key + '">' +
        '<div class="p-4 flex items-center gap-3 bg-slate-50/50 border-b border-slate-100">' +
          '<div class="w-2 h-2 rounded-full bg-accent-blue"></div>' +
          '<h3 class="text-body-lg font-bold text-on-surface">' + facility.label.replace(" 구내식당", "") + '</h3>' +
        '</div>' +
        '<div class="p-4 space-y-6">' +
          renderDayContent(day) +
          (facility.post_url
            ? '<a href="' + facility.post_url + '" target="_blank" class="inline-flex items-center gap-1 text-label-md text-secondary hover:text-primary transition-colors">원본 게시글 보기 <span class="material-symbols-outlined text-[16px]">arrow_outward</span></a>'
            : "") +
        '</div>' +
      '</div>'
    );
  }

  // ---------- 모바일: 건물별 개별 날짜 아코디언 (기본 전부 접힘) ----------
  function renderFacilityMobile(key) {
    var facility = MENU_DATA[key];
    var s = state[key];
    var days = facility.days || [];
    var day = days[s.dateIndex];
    var atMin = s.dateIndex === 0;
    var atMax = s.dateIndex === days.length - 1;
    var activeDot = s.expanded
      ? '<div class="w-2 h-2 rounded-full bg-accent-blue"></div>'
      : '<div class="w-2 h-2 rounded-full bg-slate-300"></div>';

    var body = "";
    if (s.expanded) {
      body =
        '<div class="p-4 space-y-6">' +
          '<div class="flex items-center justify-between bg-slate-50 rounded-full px-2 py-1 border border-slate-200">' +
            '<button type="button" data-action="prev" data-key="' + key + '" ' + (atMin ? "disabled" : "") + ' class="w-8 h-8 flex items-center justify-center rounded-full hover:bg-slate-200 transition-colors disabled:opacity-30 disabled:hover:bg-transparent">' +
              '<span class="material-symbols-outlined text-on-surface-variant text-[20px]">chevron_left</span>' +
            '</button>' +
            '<span class="text-label-md font-bold text-on-surface">' + (day ? fmtDatePillShort(day) : "") + '</span>' +
            '<button type="button" data-action="next" data-key="' + key + '" ' + (atMax ? "disabled" : "") + ' class="w-8 h-8 flex items-center justify-center rounded-full hover:bg-slate-200 transition-colors disabled:opacity-30 disabled:hover:bg-transparent">' +
              '<span class="material-symbols-outlined text-on-surface-variant text-[20px]">chevron_right</span>' +
            '</button>' +
          '</div>' +
          renderDayContent(day) +
          (facility.post_url
            ? '<a href="' + facility.post_url + '" target="_blank" class="inline-flex items-center gap-1 text-label-md text-secondary hover:text-primary transition-colors">원본 게시글 보기 <span class="material-symbols-outlined text-[16px]">arrow_outward</span></a>'
            : "") +
        '</div>';
    }

    return (
      '<div class="' + (s.expanded ? "bg-white border-2 border-accent-blue shadow-md" : "bg-white/80 border border-slate-200 shadow-sm hover:border-accent-blue/30") + ' rounded-xl overflow-hidden transition-all" data-key="' + key + '">' +
        '<button type="button" class="w-full p-4 flex items-center justify-between text-left ' + (s.expanded ? "bg-slate-50/50 border-b border-slate-100" : "") + '" data-action="toggle" data-key="' + key + '">' +
          '<div class="flex items-center gap-3">' +
            activeDot +
            '<h3 class="text-body-lg ' + (s.expanded ? "font-bold" : "font-semibold") + ' text-on-surface">' + facility.label.replace(" 구내식당", "") + '</h3>' +
          '</div>' +
          '<span class="material-symbols-outlined ' + (s.expanded ? "text-accent-blue" : "text-on-surface-variant") + '">' + (s.expanded ? "expand_less" : "expand_more") + '</span>' +
        '</button>' +
        body +
      '</div>'
    );
  }

  function render() {
    var root = document.getElementById("accordion-root");
    var bar = document.getElementById("global-date-bar");
    if (IS_DESKTOP()) {
      if (bar) bar.innerHTML = renderGlobalDateBar();
      root.innerHTML = FACILITY_ORDER.map(function (key) { return renderFacilityDesktop(key); }).join("");
    } else {
      if (bar) bar.innerHTML = "";
      root.innerHTML = FACILITY_ORDER.map(function (key) { return renderFacilityMobile(key); }).join("");
    }
  }

  function attachEvents() {
    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-action]");
      if (!btn || btn.disabled) return;
      var action = btn.dataset.action;

      if (action === "global-prev") {
        windowStart = Math.max(0, windowStart - 1);
        render();
      } else if (action === "global-next") {
        windowStart = Math.min(Math.max(0, ALL_DATES.length - WINDOW_SIZE), windowStart + 1);
        render();
      } else if (action === "global-date") {
        globalActiveDate = btn.dataset.date;
        render();
      } else if (action === "toggle") {
        if (IS_DESKTOP()) return;
        var key1 = btn.dataset.key;
        state[key1].expanded = !state[key1].expanded;
        render();
      } else if (action === "prev") {
        var key2 = btn.dataset.key;
        state[key2].dateIndex = Math.max(0, state[key2].dateIndex - 1);
        render();
      } else if (action === "next") {
        var key3 = btn.dataset.key;
        var max = (MENU_DATA[key3].days || []).length - 1;
        state[key3].dateIndex = Math.min(max, state[key3].dateIndex + 1);
        render();
      }
    });
  }

  var lastIsDesktop = null;
  function checkBreakpointChange() {
    var nowDesktop = IS_DESKTOP();
    if (nowDesktop !== lastIsDesktop) {
      lastIsDesktop = nowDesktop;
      render();
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    initState();
    lastIsDesktop = IS_DESKTOP();
    render();
    attachEvents();
  });
  window.addEventListener("resize", checkBreakpointChange);

  // ---- PWA 홈 화면 추가 / 앱 다운로드 배너 (실제 동작) ----
  document.addEventListener("DOMContentLoaded", function () {
    var banner = document.getElementById("installBanner");
    var msg = document.getElementById("installMsg");
    var btn = document.getElementById("installBtn");
    var dismissBtn = document.getElementById("installDismiss");
    var deferredPrompt = null;
    var DISMISS_KEY = "gbsa_menu_install_dismissed";

    function showBanner(text) {
      msg.textContent = text;
      banner.classList.remove("hidden");
      banner.classList.add("flex");
    }
    function hideBanner() {
      banner.classList.add("hidden");
      banner.classList.remove("flex");
    }

    if (localStorage.getItem(DISMISS_KEY)) {
      hideBanner();
    } else {
      var isIOS = /iphone|ipad|ipod/.test(window.navigator.userAgent.toLowerCase());
      var isStandalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;

      if (!isStandalone) {
        if (isIOS) {
          showBanner("앱으로 다운 받아 더 빠르게 확인하세요. 공유 버튼 → \\"홈 화면에 추가\\"를 눌러주세요.");
        } else {
          window.addEventListener("beforeinstallprompt", function (e) {
            e.preventDefault();
            deferredPrompt = e;
            showBanner("앱으로 다운 받아 더 빠르게 확인하세요.");
            btn.style.display = "inline-block";
          });
        }
      }
    }

    if (btn) {
      btn.addEventListener("click", function () {
        if (deferredPrompt) {
          deferredPrompt.prompt();
          deferredPrompt.userChoice.finally(hideBanner);
        }
      });
    }
    if (dismissBtn) {
      dismissBtn.addEventListener("click", function () {
        hideBanner();
        try { localStorage.setItem(DISMISS_KEY, "1"); } catch (e) {}
      });
    }
  });
})();
</script>
<script>
  // 서비스 워커 등록 — 등록되면 재방문 시 대부분의 요청이 캐시에서 처리되어
  // GitHub Pages 월간 대역폭 소모가 크게 줄어든다. 매주 배포마다 sw.js 내용이
  // 바뀌므로 브라우저가 새 버전을 감지해 캐시를 자동으로 최신 메뉴로 교체한다.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      // updateViaCache: "none" — sw.js 파일 자체를 브라우저가 HTTP 캐싱하지 않도록 강제.
      navigator.serviceWorker.register("sw.js", { updateViaCache: "none" })
        .then(function (reg) {
          // PWA를 백그라운드에서 열어뒀다가 다시 포그라운드로 돌아올 때마다
          // 서버에 새 sw.js가 있는지 강제로 확인. 브라우저 자체 스케줄(수시간~24시간)에
          // 의존하지 않게 되어, 배포 직후에도 앱을 열면 곧바로 갱신 체크가 일어난다.
          document.addEventListener("visibilitychange", function () {
            if (document.visibilityState === "visible") {
              reg.update().catch(function () {});
            }
          });
        })
        .catch(function (err) {
          console.warn("서비스 워커 등록 실패:", err);
        });

      // 새 서비스 워커가 컨트롤을 넘겨받으면(=활성화되면) 자동으로 새로고침해서
      // 사용자가 수동으로 앱을 껐다 켤 필요 없이 바로 최신 메뉴를 보게 한다.
      var refreshing = false;
      navigator.serviceWorker.addEventListener("controllerchange", function () {
        if (refreshing) return;
        refreshing = true;
        window.location.reload();
      });
    });
  }
</script>
</body>
</html>
"""

MANIFEST_JSON = {
    "name": "광교테크노밸리 구내식당 식단표",
    "short_name": "구내식당 식단표",
    "start_url": ".",
    "display": "standalone",
    "background_color": "#f7f9fb",
    "theme_color": "#00288e",
    "icons": [
        {"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ],
}


def build_html(archive: dict) -> str:
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M(KST)")
    ordered_names = [n for n in CHANNEL_ORDER if n in archive] + [n for n in archive if n not in CHANNEL_ORDER]

    menu_data = build_menu_data(archive)
    menu_data_json = json.dumps(menu_data, ensure_ascii=False)
    facility_order_json = json.dumps(ordered_names, ensure_ascii=False)

    html = PAGE_TEMPLATE
    html = html.replace("__UPDATED_AT__", now_str)
    html = html.replace("__MENU_DATA_JSON__", menu_data_json)
    html = html.replace("__FACILITY_ORDER_JSON__", facility_order_json)
    return html


def copy_static_assets():
    icons_src = ASSETS_DIR / "icons"
    icons_dst = SITE_DIR / "icons"
    if icons_src.exists():
        icons_dst.mkdir(parents=True, exist_ok=True)
        for f in icons_src.glob("*.png"):
            shutil.copy(f, icons_dst / f.name)

    css_src = ASSETS_DIR / "styles.css"
    if css_src.exists():
        SITE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(css_src, SITE_DIR / "styles.css")
    else:
        print("경고: assets/styles.css가 없습니다. scripts/build_css.sh로 먼저 빌드하세요.")

    (SITE_DIR / "manifest.json").write_text(
        json.dumps(MANIFEST_JSON, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_service_worker(version: str):
    """sw.js를 SITE_DIR에 생성한다. version이 바뀌면(=매주 배포) 브라우저가
    새 서비스 워커로 교체하면서 이전 주 캐시를 자동으로 지운다."""
    sw = SW_TEMPLATE
    sw = sw.replace("__SW_CACHE_VERSION__", version)
    sw = sw.replace("__SW_PRECACHE_URLS_JSON__", json.dumps(SW_PRECACHE_URLS, ensure_ascii=False))
    (SITE_DIR / "sw.js").write_text(sw, encoding="utf-8")


def main():
    if not ARCHIVE_PATH.exists():
        print("data/archive.json이 없습니다. merge_archive.py를 먼저 실행하세요.")
        return

    archive = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    html = build_html(archive)
    # 배포 시각을 캐시 버전으로 사용 — 매주 재배포 때마다 값이 바뀌어
    # 서비스 워커가 이전 캐시를 자동으로 교체하게 만든다.
    sw_version = datetime.now(KST).strftime("%Y%m%d%H%M%S")

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")
    copy_static_assets()
    write_service_worker(sw_version)
    print(f"사이트 생성 완료: {SITE_DIR / 'index.html'}")
    print(f"서비스 워커 캐시 버전: {sw_version}")


if __name__ == "__main__":
    main()
