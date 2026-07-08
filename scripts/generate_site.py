"""
[6단계] 웹페이지 생성 스크립트 (v3 — 아카이브 기반 렌더링 + PWA + 공휴일 표시)

이 스크립트는 이제 순수 "렌더러"다. 분류/예외처리/공휴일 판정은 모두
merge_archive.py에서 끝내고, data/archive.json에 정리된 결과만 그림으로 그린다.

추가된 것:
- data/archive.json 전체 날짜를 대상으로 ‹ › 네비게이션 (이번 주만이 아님)
- is_holiday인 날은 메뉴 대신 공휴일명 배너 표시
- PWA 설치 배너 (안드로이드: 실제 설치 버튼 / iOS: 안내 팝업)
- assets/icons를 output/site로 복사, manifest.json 생성
"""

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

ARCHIVE_PATH = Path(__file__).parent.parent / "data" / "archive.json"
SITE_DIR = Path(__file__).parent.parent / "output" / "site"
ASSETS_DIR = Path(__file__).parent.parent / "assets"

KST = timezone(timedelta(hours=9))

BUILDING_ICON = {
    "gbsa": "🏢",
    "rdb_center": "🏬",
    "nano_gaeram": "🔬",
}


def render_meal_box(title, icon, groups):
    if not groups:
        body = '<p class="empty-meal">정보 없음</p>'
    else:
        parts = []
        for g in groups:
            gname = g.get("group_name", "")
            items = g.get("items", [])
            if not items:
                continue
            items_html = "".join(f"<li>{i}</li>" for i in items)
            show_gname = gname and gname not in ("메뉴",)
            gname_html = f"<div class='group-name'>{gname}</div>" if show_gname else ""
            parts.append(f'<div class="menu-group">{gname_html}<ul class="items">{items_html}</ul></div>')
        body = "".join(parts) if parts else '<p class="empty-meal">정보 없음</p>'

    return f"""
    <div class="meal-box">
      <div class="meal-box-title">{icon} {title}</div>
      <div class="meal-box-body">{body}</div>
    </div>
    """


def render_day_panel(day, index):
    label = f"{day['weekday_label']} · {int(day['date'][5:7])}월 {int(day['date'][8:10])}일"
    label_attr = label.replace('"', "&quot;")

    if day.get("is_holiday"):
        holiday_name = day.get("holiday_name") or "공휴일"
        content = f"""
        <div class="holiday-banner">
          🎉 <strong>{holiday_name}</strong>
          <div class="holiday-sub">공휴일로 구내식당 미운영일 수 있습니다</div>
        </div>
        """
    else:
        lunch_html = render_meal_box("중식", "🍚", day.get("lunch_groups", []))
        dinner_html = render_meal_box("석식", "🌙", day.get("dinner_groups", []))
        content = f'<div class="meal-grid">{lunch_html}{dinner_html}</div>'

    return f"""
    <div class="day-panel" data-index="{index}" data-date="{day['date']}" data-label="{label_attr}">
      {content}
    </div>
    """


