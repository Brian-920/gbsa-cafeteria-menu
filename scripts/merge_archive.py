"""
[5단계] 아카이브 병합 스크립트

이번 실행에서 OCR로 얻은 이번 주 메뉴(output/data/menu_final.json)를
누적 아카이브(data/archive.json, 저장소에 커밋되어 계속 쌓임)에 병합한다.

병합 시:
- 채널별 예외 규칙(rules.py) 적용 — 중식/석식 분류, 특정 항목 제외, 표시 이름 고정
- 대한민국 공휴일 여부 판정(holiday_utils.py) — 공휴일이면 메뉴 대신 공휴일명을 저장

data/archive.json은 output/ 밖에 있어 .gitignore에 안 걸리고, 워크플로우가
매 실행 후 이 파일을 저장소에 커밋해서 다음 실행에서도 이어서 누적된다.
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import rules
import holiday_utils

OUTPUT_DATA_DIR = Path(__file__).parent.parent / "output" / "data"
ARCHIVE_PATH = Path(__file__).parent.parent / "data" / "archive.json"

KST = timezone(timedelta(hours=9))
WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]


def load_archive() -> dict:
    if ARCHIVE_PATH.exists():
        try:
            return json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[merge_archive] 기존 아카이브 로드 실패({e}), 새로 시작합니다.")
            return {}
    return {}


def save_archive(archive: dict):
    ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE_PATH.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")


def build_day_entry(day: dict, channel_name: str, run_year: int, holidays: dict):
    md = rules.extract_month_day(day)
    if md is None:
        return None
    month, dom = md

    try:
        d = date(run_year, month, dom)
    except ValueError:
        return None
    date_iso = d.isoformat()

    lunch_groups, dinner_groups = [], []
    for g in day.get("menu_groups", []):
        group_name = g.get("group_name", "")
        bucket = rules.classify_meal_type(channel_name, group_name)
        items = rules.filter_excluded_items(channel_name, group_name, g.get("items", []))
        target = dinner_groups if bucket == "dinner" else lunch_groups
        target.append({"group_name": group_name, "items": items})

    holiday_name = holidays.get(date_iso)

    return {
        "date": date_iso,
        "weekday_label": WEEKDAY_KR[d.weekday()],
        "is_holiday": holiday_name is not None,
        "holiday_name": holiday_name,
        "lunch_groups": lunch_groups,
        "dinner_groups": dinner_groups,
    }


def fill_missing_week_with_placeholder(channel_archive: dict, holidays: dict):
    """이번 주 식단표를 (5개 후보를 다 시도해도) 찾지 못한 채널에 대해,
    이번 주(월~금) 중 아직 아카이브에 없는 날짜를 '정보 없음' 상태의
    빈 데이터로 채워 넣는다.

    이렇게 해두지 않으면 프론트엔드가 오늘 날짜에 해당하는 데이터를 못 찾고
    엉뚱하게 예전(가장 오래된) 날짜를 기본값으로 보여줄 수 있다.
    """
    added = 0
    for d in rules.current_week_weekdays():
        date_iso = d.isoformat()
        if date_iso in channel_archive["days"]:
            continue  # 이미 과거 실행에서 채워진 날짜는 덮어쓰지 않음

        holiday_name = holidays.get(date_iso)
        channel_archive["days"][date_iso] = {
            "date": date_iso,
            "weekday_label": WEEKDAY_KR[d.weekday()],
            "is_holiday": holiday_name is not None,
            "holiday_name": holiday_name,
            "lunch_groups": [],
            "dinner_groups": [],
            "no_data": True,
        }
        added += 1
    return added


def main():
    menu_final_path = OUTPUT_DATA_DIR / "menu_final.json"
    if not menu_final_path.exists():
        print("menu_final.json이 없습니다. ocr_menu.py를 먼저 실행하세요.")
        return

    menu_outputs = json.loads(menu_final_path.read_text(encoding="utf-8"))

    now_kst = datetime.now(KST)
    run_year = now_kst.year
    # 연말/연초 경계(12월에 스크래핑했는데 다음 해로 넘어가는 주간)를 대비해
    # 올해와 내년 공휴일을 함께 조회해둔다.
    holidays = holiday_utils.get_holidays([run_year, run_year + 1])

    archive = load_archive()

    for entry in menu_outputs:
        name = entry.get("name")
        label = rules.display_label(name, entry.get("label", name))

        if name not in archive:
            archive[name] = {"label": label, "post_url": entry.get("post_url"), "days": {}}
        else:
            archive[name]["label"] = label
            archive[name]["post_url"] = entry.get("post_url") or archive[name].get("post_url")

        if entry.get("status") != "success":
            filled = fill_missing_week_with_placeholder(archive[name], holidays)
            print(
                f"[merge_archive] {name}: 이번 실행에서 식단표를 찾지 못했습니다"
                f"({entry.get('status')}). 이번 주 {filled}일치를 '정보 없음'으로 채웠습니다."
            )
            continue

        menu = entry.get("menu", {})
        added = 0
        for day in menu.get("days", []):
            day_entry = build_day_entry(day, name, run_year, holidays)
            if day_entry is None:
                continue
            archive[name]["days"][day_entry["date"]] = day_entry
            added += 1
        print(f"[merge_archive] {name}: {added}일치 병합 완료")

    save_archive(archive)
    print(f"\n아카이브 저장 완료: {ARCHIVE_PATH}")
    for name, ch in archive.items():
        print(f"  - {name}: 누적 {len(ch['days'])}일치")


if __name__ == "__main__":
    main()
