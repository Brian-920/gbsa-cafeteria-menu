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

    complete = len(missing) == 0
    if complete:
        print("[check_week_complete] 이번 주 모든 식당 데이터가 채워졌습니다. 재시도 불필요.")
    else:
        print(f"[check_week_complete] 아직 채워지지 않은 항목: {missing}")

    write_output(complete)


if __name__ == "__main__":
    main()
