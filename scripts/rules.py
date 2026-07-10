"""
채널별 공통 규칙 모음.
scrape_menu.py가 만든 raw OCR 결과를 merge_archive.py가 정규화할 때 사용한다.
"""

import re
from datetime import datetime, timedelta, timezone

DINNER_KEYWORDS = ["석식", "저녁"]

DATE_PATTERN = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
MMDD_PATTERN = re.compile(r"^\d{2}-\d{2}$")

KST = timezone(timedelta(hours=9))


def extract_month_day(day: dict):
    """day 딕셔너리에서 (month, dom) 튜플을 뽑아낸다. 실패 시 None."""
    raw_date = (day.get("date") or "").strip()
    if MMDD_PATTERN.match(raw_date):
        m, d = raw_date.split("-")
        return int(m), int(d)

    label = day.get("day_label", "")
    m = DATE_PATTERN.search(label)
    if m:
        return int(m.group(1)), int(m.group(2))

    return None


def current_week_weekdays(now: datetime = None):
    """오늘(KST) 기준 이번 주 월~금 날짜(date 객체) 리스트를 반환한다.

    최신 게시글이 공지/안내 이미지라 여러 후보를 순회해야 할 때, 각 후보의
    OCR 결과가 '이번 주' 식단표가 맞는지 검증하는 기준으로 사용한다.
    """
    now = now or datetime.now(KST)
    monday = now.date() - timedelta(days=now.weekday())
    return [monday + timedelta(days=i) for i in range(5)]


def menu_matches_current_week(menu_json: dict, now: datetime = None) -> bool:
    """OCR 결과(menu_json)의 days 중 하나라도 이번 주 날짜(월~금)와
    (월, 일)이 일치하면 True. days가 비어있거나 날짜를 하나도 못 뽑으면 False.

    주의: 연도 정보 없이 (월, 일)만 비교하므로, build_day_entry가 run_year를
    기준으로 실제 날짜를 확정하는 방식과 동일한 전제(연말/연초 경계는 드묾)를
    따른다.
    """
    days = menu_json.get("days") or []
    if not days:
        return False

    week_md = {(d.month, d.day) for d in current_week_weekdays(now)}
    for day in days:
        md = extract_month_day(day)
        if md is not None and md in week_md:
            return True
    return False

# 채널마다 표 양식이 고정되어 있어(관리자가 매주 같은 틀에 메뉴만 교체),
# 그룹명만으로는 중식/석식이 구분 안 되는 경우를 여기서 명시적으로 처리한다.
CHANNEL_DINNER_GROUP_OVERRIDE = {
    "rdb_center": {"일반식"},
}

# 채널별로 특정 그룹에서 매번 잘못 섞여 들어오는 항목을 제외 처리.
CHANNEL_GROUP_ITEM_EXCLUDE = {
    "rdb_center": {
        "음료": {"현미밥"},
    },
}

# 아코디언에 표시할 건물/구내식당 이름 고정 (OCR/스크래핑 label과 무관).
DISPLAY_LABEL_OVERRIDE = {
    "nano_gaeram": "한국나노기술원 구내식당",
}

BUILDING_ICON = {
    "gbsa": "🏢",
    "rdb_center": "🏬",
    "nano_gaeram": "🔬",
}


def classify_meal_type(channel_name, group_name):
    name = (group_name or "").strip()
    override_set = CHANNEL_DINNER_GROUP_OVERRIDE.get(channel_name, set())
    if name in override_set:
        return "dinner"
    if any(k in name for k in DINNER_KEYWORDS):
        return "dinner"
    return "lunch"


def filter_excluded_items(channel_name, group_name, items):
    exclude_set = CHANNEL_GROUP_ITEM_EXCLUDE.get(channel_name, {}).get(group_name, set())
    if not exclude_set:
        return items
    return [it for it in items if it not in exclude_set]


def display_label(channel_name, fallback_label):
    return DISPLAY_LABEL_OVERRIDE.get(channel_name, fallback_label)
