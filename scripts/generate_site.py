"""
[4단계] 웹페이지 생성 스크립트
menu_final.json을 읽어서 3개 건물의 이번주 식단표를 한 페이지에 보여주는
정적 HTML(index.html)을 생성한다. GitHub Pages로 배포하는 것을 전제로 한다.
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "output" / "data"
SITE_DIR = Path(__file__).parent.parent / "output" / "site"

KST = timezone(timedelta(hours=9))


def render_menu_groups(groups):
    if not groups:
        return "<p class='empty'>메뉴 정보 없음</p>"
    parts = []
    for g in groups:
        name = g.get("group_name", "")
        items = g.get("items", [])
        items_html = "".join(f"<li>{i}</li>" for i in items)
        parts.append(f"""
        <div class="menu-group">
          {f'<div class="group-name">{name}</div>' if name and name != '메뉴' else ''}
          <ul class="items">{items_html}</ul>
        </div>
        """)
    return "".join(parts)


def render_day_card(day):
    label = day.get("day_label", "")
    groups_html = render_menu_groups(day.get("menu_groups", []))
    return f"""
    <div class="day-card">
      <div class="day-label">{label}</div>
      {groups_html}
    </div>
    """


def render_channel_section(entry):
    label = entry.get("label", entry.get("name", ""))
    post_url = entry.get("post_url", "#")
    status = entry.get("status")

    if status != "success":
        reason = {
            "skipped_no_image": "최신 게시글에서 이미지를 찾지 못했습니다.",
            "error": f"처리 중 오류가 발생했습니다: {entry.get('error', '')}",
        }.get(status, "정보를 불러오지 못했습니다.")
        return f"""
        <section class="channel">
          <h2>{label}</h2>
          <p class="error-msg">⚠️ {reason}</p>
          <a class="source-link" href="{post_url}" target="_blank">카카오톡 채널에서 직접 확인 →</a>
        </section>
        """

    menu = entry.get("menu", {})
    period_label = menu.get("period_label", "")
    notice = menu.get("notice", "")
    days = menu.get("days", [])
    days_html = "".join(render_day_card(d) for d in days)

    return f"""
    <section class="channel">
      <h2>{label}</h2>
      <div class="period-label">{period_label}</div>
      {f'<div class="notice">{notice}</div>' if notice else ''}
      <div class="days-row">
        {days_html}
      </div>
      <a class="source-link" href="{post_url}" target="_blank">원본 게시글 보기 →</a>
    </section>
    """


def build_html(menu_outputs):
    now = datetime.now(KST).strftime("%Y년 %m월 %d일 %H:%M (KST)")
    sections = "".join(render_channel_section(e) for e in menu_outputs)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>광교테크노밸리 구내식당 이번주 식단표</title>
<style>
  :root {{
    --gbsa-blue: #1C4692;
    --gbsa-sky: #00A0DC;
    --bg: #f5f7fa;
    --card-bg: #ffffff;
    --text: #1a1a1a;
    --muted: #6b7280;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Pretendard", "Noto Sans KR", -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding-bottom: 40px;
  }}
  header {{
    background: linear-gradient(135deg, var(--gbsa-blue), var(--gbsa-sky));
    color: white;
    padding: 32px 20px 24px;
    text-align: center;
  }}
  header h1 {{
    margin: 0 0 6px;
    font-size: 22px;
  }}
  header .updated {{
    font-size: 13px;
    opacity: 0.85;
  }}
  .channel {{
    background: var(--card-bg);
    margin: 20px 16px;
    padding: 20px;
    border-radius: 16px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.06);
  }}
  .channel h2 {{
    margin: 0 0 4px;
    font-size: 18px;
    color: var(--gbsa-blue);
    border-left: 5px solid var(--gbsa-sky);
    padding-left: 10px;
  }}
  .period-label {{
    font-size: 14px;
    color: var(--muted);
    margin: 8px 0 4px 15px;
  }}
  .notice {{
    font-size: 12.5px;
    color: var(--muted);
    background: #f0f4fa;
    padding: 8px 12px;
    border-radius: 8px;
    margin: 8px 0 14px;
    white-space: pre-line;
  }}
  .days-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 10px;
    margin-top: 10px;
  }}
  .day-card {{
    background: #fafbfd;
    border: 1px solid #e5e9f0;
    border-radius: 10px;
    padding: 10px;
  }}
  .day-label {{
    font-weight: 700;
    font-size: 13.5px;
    color: var(--gbsa-blue);
    margin-bottom: 6px;
  }}
  .menu-group {{
    margin-bottom: 6px;
  }}
  .group-name {{
    font-size: 12.5px;
    font-weight: 600;
    color: #374151;
    margin-bottom: 2px;
  }}
  ul.items {{
    margin: 0;
    padding-left: 16px;
    font-size: 12.5px;
    line-height: 1.5;
  }}
  .empty {{
    font-size: 12.5px;
    color: var(--muted);
  }}
  .error-msg {{
    color: #b91c1c;
    font-size: 13.5px;
  }}
  .source-link {{
    display: inline-block;
    margin-top: 12px;
    font-size: 12.5px;
    color: var(--gbsa-sky);
    text-decoration: none;
  }}
  .source-link:hover {{
    text-decoration: underline;
  }}
  footer {{
    text-align: center;
    font-size: 11.5px;
    color: var(--muted);
    margin-top: 20px;
  }}
</style>
</head>
<body>
<header>
  <h1>🍱 광교테크노밸리 구내식당 이번주 식단표</h1>
  <div class="updated">마지막 업데이트: {now}</div>
</header>

{sections}

<footer>
  본 페이지는 각 구내식당 카카오톡 채널의 최신 게시글을 자동으로 읽어 생성됩니다.<br>
  실제 운영 사정에 따라 메뉴가 변경될 수 있으니, 정확한 정보는 원본 게시글을 확인해주세요.
</footer>
</body>
</html>
"""


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
