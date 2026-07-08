"""
[4단계] 웹페이지 생성 스크립트 (v2 — SaaS 스타일 + 아코디언 + 날짜 네비게이션)

요구사항 반영:
- SaaS 스타일 디자인 (카드형, 여백감, 부드러운 그림자)
- 건물별(구내식당별) 아코디언, 기본값은 닫힌 상태
- 아코디언을 열면 "오늘(PC 날짜) 기준" 하루치 메뉴만 표시
- '<' '>' 버튼으로 날짜 이동 (좌우 하루씩)
- PC 날짜가 이번 주 식단 범위를 벗어나면(더 미래) 가장 최근 제공 가능한 날짜로 표시
- 중식/석식을 별도 박스로 분리
- 아코디언 헤더에는 건물명(구내식당명)만 표기, 부가 설명 없음

날짜 판별은 "PC(브라우저) 날짜" 기준이어야 하므로, 서버(Python)에서는 각 날짜를
MM-DD 형식으로 정규화해서 데이터만 만들어 넣고, 실제 "오늘이 며칠인지" 비교/이동
로직은 전부 클라이언트 JS에서 처리한다.
"""

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "output" / "data"
SITE_DIR = Path(__file__).parent.parent / "output" / "site"

KST = timezone(timedelta(hours=9))

WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

DATE_PATTERN = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
MMDD_PATTERN = re.compile(r"^\d{2}-\d{2}$")

DINNER_KEYWORDS = ["석식", "저녁"]


def extract_date_iso(day, fallback_year):
    """day 딕셔너리에서 MM-DD 형식의 날짜 문자열을 뽑아낸다.
    1) OCR이 'date' 필드를 MM-DD로 정확히 줬으면 그대로 사용
    2) 아니면 day_label 텍스트에서 '7월 6일' 같은 패턴을 정규식으로 추출
    """
    raw_date = (day.get("date") or "").strip()
    if MMDD_PATTERN.match(raw_date):
        return raw_date

    label = day.get("day_label", "")
    m = DATE_PATTERN.search(label)
    if m:
        month, dom = int(m.group(1)), int(m.group(2))
        return f"{month:02d}-{dom:02d}"

    return None


def classify_meal_type(group_name):
    name = group_name or ""
    if any(k in name for k in DINNER_KEYWORDS):
        return "dinner"
    return "lunch"


def build_channel_data(entry, fallback_year):
    name = entry.get("name")
    label = entry.get("label", name)
    status = entry.get("status")

    channel = {
        "name": name,
        "label": label,
        "status": status,
        "post_url": entry.get("post_url"),
        "notice": "",
        "days": [],
    }

    if status != "success":
        channel["error_message"] = {
            "skipped_no_image": "최신 게시글에서 이미지를 찾지 못했습니다.",
            "error": f"처리 중 오류가 발생했습니다: {entry.get('error', '')}",
        }.get(status, "정보를 불러오지 못했습니다.")
        return channel

    menu = entry.get("menu", {})
    channel["notice"] = menu.get("notice", "") or ""

    days_out = []
    for day in menu.get("days", []):
        date_iso = extract_date_iso(day, fallback_year)
        if date_iso is None:
            weekday_label = day.get("day_label", "")
        else:
            month, dom = map(int, date_iso.split("-"))
            try:
                wd = date(fallback_year, month, dom).weekday()
                weekday_label = f"{WEEKDAY_KR[wd]} · {month}월 {dom}일"
            except ValueError:
                weekday_label = day.get("day_label", "")

        lunch_groups = []
        dinner_groups = []
        for g in day.get("menu_groups", []):
            bucket = classify_meal_type(g.get("group_name", ""))
            target = dinner_groups if bucket == "dinner" else lunch_groups
            target.append({
                "group_name": g.get("group_name", ""),
                "items": g.get("items", []),
            })

        days_out.append({
            "date_iso": date_iso,
            "label": weekday_label,
            "lunch_groups": lunch_groups,
            "dinner_groups": dinner_groups,
        })

    days_out.sort(key=lambda d: d["date_iso"] or "99-99")
    channel["days"] = days_out
    return channel


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
            gname = g["group_name"]
            items = g["items"]
            if not items:
                continue
            items_html = "".join(f"<li>{i}</li>" for i in items)
            show_gname = gname and gname not in ("메뉴",)
            gname_html = f"<div class='group-name'>{gname}</div>" if show_gname else ""
            parts.append(
                f'<div class="menu-group">{gname_html}<ul class="items">{items_html}</ul></div>'
            )
        body = "".join(parts) if parts else '<p class="empty-meal">정보 없음</p>'

    return f"""
    <div class="meal-box">
      <div class="meal-box-title">{icon} {title}</div>
      <div class="meal-box-body">{body}</div>
    </div>
    """


