"""
[3단계] OCR 스크립트 (무료 버전 — Google Gemini API 사용)

scrape_menu.py가 만든 후보(최근 게시글 최대 MAX_CANDIDATES개)를 최신순으로
순회하며 OCR한다. 각 후보에 대해:
  1) 이미지를 실제로 읽을 수 있는 "식단표"인지 (Gemini가 days: []를 반환하면
     식단표가 아닌 것으로 판단 — SYSTEM_PROMPT 지침)
  2) 식단표라면, 그 안의 날짜가 "이번 주(월~금)"에 해당하는지 (rules.py의
     menu_matches_current_week)
두 조건을 모두 만족하는 첫 번째 후보를 채택한다.

---------------------------------------------------------------------------
2026-10-07 수정 — 할당량/일시적 오류로 식단표를 통째로 놓치던 문제 해결
---------------------------------------------------------------------------
증상: 2026-10-05 ~ 10-07 주간에 경기도경제과학진흥원/한국나노기술원 식단표가
      "정보 없음"으로만 표시됨 (카카오 채널에는 정상 게시되어 있었음).

원인(실행 로그 확인):
  - Gemini가 503 UNAVAILABLE("high demand")을 돌려주면 예전 코드는 그 후보를
    즉시 포기하고 다음 후보로 넘어갔다. 과부하는 몇 초만 기다리면 풀리는
    일시적 오류인데, 5개 후보가 1초 안에 전부 소진되고 채널이 not_found 처리됐다.
  - 그렇게 실패한 호출도 무료 할당량(모델당 1일 20회)을 깎는다. 2시간마다 도는
    재시도 워크플로우가 매번 3채널 x 5후보 = 최대 15회를 호출하니, 하루 할당량이
    오전에 바닥나고 이후 모든 실행이 429로 실패하는 악순환에 빠졌다.

대응:
  1) 일시적 오류(5xx, 분당 한도 429)는 지수 백오프로 재시도한다.
  2) "하루 할당량 소진" 429를 만나면 그 모델 호출을 즉시 중단한다. 더 때려봐야
     할당량만 깎이고 성공할 수 없다.
  3) 모델을 여러 개 두고(GEMINI_MODELS) 앞 모델이 과부하/소진이면 다음 모델로
     넘어간다. 무료 할당량은 모델별로 따로 잡힌다.
  3-1) 주 모델을 gemini-2.5-flash로 되돌렸다. gemini-3.8-flash는 무료 1일 한도가
     약 20회뿐이라(2.5-flash는 약 500회) 이 파이프라인이 감당할 수 없다.
  4) 이미 이번 주 데이터를 확보한 채널은 OCR을 통째로 건너뛴다.
  5) OCR 결과를 이미지 해시 기준으로 캐시한다(data/ocr_cache.json). 재시도가
     여러 번 돌아도 같은 이미지를 다시 호출하지 않는다.
  6) 한 번 실행에서 쓸 수 있는 API 호출 수에 상한을 둬서(GEMINI_MAX_CALLS),
     한 번의 나쁜 실행이 하루치 할당량을 다 먹지 못하게 한다.

필요 환경변수: GEMINI_API_KEY (GitHub Actions Secrets에 등록 필요)
발급 방법: https://aistudio.google.com/apikey 에서 무료로 발급 (신용카드 불필요)
선택 환경변수:
  GEMINI_MODELS       쉼표로 구분한 모델 우선순위 (기본값 아래 DEFAULT_MODELS)
  GEMINI_MAX_CALLS    이번 실행에서 허용할 최대 API 호출 수 (기본 12)
  OCR_CACHE_DISABLED  1로 두면 OCR 캐시를 쓰지 않고 항상 새로 호출
"""

import json
import os
import re
import time
from pathlib import Path

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

