"""
대한민국 공휴일 조회 모듈.

공공데이터포털(data.go.kr)의 "특일 정보" API(한국천문연구원 제공)를 사용한다.
이 API는 정부 공식 소스라, 연초부터 정해진 공휴일뿐 아니라 연중에 국무회의로
추가 지정되는 "임시공휴일"도 정부 발표 후 API에 반영되는 대로 함께 조회된다.

필요 환경변수: KOREA_HOLIDAY_API_KEY
발급 방법:
  1) https://www.data.go.kr 회원가입
  2) "특일 정보" 검색 → "한국천문연구원_특일 정보" 활용신청 (자동승인, 무료)
  3) 마이페이지에서 인증키(서비스키) 확인 → GitHub Secrets에 KOREA_HOLIDAY_API_KEY로 등록

API 키가 없거나 호출이 실패하면, 이전에 저장해둔 캐시 파일(data/holidays_cache.json)을
그대로 사용한다. 캐시도 없으면 빈 목록으로 처리(공휴일 표시 없이 정상 동작).
"""

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

API_URL = "http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"
CACHE_PATH = Path(__file__).parent.parent / "data" / "holidays_cache.json"


def fetch_holidays_for_year(year: int, api_key: str) -> dict:
    """해당 연도의 공휴일을 {"YYYY-MM-DD": "공휴일명"} 형태로 반환. 실패 시 예외 발생."""
    holidays = {}
    for month in range(1, 13):
        params = {
            "serviceKey": api_key,
            "solYear": str(year),
            "solMonth": f"{month:02d}",
            "numOfRows": "50",
            "_type": "json",
        }
        resp = requests.get(API_URL, params=params, timeout=15)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        try:
            data = resp.json()
        except ValueError:
            # 일부 공공데이터 API는 오류 시에도 XML로 응답하는 경우가 있어 대비
            root = ET.fromstring(resp.text)
            raise RuntimeError(f"API가 JSON이 아닌 응답을 반환함: {ET.tostring(root, encoding='unicode')[:300]}")

        body = data.get("response", {}).get("body", {})
        items = body.get("items", "")
        if not items:
            continue
        item_list = items.get("item", [])
        if isinstance(item_list, dict):
            item_list = [item_list]

        for item in item_list:
            loc_date = str(item.get("locdate"))  # 예: 20260101
            name = item.get("dateName", "공휴일")
            is_holiday = item.get("isHoliday", "Y")
            if is_holiday != "Y":
                continue
            date_iso = f"{loc_date[0:4]}-{loc_date[4:6]}-{loc_date[6:8]}"
            holidays[date_iso] = name

    return holidays


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(holidays: dict):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(holidays, ensure_ascii=False, indent=2), encoding="utf-8")


def get_holidays(years: list) -> dict:
    """years에 해당하는 공휴일을 조회. API 키가 없거나 실패하면 캐시로 대체.
    성공 시 캐시를 최신 내용으로 갱신한다.
    """
    api_key = os.environ.get("KOREA_HOLIDAY_API_KEY")
    cache = load_cache()

    if not api_key:
        print("[holiday_utils] KOREA_HOLIDAY_API_KEY 없음 — 캐시된 공휴일 정보로 대체합니다.")
        return cache

    merged = dict(cache)  # 기존 캐시를 베이스로 시작 (API 부분 실패해도 과거 데이터는 유지)
    any_success = False

    for year in years:
        try:
            year_holidays = fetch_holidays_for_year(year, api_key)
            merged.update(year_holidays)
            any_success = True
            print(f"[holiday_utils] {year}년 공휴일 {len(year_holidays)}건 조회 성공")
        except Exception as e:
            print(f"[holiday_utils] {year}년 공휴일 조회 실패: {e} (캐시 유지)")

    if any_success:
        save_cache(merged)

    return merged
