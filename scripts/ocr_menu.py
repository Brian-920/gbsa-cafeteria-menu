"""
[3단계] OCR 스크립트
scrape_menu.py가 다운로드한 식단표 이미지를 Claude Vision API로 읽어서
구조화된 JSON(요일별/코너별 메뉴)으로 변환한다.

필요 환경변수: ANTHROPIC_API_KEY (GitHub Actions Secrets에 등록 필요)
"""

import base64
import json
import os
from pathlib import Path

import requests

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5"

DATA_DIR = Path(__file__).parent.parent / "output" / "data"

SYSTEM_PROMPT = """당신은 한국 구내식당 주간 식단표 이미지를 읽어 구조화된 JSON으로 변환하는 도우미입니다.
이미지 안의 표를 최대한 정확하게 그대로 옮기세요. 절대로 이미지에 없는 메뉴를 추측해서 만들어내지 마세요.
표 형식이 채널마다 다를 수 있습니다 (요일별 5일 표, 코너별 표 등). 이미지에 보이는 구조를 최대한 그대로 반영하세요.

반드시 아래 JSON 스키마로만 응답하세요. 다른 설명, 코드블록 마크다운(```json 등) 없이 순수 JSON만 출력하세요.

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


def encode_image(path: Path):
    ext = path.suffix.lower()
    media_type = "image/png" if ext == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return media_type, data


def ocr_image(image_path: Path):
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수가 설정되어 있지 않습니다.")

    media_type, b64data = encode_image(image_path)

    response = requests.post(
        API_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 2000,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64data,
                            },
                        },
                        {
                            "type": "text",
                            "text": "이 식단표 이미지를 스키마에 맞는 JSON으로 변환해주세요.",
                        },
                    ],
                }
            ],
        },
        timeout=60,
    )

    if response.status_code != 200:
        raise RuntimeError(f"API 오류 {response.status_code}: {response.text[:500]}")

    data = response.json()
    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    raw_text = "\n".join(text_blocks).strip()

    # 혹시 모델이 코드블록으로 감싸서 응답한 경우 제거
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.lower().startswith("json"):
            raw_text = raw_text[4:].strip()

    return json.loads(raw_text)


def main():
    scrape_result_path = DATA_DIR / "scrape_result.json"
    if not scrape_result_path.exists():
        print("scrape_result.json이 없습니다. scrape_menu.py를 먼저 실행하세요.")
        return

    scrape_results = json.loads(scrape_result_path.read_text(encoding="utf-8"))
    menu_outputs = []

    for entry in scrape_results:
        name = entry["name"]
        label = entry.get("label", name)
        print(f"\n=== [{name}] OCR 시작 ===")

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
            menu_json = ocr_image(image_path)
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