import rules
import check_week_complete
from ocr_cache import OcrCache, image_key

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 무료 할당량은 모델마다 따로 잡히므로, 앞 모델이 과부하/소진이어도 뒤 모델로
# 한 번 더 기회를 가져갈 수 있다. 모델이 세대교체되면 이 목록만 고치면 된다.
#
# 순서가 중요하다. 무료 등급의 1일 요청 한도(RPD)는 모델마다 크게 다르다:
#   gemini-2.5-flash  약 500회/일   <- 이 프로젝트가 수개월간 문제없이 쓰던 모델
#   gemini-3.8-flash  약  20회/일   <- 최신 모델이지만 무료 한도가 25배 낮다
# 2026-09-30에 3.8-flash로 "업그레이드"한 뒤 10/05 주차부터 식단표를 못 가져온
# 원인이 바로 이것이다. 한도가 넉넉한 2.5-flash를 주 모델로 쓰고, 혹시 2.5가
# 단종되면 3.8이 받아주도록 뒤에 둔다.
#
# 주의: "gemini-flash-latest" 같은 별칭(alias)은 최신 모델을 가리키므로
# gemini-3.8-flash와 같은 할당량을 공유한다(2026-10-07 실행 로그에서 두 모델의
# 초기화 시각이 동일하게 찍혀 확인됨). 대체 모델로는 의미가 없어 뺐다.
# (gemini-2.0-flash는 2026-03-03부로 단종되어 무료 할당량이 0으로 처리됨)
DEFAULT_MODELS = "gemini-2.5-flash,gemini-3.8-flash"


def _model_list() -> list:
    """GEMINI_MODELS가 비어 있거나(워크플로의 미설정 변수는 빈 문자열로 들어온다)
    쉼표만 있는 경우에도 기본 모델 목록으로 안전하게 되돌아간다."""
    raw = os.environ.get("GEMINI_MODELS") or ""
    models = [m.strip() for m in raw.split(",") if m.strip()]
    return models or [m.strip() for m in DEFAULT_MODELS.split(",")]


MODELS = _model_list()

# 일시적 오류(과부하/분당 한도)에 대한 재시도 횟수와 대기 시간(초)
RETRY_BACKOFF_SECONDS = [5, 15, 30]

# 429의 retryDelay가 이 값보다 길면 "분당 한도"가 아니라 "하루 할당량 소진"으로 본다.
QUOTA_HARD_THRESHOLD_SECONDS = 600

# 이번 실행에서 쓸 수 있는 API 호출 총량. 한 번의 실행이 하루치 할당량을 다 먹지
# 않게 상한을 두되, 503 재시도(후보 하나에 최대 8회)와 2차 시도, 누락 재확인을
# 감당하도록 12 -> 20으로 올렸다. (주 모델 gemini-2.5-flash는 무료 1일 약 500회)
DEFAULT_MAX_API_CALLS = 20


