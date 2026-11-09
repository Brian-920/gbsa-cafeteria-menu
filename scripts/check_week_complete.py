"""
[재시도 여부 판단] 이번 주(월~금, 오늘까지) 모든 구내식당의 식단 데이터가
채워졌는지 확인하는 스크립트.

식당 게시글이 늦게 올라올 때를 대비해, retry-menu.yml 워크플로우가
평일 2시간마다 이 스크립트를 가장 먼저 실행한다.
- 이미 다 채워졌으면(complete=true) 뒤이은 스크래핑/배포 단계를 전부 건너뛴다
  (=사실상 실행 시간이 몇 초짜리 확인만 하고 끝난다).
- 아직 못 채운 식당이 있으면(complete=false) 평소와 같은 파이프라인
  (scrape -> ocr -> merge -> generate -> commit -> deploy)을 그대로 돈다.

주의: "이번 주 월~금" 중에서도 아직 오지 않은 미래 요일은 검사 대상에서
제외한다 (예: 오늘이 화요일이면 수/목/금은 아직 없는 게 정상이므로 완료
여부 판정에서 제외).
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import rules

ARCHIVE_PATH = Path(__file__).parent.parent / "data" / "archive.json"
KST = timezone(timedelta(hours=9))
CHANNELS = ["gbsa", "rdb_center", "nano_gaeram"]


def current_week_weekdays_up_to_today(now: datetime = None):
    """오늘(KST) 기준 이번 주 월~금 중, 오늘까지의 날짜만 반환한다."""
    now = now or datetime.now(KST)
    today = now.date()
    monday = today - timedelta(days=today.weekday())
    return [
        monday + timedelta(days=i)
        for i in range(5)
        if monday + timedelta(days=i) <= today
    ]


def channel_has_real_data(archive: dict, channel: str, date_iso: str) -> bool:
    day = archive.get(channel, {}).get("days", {}).get(date_iso)
    if day is None:
        return False
    if day.get("is_holiday"):
        return True  # 공휴일은 원래 메뉴가 없는 게 정상 -> 완료로 간주
    if day.get("no_data"):
        return False  # merge_archive.py가 채운 "정보 없음" 플레이스홀더
    return bool(day.get("lunch_groups")) or bool(day.get("dinner_groups"))


def channel_suspect_days(archive: dict, channel: str, now: datetime = None) -> dict:
    """이번 주 중 '표의 행이 OCR에서 빠진 것 같은' 날짜 -> 그룹명 목록.

    데이터가 비어 있지는 않지만 같은 주 다른 요일에 있는 중식 그룹이 빠진 경우
    (예: 2026-11-09 경과원 월요일의 '중식 일반식')를 잡아낸다. 한 번 재확인한
    날(rechecked)은 제외하므로 재시도가 무한히 반복되지 않는다.
    """
    days = archive.get(channel, {}).get("days", {})
    # 비교 기준은 '이번 주 월~금 전체'다. 식단표는 한 주치가 한꺼번에 올라오므로
    # 월요일 아침에도 화~금 데이터와 견줘서 월요일 누락을 알아챌 수 있다.
    week_isos = [d.isoformat() for d in rules.current_week_weekdays(now)]
    return rules.find_archive_days_missing_groups(days, week_isos)


def channels_missing_data(archive: dict, now: datetime = None) -> set:
    """이번 주(월~오늘) 중 아직 실제 식단 데이터가 없는 채널 이름 집합을 돌려준다.

    ocr_menu.py가 "이미 다 채워진 채널은 OCR을 건너뛰기" 위해 그대로 재사용한다.
    (Gemini 무료 할당량이 모델당 1일 20회뿐이라, 이미 확보한 채널까지 매번 다시
    OCR 하면 하루치 할당량이 금방 바닥난다.)
    """
    missing = set()
    for d in current_week_weekdays_up_to_today(now):
        date_iso = d.isoformat()
        for channel in CHANNELS:
            if not channel_has_real_data(archive, channel, date_iso):
                missing.add(channel)
    for channel in CHANNELS:
        if channel_suspect_days(archive, channel, now):
            missing.add(channel)
    return missing


def write_output(complete: bool):
    value = "true" if complete else "false"
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"complete={value}\n")
    print(f"complete={value}")


def main():
    if not ARCHIVE_PATH.exists():
        print("[check_week_complete] 아카이브가 아직 없습니다 -> 재시도 필요")
        write_output(False)
        return

    archive = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    check_dates = current_week_weekdays_up_to_today()

    missing = []
    for d in check_dates:
        date_iso = d.isoformat()
        for channel in CHANNELS:
            if not channel_has_real_data(archive, channel, date_iso):
                missing.append(f"{channel}:{date_iso}")

    for channel in CHANNELS:
        for date_iso, groups in channel_suspect_days(archive, channel).items():
            missing.append(f"{channel}:{date_iso}(누락 의심: {'/'.join(groups)})")

    complete = len(missing) == 0
    if complete:
        print("[check_week_complete] 이번 주 모든 식당 데이터가 채워졌습니다. 재시도 불필요.")
    else:
        print(f"[check_week_complete] 아직 채워지지 않은 항목: {missing}")

    write_output(complete)


if __name__ == "__main__":
    main()