def render_channel_accordion(channel_name, channel, index):
    icon = BUILDING_ICON.get(channel_name, "🍽️")
    label = channel.get("label", channel_name)
    days = sorted(channel.get("days", {}).values(), key=lambda d: d["date"])

    if not days:
        return f"""
    <div class="accordion-item">
      <button type="button" class="accordion-header" disabled>
        <span class="accordion-title">{icon} {label}</span>
        <span class="chevron">›</span>
      </button>
      <div class="accordion-panel-wrap">
        <div class="accordion-panel error-panel">
          <p class="error-msg">⚠️ 아직 수집된 메뉴 정보가 없습니다.</p>
        </div>
      </div>
    </div>
    """

    dates_json = json.dumps([d["date"] for d in days], ensure_ascii=False)
    days_html = "".join(render_day_panel(days[i], i) for i in range(len(days)))
    post_url = channel.get("post_url")
    source_html = (
        f'<a class="source-link" href="{post_url}" target="_blank">원본 게시글 보기 →</a>'
        if post_url else ""
    )

    return f"""
    <div class="accordion-item" data-channel="{channel_name}" data-dates='{dates_json}'>
      <button type="button" class="accordion-header">
        <span class="accordion-title">{icon} {label}</span>
        <span class="chevron">›</span>
      </button>
      <div class="accordion-panel-wrap">
        <div class="accordion-panel">
          <div class="date-pill-row">
            <button type="button" class="nav-btn prev-btn" aria-label="이전 날짜">‹</button>
            <div class="date-pill-label"></div>
            <button type="button" class="nav-btn next-btn" aria-label="다음 날짜">›</button>
          </div>
          <div class="date-viewport">
            {days_html}
          </div>
          {source_html}
        </div>
      </div>
    </div>
    """


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>광교테크노밸리 구내식당 식단표</title>
<link rel="manifest" href="manifest.json">
<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">
<link rel="icon" href="icons/icon-192.png">
<meta name="theme-color" content="#1C4692">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="구내식당 식단표">
<style>
  :root {
    --brand: #1C4692;
    --brand-light: #00A0DC;
    --bg: #f6f7fb;
    --card: #ffffff;
    --border: #e8eaf0;
    --text: #16181d;
    --muted: #8a8f9c;
    --radius-lg: 20px;
    --radius-md: 14px;
    --shadow: 0 1px 2px rgba(16,24,40,0.04), 0 4px 16px rgba(16,24,40,0.06);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "Pretendard", "Inter", "Noto Sans KR", -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg);
    color: var(--text);
    -webkit-font-smoothing: antialiased;
  }
  .page {
    max-width: 560px;
    margin: 0 auto;
    padding: 24px 16px 60px;
  }
  @media (min-width: 900px) {
    .page { max-width: 1100px; }
  }
  .top-bar {
    text-align: center;
    margin-bottom: 20px;
  }
  .top-bar h1 {
    font-size: 19px;
    font-weight: 700;
    margin: 0 0 6px;
    letter-spacing: -0.01em;
  }
  .top-bar .updated {
    font-size: 12.5px;
    color: var(--muted);
  }
  .install-banner {
    display: none;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow);
    padding: 12px 14px;
    margin-bottom: 16px;
    font-size: 12.5px;
  }
  .install-banner.show { display: flex; }
  .install-banner .msg { color: var(--text); line-height: 1.5; }
  .install-banner button {
    flex: 0 0 auto;
    background: var(--brand);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
  }
  .install-banner .dismiss {
    background: none;
    color: var(--muted);
    padding: 8px 6px;
  }
  .accordion {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  @media (min-width: 900px) {
    .accordion {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      align-items: start;
      gap: 16px;
    }
  }
  .accordion-item {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow);
    overflow: hidden;
  }
  .accordion-header {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: none;
    border: none;
    padding: 18px 20px;
    font-size: 15.5px;
    font-weight: 600;
    color: var(--text);
    cursor: pointer;
    text-align: left;
  }
  .accordion-header:disabled {
    cursor: default;
    color: var(--muted);
  }
  .chevron {
    font-size: 20px;
    color: var(--muted);
    transform: rotate(90deg);
    transition: transform 0.25s ease;
  }
  .accordion-item.open .chevron {
    transform: rotate(-90deg);
  }
  .accordion-panel-wrap {
    max-height: 0;
    overflow: hidden;
    transition: max-height 0.3s ease;
  }
  .accordion-panel, .error-panel {
    padding: 0 20px 20px;
  }
  .error-msg {
    color: #c0392b;
    font-size: 13.5px;
    margin: 0 0 8px;
  }
  .date-pill-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin-bottom: 12px;
  }
  .nav-btn {
    flex: 0 0 auto;
    width: 32px;
    height: 32px;
    border: 1px solid var(--border);
    background: #fafbfd;
    border-radius: 10px;
    font-size: 17px;
    line-height: 1;
    color: var(--brand);
    cursor: pointer;
    transition: background 0.15s ease;
  }
  .nav-btn:hover { background: #eef2fb; }
  .nav-btn:disabled { opacity: 0.3; cursor: default; }
  .date-pill-label {
    flex: 1 1 auto;
    max-width: 220px;
    text-align: center;
    font-size: 13.5px;
    font-weight: 700;
    color: var(--brand);
    background: #eef2fb;
    border-radius: 10px;
    padding: 8px 0;
  }
  .date-viewport { position: relative; }
  .day-panel { display: none; }
  .day-panel.active { display: block; }
  .meal-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  @media (max-width: 380px) {
    .meal-grid { grid-template-columns: 1fr; }
  }
  .meal-box {
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 12px;
    background: #fcfcfd;
  }
  .meal-box-title {
    font-size: 12.5px;
    font-weight: 700;
    margin-bottom: 8px;
  }
  .menu-group { margin-bottom: 8px; }
  .menu-group:last-child { margin-bottom: 0; }
  .group-name {
    font-size: 11.5px;
    font-weight: 600;
    color: var(--brand-light);
    margin-bottom: 2px;
  }
  ul.items {
    margin: 0;
    padding-left: 14px;
    font-size: 12px;
    line-height: 1.55;
  }
  .empty-meal { font-size: 12px; color: var(--muted); margin: 0; }
  .holiday-banner {
    text-align: center;
    padding: 28px 12px;
    background: #fff7ed;
    border: 1px dashed #f3b866;
    border-radius: var(--radius-md);
    font-size: 15px;
    color: #9a5b12;
  }
  .holiday-sub {
    font-size: 12px;
    color: #b07a3a;
    margin-top: 6px;
  }
  .source-link {
    display: inline-block;
    margin-top: 14px;
    font-size: 12px;
    color: var(--brand-light);
    text-decoration: none;
  }
  .source-link:hover { text-decoration: underline; }
  footer {
    text-align: center;
    font-size: 11px;
    color: var(--muted);
    margin-top: 28px;
    line-height: 1.6;
  }
</style>
</head>
<body>
<div class="page">
  <div class="top-bar">
    <h1>🍱 광교테크노밸리 구내식당 식단표</h1>
    <div class="updated">마지막 업데이트: __UPDATED_AT__</div>
  </div>

  <div id="installBanner" class="install-banner">
    <div class="msg" id="installMsg"></div>
    <button type="button" id="installBtn" style="display:none;">홈 화면에 추가</button>
    <button type="button" class="dismiss" id="installDismiss">닫기</button>
  </div>

  <div class="accordion">
    __ACCORDION_HTML__
  </div>

  <footer>
    실제 운영 사정에 따라 메뉴가 변경될 수 있으니, 정확한 정보는 원본 게시글을 확인해주세요.
  </footer>
</div>

<script>
(function () {
  function pad(n) { return String(n).padStart(2, "0"); }

  function todayISO() {
    var d = new Date();
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function getInitialIndex(dates) {
    var t = todayISO();
    var idx = dates.indexOf(t);
    if (idx !== -1) return idx;
    if (dates.length === 0) return -1;
    if (t > dates[dates.length - 1]) return dates.length - 1;
    return 0;
  }

  function setActiveDay(item, index) {
    var panels = item.querySelectorAll(".day-panel");
    var activePanel = null;
    panels.forEach(function (p) {
      var isActive = parseInt(p.dataset.index, 10) === index;
      p.classList.toggle("active", isActive);
      if (isActive) activePanel = p;
    });
    item.dataset.currentIndex = index;

    var label = item.querySelector(".date-pill-label");
    if (label && activePanel) label.textContent = activePanel.dataset.label || "";

    var dates = JSON.parse(item.dataset.dates || "[]");
    var prevBtn = item.querySelector(".prev-btn");
    var nextBtn = item.querySelector(".next-btn");
    if (prevBtn) prevBtn.disabled = index <= 0;
    if (nextBtn) nextBtn.disabled = index >= dates.length - 1;
  }

  function recalcHeight(item) {
    var wrap = item.querySelector(".accordion-panel-wrap");
    var panel = item.querySelector(".accordion-panel, .error-panel");
    if (wrap && panel) {
      wrap.style.maxHeight = item.classList.contains("open") ? panel.scrollHeight + "px" : "0px";
    }
  }

  document.querySelectorAll(".accordion-item").forEach(function (item) {
    var dates = JSON.parse(item.dataset.dates || "[]");
    if (dates.length > 0) setActiveDay(item, getInitialIndex(dates));

    var header = item.querySelector(".accordion-header");
    if (header && !header.disabled) {
      header.addEventListener("click", function () {
        item.classList.toggle("open");
        recalcHeight(item);
      });
    }

    var prevBtn = item.querySelector(".prev-btn");
    var nextBtn = item.querySelector(".next-btn");
    if (prevBtn) {
      prevBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        var cur = parseInt(item.dataset.currentIndex || "0", 10);
        if (cur > 0) { setActiveDay(item, cur - 1); recalcHeight(item); }
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        var cur = parseInt(item.dataset.currentIndex || "0", 10);
        if (cur < dates.length - 1) { setActiveDay(item, cur + 1); recalcHeight(item); }
      });
    }
  });

  window.addEventListener("resize", function () {
    document.querySelectorAll(".accordion-item.open").forEach(recalcHeight);
  });

  // ---- PWA 홈 화면 추가 배너 ----
  var banner = document.getElementById("installBanner");
  var msg = document.getElementById("installMsg");
  var btn = document.getElementById("installBtn");
  var dismiss = document.getElementById("installDismiss");
  var deferredPrompt = null;

  var DISMISS_KEY = "gbsa_menu_install_dismissed";
  if (localStorage.getItem(DISMISS_KEY)) {
    banner.classList.remove("show");
  } else {
    var isIOS = /iphone|ipad|ipod/.test(window.navigator.userAgent.toLowerCase());
    var isInStandalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;

    if (!isInStandalone) {
      if (isIOS) {
        msg.textContent = "홈 화면에 추가하면 앱처럼 빠르게 열 수 있어요. 공유 버튼 → \\"홈 화면에 추가\\"를 눌러주세요.";
        banner.classList.add("show");
      } else {
        window.addEventListener("beforeinstallprompt", function (e) {
          e.preventDefault();
          deferredPrompt = e;
          msg.textContent = "홈 화면에 추가하면 앱처럼 빠르게 열 수 있어요.";
          btn.style.display = "inline-block";
          banner.classList.add("show");
        });
      }
    }
  }

  if (btn) {
    btn.addEventListener("click", function () {
      if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.finally(function () {
          banner.classList.remove("show");
        });
      }
    });
  }
  if (dismiss) {
    dismiss.addEventListener("click", function () {
      banner.classList.remove("show");
      try { localStorage.setItem(DISMISS_KEY, "1"); } catch (e) {}
    });
  }
})();
</script>
</body>
</html>
"""

MANIFEST_JSON = {
    "name": "광교테크노밸리 구내식당 식단표",
    "short_name": "구내식당 식단표",
    "start_url": ".",
    "display": "standalone",
    "background_color": "#f6f7fb",
    "theme_color": "#1C4692",
    "icons": [
        {"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ],
}


def build_html(archive: dict) -> str:
    now_str = datetime.now(KST).strftime("%Y년 %m월 %d일 %H:%M (KST)")
    channel_order = ["gbsa", "rdb_center", "nano_gaeram"]
    ordered_names = [n for n in channel_order if n in archive] + [n for n in archive if n not in channel_order]

    accordion_html = "".join(
        render_channel_accordion(name, archive[name], i) for i, name in enumerate(ordered_names)
    )

    html = PAGE_TEMPLATE
    html = html.replace("__UPDATED_AT__", now_str)
    html = html.replace("__ACCORDION_HTML__", accordion_html)
    return html


def copy_static_assets():
    icons_src = ASSETS_DIR / "icons"
    icons_dst = SITE_DIR / "icons"
    if icons_src.exists():
        icons_dst.mkdir(parents=True, exist_ok=True)
        for f in icons_src.glob("*.png"):
            shutil.copy(f, icons_dst / f.name)

    (SITE_DIR / "manifest.json").write_text(
        json.dumps(MANIFEST_JSON, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main():
    if not ARCHIVE_PATH.exists():
        print("data/archive.json이 없습니다. merge_archive.py를 먼저 실행하세요.")
        return

    archive = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    html = build_html(archive)

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")
    copy_static_assets()
    print(f"사이트 생성 완료: {SITE_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