def _max_api_calls() -> int:
    raw = (os.environ.get("GEMINI_MAX_CALLS") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_API_CALLS
    return value if value > 0 else DEFAULT_MAX_API_CALLS


MAX_API_CALLS = _max_api_calls()

TRANSIENT_HTTP_CODES = {500, 502, 503, 504}

# 1차 순회에서 '이번 주 글(후보 0)'이 일시적 오류(503 등)로 읽히지 않았을 때,
# 다른 채널을 모두 처리한 뒤 이만큼(초) 기다렸다가 한 번 더 시도한다.
# (2026-11-09: R&DB센터 이번 주 글이 두 모델 모두 503이라 한 주 전체가 '정보 없음'이 됨)
SECOND_PASS_WAIT_SECONDS = int(os.environ.get("OCR_SECOND_PASS_WAIT") or 90)

DATA_DIR = Path(__file__).parent.parent / "output" / "data"
ARCHIVE_PATH = Path(__file__).parent.parent / "data" / "archive.json"

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


class QuotaExhausted(Exception):
    """쓸 수 있는 모델의 하루치 무료 할당량이 전부 소진됨.

    더 호출해도 성공할 수 없으므로 이번 실행의 OCR을 즉시 중단한다.
    """


class BudgetExhausted(Exception):
    """이번 실행에 허용한 API 호출 예산(MAX_API_CALLS)을 모두 사용함."""


def gh_warning(message: str):
    """GitHub Actions 실행 요약에 경고로 표시되도록 출력한다 (워크플로는 계속 진행)."""
    one_line = message.replace("\n", " ")
    print(f"::warning title=구내식당 식단표 OCR::{one_line}")
    print(f"[경고] {message}")


def guess_mime_type(path: Path) -> str:
    ext = path.suffix.lower()
    return "image/png" if ext == ".png" else "image/jpeg"


def parse_retry_delay_seconds(err) -> float:
    """429 응답에서 '얼마나 기다리라'는 값을 초 단위로 뽑는다. 못 찾으면 -1."""
    details = getattr(err, "details", None)
    if isinstance(details, dict):
        blocks = details.get("error", {}).get("details") or details.get("details") or []
        if isinstance(blocks, list):
            for block in blocks:
                if isinstance(block, dict) and block.get("retryDelay"):
                    m = re.match(r"([0-9.]+)s?$", str(block["retryDelay"]))
                    if m:
                        return float(m.group(1))

    # details가 없을 때를 대비한 보조 경로: 메시지의 "Please retry in 4h40m52.5s"
    message = str(getattr(err, "message", "") or err)
    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?([0-9.]+)s", message)
    if m:
        hours = int(m.group(1) or 0)
        minutes = int(m.group(2) or 0)
        seconds = float(m.group(3))
        return hours * 3600 + minutes * 60 + seconds

    return -1.0


class GeminiOcr:
    """모델 우선순위 + 재시도 + 할당량 보호 + 캐시를 한 군데로 모은 OCR 실행기."""

    def __init__(self, client, cache: OcrCache):
        self.client = client
        self.cache = cache
        self.calls_used = 0
        self.exhausted_models = set()  # 하루 할당량이 소진된 모델

    def available_models(self):
        return [m for m in MODELS if m not in self.exhausted_models]

    def _generate(self, model: str, image_bytes: bytes, mime_type: str, hint: str = "") -> dict:
        if self.calls_used >= MAX_API_CALLS:
            raise BudgetExhausted(
                f"이번 실행의 API 호출 예산 {MAX_API_CALLS}회를 모두 사용했습니다."
            )
        self.calls_used += 1

        response = self.client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                "이 식단표 이미지를 스키마에 맞는 JSON으로 변환해주세요." + (f"\n{hint}" if hint else ""),
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        return json.loads((response.text or "").strip())

    def _ocr_with_model(self, model: str, image_bytes: bytes, mime_type: str, hint: str = "") -> dict:
        """한 모델로 OCR을 시도한다. 일시적 오류는 백오프 후 재시도.

        돌려주는 값:
          dict  -> 성공
          None  -> 이 모델로는 실패 (다음 모델로 넘어가도 됨)
        예외:
          QuotaExhausted  -> 모든 모델의 하루 할당량 소진
          BudgetExhausted -> 이번 실행 호출 예산 소진
        """
        for attempt in range(len(RETRY_BACKOFF_SECONDS) + 1):
            try:
                return self._generate(model, image_bytes, mime_type, hint)

            except genai_errors.APIError as e:
                code = getattr(e, "code", None)

                if code == 429:
                    delay = parse_retry_delay_seconds(e)
                    if delay < 0 or delay >= QUOTA_HARD_THRESHOLD_SECONDS:
                        # 하루 할당량 소진 — 이 모델은 오늘 더 못 쓴다.
                        self.exhausted_models.add(model)
                        gh_warning(
                            f"[{model}] 무료 하루 할당량이 소진되었습니다"
                            f"(약 {max(delay, 0) / 3600:.1f}시간 후 초기화). 이 모델 호출을 중단합니다."
                        )
                        if not self.available_models():
                            raise QuotaExhausted(
                                "사용 가능한 모든 모델의 하루 할당량이 소진되었습니다."
                            ) from e
                        return None

                    # 분당 한도 — 잠깐 기다리면 풀린다.
                    if attempt < len(RETRY_BACKOFF_SECONDS):
                        wait = max(delay, RETRY_BACKOFF_SECONDS[attempt])
                        print(f"    [{model}] 분당 한도(429). {wait:.0f}초 후 재시도합니다.")
                        time.sleep(wait)
                        continue
                    print(f"    [{model}] 분당 한도(429)가 재시도 후에도 풀리지 않았습니다.")
                    return None

                if code in TRANSIENT_HTTP_CODES:
                    if attempt < len(RETRY_BACKOFF_SECONDS):
                        wait = RETRY_BACKOFF_SECONDS[attempt]
                        print(f"    [{model}] 일시적 오류({code}). {wait}초 후 재시도합니다.")
                        time.sleep(wait)
                        continue
                    print(f"    [{model}] 일시적 오류({code})가 재시도 후에도 계속됩니다.")
                    return None

                # 400(잘못된 요청), 404(없는 모델) 등은 재시도해도 소용없다.
                print(f"    [{model}] 호출 실패({code}): {getattr(e, 'message', e)}")
                return None

            except json.JSONDecodeError as e:
                print(f"    [{model}] 응답을 JSON으로 읽지 못했습니다: {e}")
                return None

        return None

    def _ocr_any_model(self, image_bytes: bytes, mime_type: str, hint: str = ""):
        """모델 우선순위대로 시도해 (결과, 모델명)을 돌려준다. 전부 실패하면 (None, None)."""
        for model in self.available_models():
            result = self._ocr_with_model(model, image_bytes, mime_type, hint)
            if result is not None:
                return result, model
        return None, None

    def ocr_image(self, image_path: Path, channel_name: str = None):
        """캐시를 먼저 보고, 없으면 모델 우선순위대로 OCR한다.

        돌려주는 값: (OCR 결과 또는 None, rechecked)
          rechecked: '표의 행이 빠진 것 같아' 힌트를 주고 한 번 더 읽어본 결과인지.
                     한 번 재확인한 이미지는 같은 이유로 다시 API를 부르지 않는다.

        2026-11-09 경과원 월요일 칸에서 '중식 일반식' 행이 통째로 빠진 채 읽혔고,
        그 결과가 캐시에 남아 계속 재사용되는 문제가 있어 누락 점검 + 재확인을 추가했다.
        """
        image_bytes = image_path.read_bytes()
        key = image_key(image_bytes)
        mime_type = guess_mime_type(image_path)

        entry = self.cache.get_entry(key)
        if entry is not None:
            print("    (캐시 적중 — API 호출 없음)")
            result = entry.get("ocr")
            rechecked = bool(entry.get("recheck_done"))
            model_used = entry.get("model", "")
        else:
            result, model_used = self._ocr_any_model(image_bytes, mime_type)
            if result is None:
                return None, False
            rechecked = False
            self.cache.put(key, result, model_used)

        if not channel_name or not result.get("days") or rechecked:
            return result, rechecked

        missing = rules.find_missing_groups_in_menu(result, channel_name)
        if not missing:
            return result, False

        summary = ", ".join(f"{day}: {'/'.join(groups)}" for day, groups in missing.items())
        print(f"    [누락 의심] {summary} -> 힌트를 주고 한 번 더 읽어봅니다.")
        hint = (
            "주의: 이전 판독에서 다음 행이 누락된 것으로 보입니다 - "
            + "; ".join(f"{day}의 '{'/'.join(groups)}'" for day, groups in missing.items())
            + ". 표의 모든 요일 열에서 모든 행(코너)을 빠짐없이 읽어 days 전체를 다시 출력하세요. "
            "실제로 비어 있는 칸만 빈 items로 두세요."
        )
        try:
            retry, retry_model = self._ocr_any_model(image_bytes, mime_type, hint)
        except (QuotaExhausted, BudgetExhausted) as e:
            print(f"    [누락 재확인 생략] {e}")
            return result, False

        if retry is None or not retry.get("days"):
            print("    [누락 재확인 실패] 기존 결과를 유지하고 다음 실행에서 다시 시도합니다.")
            return result, False

        retry_missing = rules.find_missing_groups_in_menu(retry, channel_name)
        if sum(len(v) for v in retry_missing.values()) <= sum(len(v) for v in missing.values()):
            result, model_used = retry, retry_model
            print(f"    [누락 재확인 완료] 남은 의심: {retry_missing or '없음'}")
        else:
            print("    [누락 재확인] 새 결과가 더 나빠 기존 결과를 유지합니다.")
        self.cache.put(key, result, model_used or "", recheck_done=True)
        return result, True


def try_candidates(ocr: GeminiOcr, candidates: list, channel_name: str = None) -> dict:
    """후보를 최신순으로 순회하며 '이번 주 식단표'를 찾을 때까지 OCR한다."""
    attempts = []

    for cand in candidates:
        idx = cand["index"]

        if cand.get("image_download_status") != "success":
            print(f"  [후보 {idx}] 이미지 다운로드 실패로 건너뜀: {cand.get('image_download_status')}")
            attempts.append({"index": idx, "result": "skipped_no_image"})
            continue

        image_path = Path(cand["local_image_path"])
        print(f"  [후보 {idx}] OCR 시도")
        menu_json, rechecked = ocr.ocr_image(image_path, channel_name)

        if menu_json is None:
            print(f"  [후보 {idx}] OCR 실패 (재시도/대체 모델까지 모두 실패)")
            attempts.append({"index": idx, "result": "ocr_error"})
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
            "rechecked": rechecked,
            "menu": menu_json,
            "candidate_attempts": attempts,
        }

    outcome = {
        "status": "not_found",
        "candidate_attempts": attempts,
    }
    # 최신 글을 일시적 오류로 못 읽은 경우: 화면의 '원본 게시글 보기'가 지난주 글을
    # 가리키지 않도록 최신 글 주소를 함께 남긴다.
    if attempts and attempts[0].get("result") == "ocr_error":
        outcome["latest_post_url"] = candidates[0].get("post_url")
        outcome["transient_failure"] = True
    return outcome


