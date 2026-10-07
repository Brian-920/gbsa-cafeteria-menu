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

# ---------------------------------------------------------------------------
# 그룹명 정리 규칙
# ---------------------------------------------------------------------------
# 표의 세로 병합 셀 머리말("정성이 가득한 점심 (11:30~13:10)" 등)이 그룹명에
# 통째로 딸려 들어와 화면이 지저분해진다. 게다가 OCR이 매주 조금씩 다르게
# 읽어서, 나노기술원 한 채널에서만 그룹명이 20종류 넘게 생겼다
# ('A코너', '점심 A코너', 'A코너 (정성이 가득한 점심 11:30~13:10)' ...).
#
# 그래서 표시용 이름은 OCR 결과를 그대로 쓰지 않고 여기서 확정한다.
# 위에서부터 순서대로 검사해 처음 걸리는 규칙의 이름으로 바꾼다.
# 어느 규칙에도 안 걸리면 OCR이 읽은 이름을 그대로 둔다(예: 공휴일 '안내').
CHANNEL_GROUP_RENAME = {
    "nano_gaeram": [
        (re.compile(r"A\s*코너"), "A코너"),
        (re.compile(r"B\s*코너"), "B코너"),
        (re.compile(r"석식|저녁"), "석식"),
        (re.compile(r"PLUS|플러스", re.IGNORECASE), "PLUS"),
        # 위 규칙에 안 걸리는 뭉뚱그린 '점심' 그룹(드물게 OCR이 코너 구분을
        # 못 읽은 주)은 다른 채널과 표기를 맞춰 '중식'으로 둔다.
        (re.compile(r"점심"), "중식"),
    ],
}

# ---------------------------------------------------------------------------
# 병합된 그룹 분리 규칙
# ---------------------------------------------------------------------------
# 표에서 세로로 맞붙은 두 행을 OCR이 한 그룹으로 합쳐 읽는 경우가 있다.
# 나노기술원은 'PLUS(그린샐러드/후식차)' 행과 그 아래 '석식' 행이 한 덩어리로
# 읽혀서, 석식 메뉴가 통째로 중식 쪽에 붙거나 그 반대가 된다.
#   예) 'PLUS 하루를 마무리 하는 저녁 (17:30 ~ 18:30)'
#       -> ['그린샐러드/후식차', '계란볶음밥', '야채짬뽕국물', ...]
#
# name_keywords가 그룹명에 전부 들어 있을 때만, 앞쪽(head)에 연속으로 등장하는
# head_item_pattern 항목들을 떼어내 별도 그룹으로 분리한다.
# "앞에서부터 연속으로"만 보는 이유는, 석식 메뉴에 우연히 샐러드가 끼어 있어도
# 엉뚱하게 끌려오지 않게 하기 위해서다.
CHANNEL_GROUP_SPLIT = {
    "nano_gaeram": [
        {
            "name_keywords": ["PLUS", "저녁"],
            "head_name": "PLUS",
            "head_item_pattern": re.compile(r"샐러드|후식차|숭늉"),
            "tail_name": "석식",
        },
    ],
}

# 표의 빈 칸이 '-', '–', '.' 같은 찌꺼기 항목으로 읽히는 경우를 걸러낸다.
PLACEHOLDER_ITEM = re.compile(r"^[\s\-\u2013\u2014~.,/]*$")


def split_merged_groups(channel_name, group_name, items):
    """합쳐 읽힌 그룹을 (그룹명, 항목들) 리스트로 쪼갠다. 해당 없으면 원본 1개."""
    for rule in CHANNEL_GROUP_SPLIT.get(channel_name, []):
        name_upper = (group_name or "").upper()
        if not all(kw.upper() in name_upper for kw in rule["name_keywords"]):
            continue

        pattern = rule["head_item_pattern"]
        head = []
        for item in items:
            if not pattern.search(item or ""):
                break
            head.append(item)
        tail = items[len(head):]

        # 한쪽이 비면 분리 근거가 없는 것이므로 건드리지 않는다.
        if not head or not tail:
            continue

        return [(rule["head_name"], head), (rule["tail_name"], tail)]

    return [(group_name, items)]


def display_group_name(channel_name, group_name):
    for pattern, replacement in CHANNEL_GROUP_RENAME.get(channel_name, []):
        if pattern.search(group_name or ""):
            return replacement
    return group_name


def normalize_groups(channel_name, group_name, items):
    """OCR 그룹 하나를 화면에 쓸 (그룹명, 항목들) 리스트로 정리한다.

    분리 -> 이름 확정 -> 찌꺼기 항목 제거 순으로 처리한다.
    """
    normalized = []
    for name, group_items in split_merged_groups(channel_name, group_name, items):
        clean_items = [it for it in group_items if not PLACEHOLDER_ITEM.match(it or "")]
        # 항목이 비어도 그룹 자체는 지우지 않는다. 원래 비어 있던 그룹(공휴일 등)을
        # 조용히 없애면 기존 화면과 달라지므로, 찌꺼기 항목만 걷어낸다.
        normalized.append((display_group_name(channel_name, name), clean_items))
    return normalized


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
