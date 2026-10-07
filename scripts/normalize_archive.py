"""
[보조 도구] 이미 쌓인 아카이브에 현재의 그룹 정리 규칙을 소급 적용한다.

rules.py의 정리 규칙(그룹명 통일, 병합 그룹 분리, 중식/석식 재분류, 찌꺼기 항목
제거)은 merge_archive.py가 "새로 병합할 때"만 적용된다. 그래서 규칙을 새로
추가하거나 고치면 과거에 저장된 기록은 예전 형태 그대로 남는다.

이 스크립트는 data/archive.json 전체를 다시 훑으며 같은 규칙을 적용한다.
메뉴 항목의 내용(텍스트)은 건드리지 않고, 그룹명과 중식/석식 소속만 바로잡는다.

사용법:
    python scripts/normalize_archive.py --dry-run   # 무엇이 바뀌는지만 출력
    python scripts/normalize_archive.py             # 실제로 저장

주의: 공휴일 '안내' 그룹처럼 어느 규칙에도 안 걸리는 그룹은 그대로 둔다.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import rules

ARCHIVE_PATH = Path(__file__).parent.parent / "data" / "archive.json"


def normalize_day(channel_name: str, day: dict):
    """하루치 entry를 정리한다. 바뀐 게 있으면 True."""
    before = json.dumps(
        [day.get("lunch_groups", []), day.get("dinner_groups", [])],
        ensure_ascii=False, sort_keys=True,
    )

    lunch, dinner = [], []
    # 중식/석식 소속도 다시 판정하므로, 양쪽을 한데 모아 처음부터 분류한다.
    for group in list(day.get("lunch_groups", [])) + list(day.get("dinner_groups", [])):
        for name, raw_items in rules.normalize_groups(
            channel_name, group.get("group_name", ""), group.get("items", [])
        ):
            items = rules.filter_excluded_items(channel_name, name, raw_items)
            bucket = rules.classify_meal_type(channel_name, name)
            (dinner if bucket == "dinner" else lunch).append(
                {"group_name": name, "items": items}
            )

    day["lunch_groups"] = lunch
    day["dinner_groups"] = dinner

    after = json.dumps([lunch, dinner], ensure_ascii=False, sort_keys=True)
    return before != after


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="저장하지 않고 바뀔 내용만 출력")
    args = parser.parse_args()

    archive = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))

    changed_days = 0
    renames = Counter()
    for channel_name, channel in archive.items():
        for date_iso, day in sorted(channel.get("days", {}).items()):
            old_names = [
                g.get("group_name", "")
                for g in list(day.get("lunch_groups", [])) + list(day.get("dinner_groups", []))
            ]
            if normalize_day(channel_name, day):
                changed_days += 1
                new_names = [
                    g["group_name"]
                    for g in day["lunch_groups"] + day["dinner_groups"]
                ]
                renames[(channel_name, tuple(old_names), tuple(new_names))] += 1

    print(f"바뀐 날짜 수: {changed_days}일")
    for (channel_name, old, new), count in sorted(renames.items(), key=lambda kv: -kv[1]):
        print(f"  [{channel_name}] {count:3d}일")
        print(f"      이전: {list(old)}")
        print(f"      이후: {list(new)}")

    if args.dry_run:
        print("\n(--dry-run 이므로 저장하지 않았습니다)")
        return

    ARCHIVE_PATH.write_text(
        json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n저장 완료: {ARCHIVE_PATH}")


if __name__ == "__main__":
    main()