def load_channels_needing_ocr() -> set:
    """이번 주 데이터가 아직 없는 채널만 돌려준다 (없으면 None = 전부 시도)."""
    if not ARCHIVE_PATH.exists():
        return None
    try:
        archive = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ocr_menu] 아카이브 로드 실패({e}) — 모든 채널을 시도합니다.")
        return None
    return check_week_complete.channels_missing_data(archive)


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
    cache = OcrCache()
    ocr = GeminiOcr(client, cache)

    needs_ocr = load_channels_needing_ocr()
    if needs_ocr is not None:
        print(f"[ocr_menu] 이번 주 데이터가 비어 있는 채널: {sorted(needs_ocr) or '없음'}")

    scrape_results = json.loads(scrape_result_path.read_text(encoding="utf-8"))
    menu_outputs = []
    halt_reason = None

    for entry in scrape_results:
        name = entry["name"]
        label = entry.get("label", name)

        if halt_reason:
            menu_outputs.append({
                "name": name, "label": label,
                "status": "not_found", "reason": halt_reason,
            })
            continue

        if needs_ocr is not None and name not in needs_ocr:
            print(f"\n=== [{name}] 이번 주 데이터가 이미 있어 OCR을 건너뜁니다 ===")
            menu_outputs.append({
                "name": name, "label": label,
                "status": "skipped_already_complete",
            })
            continue

        print(f"\n=== [{name}] OCR 시작 (Gemini) ===")

        candidates = entry.get("candidates") or []
        if entry.get("status") != "success" or not candidates:
            print(f"스크래핑 결과가 없어 OCR 건너뜀: {entry.get('status')}")
            menu_outputs.append({
                "name": name, "label": label,
                "status": "not_found", "reason": entry.get("status"),
            })
            continue

        try:
            outcome = try_candidates(ocr, candidates, name)
        except (QuotaExhausted, BudgetExhausted) as e:
            halt_reason = type(e).__name__
            gh_warning(
                f"[{name}] OCR 중단: {e} "
                "다음 재시도 실행에서 이어서 처리합니다 (이미 확보한 채널은 건너뜁니다)."
            )
            menu_outputs.append({
                "name": name, "label": label,
                "status": "not_found", "reason": halt_reason,
            })
            continue

        outcome["name"] = name
        outcome["label"] = label

        if outcome["status"] != "success":
            print(f"[{name}] 후보 {len(candidates)}개 내에서 이번 주 식단표를 찾지 못함 -> not_found 처리")

        menu_outputs.append(outcome)

    # 2차 시도: 일시적 오류(503 등)로 이번 주 글을 못 읽은 채널을 잠시 뒤 한 번 더 시도.
    retry_targets = [
        (i, o) for i, o in enumerate(menu_outputs)
        if o.get("transient_failure") and not halt_reason
    ]
    if retry_targets:
        names = [o["name"] for _, o in retry_targets]
        print(f"\n[ocr_menu] 일시적 오류로 못 읽은 채널 {names} — {SECOND_PASS_WAIT_SECONDS}초 후 2차 시도")
        time.sleep(SECOND_PASS_WAIT_SECONDS)
        entries_by_name = {e["name"]: e for e in scrape_results}
        for i, old in retry_targets:
            name = old["name"]
            candidates = entries_by_name[name].get("candidates") or []
            print(f"\n=== [{name}] 2차 OCR 시도 ===")
            try:
                outcome = try_candidates(ocr, candidates, name)
            except (QuotaExhausted, BudgetExhausted) as e:
                gh_warning(f"[{name}] 2차 OCR 중단: {e}")
                break
            outcome["name"] = name
            outcome["label"] = old["label"]
            menu_outputs[i] = outcome

    cache.save()

    out_path = DATA_DIR / "menu_final.json"
    out_path.write_text(json.dumps(menu_outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n최종 결과 저장: {out_path}")
    print(f"이번 실행 API 호출: {ocr.calls_used}회 / 예산 {MAX_API_CALLS}회"
          f" (캐시 적중 {cache.hits}회)")
    if ocr.exhausted_models:
        print(f"하루 할당량이 소진된 모델: {sorted(ocr.exhausted_models)}")


if __name__ == "__main__":
    main()
