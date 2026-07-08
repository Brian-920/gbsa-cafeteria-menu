"""
[3단계] OCR 스크립트 (무료 버전 — Google Gemini API 사용)
scrape_menu.py가 다운로드한 식단표 이미지를 Gemini Vision API로 읽어서
구조화된 JSON(요일별/코너별 메뉴)으로 변환한다.

필요 환경변수: GEMINI_API_KEY (GitHub Actions Secrets에 등록 필요)
발급 방법: https://aistudio.google.com/apikey 에서 무료로 발급 (신용카드 불필요)
사용 모델: gemini-2.5-flash (2026-07 기준 무료 티어 지원 모델. gemini-2.0-flash는 단종되어 사용 불가)
무료 할당량: 분당 10회, 일 250회 수준 (2026년 기준, 변동 가능)
   -> 이 프로젝트는 주 1회, 이미지 3장만 처리하므로 무료 할당량에 전혀 문제 없음
"""

import json
import os
from pathlib import Path

from google import genai
from google.genai import types

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

        if entry.get("image_download_status") != "success":
            print(f"이미지 다운로드가 안 되어 OCR 건너뜀: {entry.get('image_download_status')}")
            menu_outputs.append({
                "name": name,
                "label": label,
                "status": "skipped_no_image",
                "post_url": entry.get("post_url"),
            })
            continue

        image_path = Path(entry["local_image_path"])
        try:
            menu_json = ocr_image(client, image_path)
            menu_outputs.append({
                "name": name,
                "label": label,
                "status": "success",
                "post_url": entry.get("post_url"),
                "source_title": entry.get("title"),
                "menu": menu_json,
            })
            print(f"OCR 성공: {menu_json.get('period_label')}")
        except Exception as e:
            print(f"[오류] {name} OCR 실패: {e}")
            menu_outputs.append({
                "name": name,
                "label": label,
                "status": "error",
                "error": str(e),
                "post_url": entry.get("post_url"),
            })

    out_path = DATA_DIR / "menu_final.json"
    out_path.write_text(json.dumps(menu_outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n최종 결과 저장: {out_path}")


if __name__ == "__main__":
    main()