def render_day_panel(day, index):
    lunch_html = render_meal_box("중식", "🍚", day["lunch_groups"])
    dinner_html = render_meal_box("석식", "🌙", day["dinner_groups"])
    return f"""
    <div class="day-panel" data-index="{index}" data-date="{day['date_iso'] or ''}">
      <div class="day-panel-heading">{day['label']}</div>
      <div class="meal-grid">
        {lunch_html}
        {dinner_html}
      </div>
    </div>
    """


def render_channel_accordion(channel, index):
    icon = BUILDING_ICON.get(channel["name"], "🍽️")
    label = channel["label"]

    if channel["status"] != "success":
        post_link_html = (
            f'<a class="source-link" href="{channel["post_url"]}" target="_blank">카카오톡 채널에서 직접 확인 →</a>'
            if channel.get("post_url") else ""
        )
        return f"""
    <div class="accordion-item">
      <button type="button" class="accordion-header" disabled>
        <span class="accordion-title">{icon} {label}</span>
        <span class="chevron">›</span>
      </button>
      <div class="accordion-panel-wrap">
        <div class="accordion-panel error-panel">
          <p class="error-msg">⚠️ {channel.get('error_message', '정보를 불러오지 못했습니다.')}</p>
          {post_link_html}
        </div>
      </div>
    </div>
    """

    days = channel["days"]
    dates_json = json.dumps([d["date_iso"] for d in days], ensure_ascii=False)
    days_html = "".join(render_day_panel(days[i], i) for i in range(len(days)))
    notice = channel.get("notice", "")
    notice_html = f'<div class="channel-notice">{notice}</div>' if notice else ""
    source_html = (
        f'<a class="source-link" href="{channel["post_url"]}" target="_blank">원본 게시글 보기 →</a>'
        if channel.get("post_url") else ""
    )

    return f"""
    <div class="accordion-item" data-channel="{channel['name']}" data-dates='{dates_json}'>
      <button type="button" class="accordion-header">
        <span class="accordion-title">{icon} {label}</span>
        <span class="chevron">›</span>
      </button>
      <div class="accordion-panel-wrap">
        <div class="accordion-panel">
          {notice_html}
          <div class="date-nav">
            <button type="button" class="nav-btn prev-btn" aria-label="이전 날짜">‹</button>
            <div class="date-viewport">
              {days_html}
            </div>
            <button type="button" class="nav-btn next-btn" aria-label="다음 날짜">›</button>
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
  .top-bar {
    text-align: center;
    margin-bottom: 24px;
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
  .accordion {
    display: flex;
    flex-direction: column;
    gap: 12px;
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
  .accordion-panel {
    padding: 0 20px 20px;
  }
  .error-panel {
    padding: 0 20px 20px;
  }
  .error-msg {
    color: #c0392b;
    font-size: 13.5px;
    margin: 0 0 8px;
  }
  .channel-notice {
    font-size: 12px;
    line-height: 1.6;
    color: var(--muted);
    background: #f2f4f9;
    border-radius: 10px;
    padding: 10px 12px;
    margin-bottom: 14px;
    white-space: pre-line;
  }
  .date-nav {
    display: flex;
    align-items: stretch;
    gap: 8px;
  }
  .nav-btn {
    flex: 0 0 auto;
    width: 36px;
    border: 1px solid var(--border);
    background: #fafbfd;
    border-radius: 10px;
    font-size: 18px;
    color: var(--brand);
    cursor: pointer;
    transition: background 0.15s ease;
  }
  .nav-btn:hover {
    background: #eef2fb;
  }
  .nav-btn:disabled {
    opacity: 0.3;
    cursor: default;
  }
  .date-viewport {
    flex: 1;
    min-width: 0;
    position: relative;
  }
  .day-panel {
    display: none;
  }
  .day-panel.active {
    display: block;
  }
  .day-panel-heading {
    text-align: center;
    font-size: 13.5px;
    font-weight: 700;
    color: var(--brand);
    background: #eef2fb;
    border-radius: 10px;
    padding: 8px 0;
    margin-bottom: 12px;
  }
  .meal-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  @media (max-width: 380px) {
    .meal-grid {
      grid-template-columns: 1fr;
    }
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
    color: var(--text);
    margin-bottom: 8px;
  }
  .menu-group {
    margin-bottom: 8px;
  }
  .menu-group:last-child {
    margin-bottom: 0;
  }
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
    color: var(--text);
  }
  .empty-meal {
    font-size: 12px;
    color: var(--muted);
    margin: 0;
  }
  .source-link {
    display: inline-block;
    margin-top: 14px;
    font-size: 12px;
    color: var(--brand-light);
    text-decoration: none;
  }
  .source-link:hover {
    text-decoration: underline;
  }
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

  function todayMMDD() {
    var d = new Date();
    return pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function getInitialIndex(dates) {
    var t = todayMMDD();
    var idx = dates.indexOf(t);
    if (idx !== -1) return idx;
    if (dates.length === 0) return -1;
    if (t > dates[dates.length - 1]) return dates.length - 1;
    return 0;
  }

  function setActiveDay(item, index) {
    var panels = item.querySelectorAll(".day-panel");
    panels.forEach(function (p) {
      p.classList.toggle("active", parseInt(p.dataset.index, 10) === index);
    });
    item.dataset.currentIndex = index;

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
      wrap.style.maxHeight = item.classList.contains("open")
        ? panel.scrollHeight + "px"
        : "0px";
    }
  }

  document.querySelectorAll(".accordion-item").forEach(function (item) {
    var dates = JSON.parse(item.dataset.dates || "[]");

    if (dates.length > 0) {
      var initial = getInitialIndex(dates);
      setActiveDay(item, initial);
    }

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
        if (cur > 0) {
          setActiveDay(item, cur - 1);
          recalcHeight(item);
        }
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        var cur = parseInt(item.dataset.currentIndex || "0", 10);
        if (cur < dates.length - 1) {
          setActiveDay(item, cur + 1);
          recalcHeight(item);
        }
      });
    }
  });

  window.addEventListener("resize", function () {
    document.querySelectorAll(".accordion-item.open").forEach(recalcHeight);
  });
})();
</script>
</body>
</html>
"""


def build_html(menu_outputs):
    now_kst = datetime.now(KST)
    now_str = now_kst.strftime("%Y년 %m월 %d일 %H:%M (KST)")
    fallback_year = now_kst.year

    channels = [build_channel_data(e, fallback_year) for e in menu_outputs]
    accordion_html = "".join(
        render_channel_accordion(c, i) for i, c in enumerate(channels)
    )

    html = PAGE_TEMPLATE
    html = html.replace("__UPDATED_AT__", now_str)
    html = html.replace("__ACCORDION_HTML__", accordion_html)
    return html


def main():
    menu_final_path = DATA_DIR / "menu_final.json"
    if not menu_final_path.exists():
        print("menu_final.json이 없습니다. ocr_menu.py를 먼저 실행하세요.")
        return

    menu_outputs = json.loads(menu_final_path.read_text(encoding="utf-8"))
    html = build_html(menu_outputs)

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"사이트 생성 완료: {SITE_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
