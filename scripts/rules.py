"""
채널별 공통 규칙 모음.
scrape_menu.py가 만든 raw OCR 결과를 merge_archive.py가 정규화할 때 사용한다.
"""

import re

DINNER_KEYWORDS = ["석식", "저녁"]

DATE_PATTERN = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
MMDD_PATTERN = re.compile(r"^\d{2}-\d{2}$")


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
