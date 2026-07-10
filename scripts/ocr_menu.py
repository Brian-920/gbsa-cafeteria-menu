"""
[3단계] OCR 스크립트 (무료 버전 — Google Gemini API 사용)

scrape_menu.py가 만든 후보(최근 게시글 최대 MAX_CANDIDATES개)를 최신순으로
순회하며 OCR한다. 각 후보에 대해:
  1) 이미지를 실제로 읽을 수 있는 "식단표"인지 (Gemini가 days: []를 반환하면
     식단표가 아닌 것으로 판단 — SYSTEM_PROMPT 지침)
  2) 식단표라면, 그 안의 날짜가 "이번 주(월~금)"에 해당하는지 (rules.py의
     menu_matches_current_week)
두 조건을 모두 만족하는 첫 번째 후보를 채택한다. 5개 후보를 모두 시도해도
못 찾으면 status를 "not_found"로 남기고, merge_archive.py가 이를 보고
'정보 없음' 처리를 하게 된다.

필요 환경변수: GEMINI_API_KEY (GitHub Actions Secrets에 등록 필요)
발급 방법: https://aistudio.google.com/apikey 에서 무료로 발급 (신용카드 불필요)
사용 모델: gemini-2.5-flash (2026-07 기준 무료 티어 지원 모델. gemini-2.0-flash는 단종되어 사용 불가)
무료 할당량: 분당 10회, 일 250회 수준 (2026년 기준, 변동 가능)
   -> 이 프로젝트는 주 1회, 채널당 최대 5장(최악의 경우 3채널 x 5장 = 15회)만
      처리하므로 무료 할당량에 전혀 문제 없음
"""

import json
import os
from pathlib import Path

from google import genai
from google.genai import types

import rules

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
# 주의: gemini-2.0-flash는 2026년 3월 3일부로 단종되어 무료 할당량이 0으로 처리됨
# (2026-07 기준 무료 티어 최신 모델인 2.5-flash 사용. 추후 또 세대교체되면 업데이트 필요)
MODEL = "gemini-2.5-flash"

DATA_DIR = Path(__file__).parent.parent / "output" / "data"

SYSTEM_PROMPT = """당신은 한국 구내식당 주간 식단표 이미지를 읽어 구조화된 JSON으로 변환하는 도우미입니다.
이미지 안의 표를 최대한 정확하게 그대로 옮기세요. 절대로 이미지에 없는 메뉴를 추측해서 만들어내지 마세요.
표 형식이 채널마다 다를 수 있습니다 (요일별 5일 표, 코너별 표 등). 이미지에 보이는 구조를 최대한 그대로 반영하세요.

반드시 아래 JSON 스키마로만 응답하세요.

{
  "period_label": "이미지 상단에 표시된 기간/제목 (예: '7월 2째주', '0706-0710 주간메뉴')",
  "notice": "예약 문의 전화번호, 유의사항 등 표 외의 안내 문구 (없으면 빈 문자열)",
  "days": [
    {
      "day_label": "요일 또는 날짜 (예: '월요일 7월 6일', 이미지에 표시된 그대로)",
      "menu_groups": [
        {
          "group_name": "코너명 또는 카테고리명 (예: '오징어콩나물찜', 구분이 없으면 '메뉴')",
          "items": ["항목1", "항목2", "..."]
        }
      ]
    }
  ]
}

이미지에서 표를 읽을 수 없거나 식단표가 아닌 경우, days를 빈 배열로 두고 notice에 그 사유를 적으세요.
"""


def guess_mime_type(path: Path) -> str:
    ext = path.suffix.lower()
    return "image/png" if ext == ".png" else "image/jpeg"


def ocr_image(client: "genai.Client", image_path: Path) -> dict:
    mime_type = guess_mime_type(image_path)
    image_bytes = image_path.read_bytes()

    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            "이 식단표 이미지를 스키마에 맞는 JSON으로 변환해주세요.",
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0,
        ),
    )

    raw_text = (response.text or "").strip()
    return json.loads(raw_text)


def try_candidates(client: "genai.Client", candidates: list) -> dict:
    """후보를 최신순으로 순회하며 '이번 주 식단표'를 찾을 때까지 OCR한다."""
    attempts = []

    for cand in candidates:
        idx = cand["index"]

        if cand.get("image_download_status") != "success":
            print(f"  [후보 {idx}] 이미지 다운로드 실패로 건너뜀: {cand.get('image_download_status')}")
            attempts.append({"index": idx, "result": "skipped_no_image"})
            continue

        image_path = Path(cand["local_image_path"])
        try:
            menu_json = ocr_image(client, image_path)
        except Exception as e:
            print(f"  [후보 {idx}] OCR 실패: {e}")
            attempts.append({"index": idx, "result": "ocr_error", "error": str(e)})
            continue

        if not menu_json.get("days"):
            print(f"  [후보 {idx}] 식단표가 아닌 것으로 판단 (notice: {menu_json.get('notice')!r})")
            attempts.append({
                "index": idx,
                "result": "not_a_menu",
                "notice": menu_json.get("notice"),
            })
            continue

        if not rules.menu_matches_current_week(menu_json):
            print(f"  [후보 {idx}] 식단표이나 이번 주 날짜와 불일치 (period_label: {menu_json.get('period_label')!r})")
            attempts.append({
                "index": idx,
                "result": "date_mismatch",
                "period_label": menu_json.get("period_label"),
            })
            continue

        print(f"  [후보 {idx}] 채택: 이번 주 식단표 확인됨 (period_label: {menu_json.get('period_label')!r})")
        attempts.append({"index": idx, "result": "matched"})
        return {
            "status": "success",
            "post_url": cand.get("post_url"),
            "source_title": cand.get("title"),
            "matched_candidate_index": idx,
            "menu": menu_json,
            "candidate_attempts": attempts,
        }

    return {
        "status": "not_found",
        "candidate_attempts": attempts,
    }


def main():
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY 환경변수가 설정되어 있지 않습니다. "
            "GitHub Secrets에 GEMINI_API_KEY를 등록했는지 확인하세요."
        )

    scrape_result_path = DATA_DIR / "scrape_result.json"
    if not scrape_result_path.exists():
        print("scrape_result.json이 없습니다. scrape_menu.py를 먼저 실행하세요.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    scrape_results = json.loads(scrape_result_path.read_text(encoding="utf-8"))
    menu_outputs = []

    for entry in scrape_results:
        name = entry["name"]
        label = entry.get("label", name)
        print(f"\n=== [{name}] OCR 시작 (Gemini) ===")

        candidates = entry.get("candidates") or []
        if entry.get("status") != "success" or not candidates:
            print(f"스크래핑 결과가 없어 OCR 건너뜀: {entry.get('status')}")
            menu_outputs.append({
                "name": name,
                "label": label,
                "status": "not_found",
                "reason": entry.get("status"),
            })
            continue

        outcome = try_candidates(client, candidates)
        outcome["name"] = name
        outcome["label"] = label

        if outcome["status"] != "success":
            print(f"[{name}] 후보 {len(candidates)}개 내에서 이번 주 식단표를 찾지 못함 -> not_found 처리")

        menu_outputs.append(outcome)

    out_path = DATA_DIR / "menu_final.json"
    out_path.write_text(json.dumps(menu_outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n최종 결과 저장: {out_path}")


if __name__ == "__main__":
    main()
