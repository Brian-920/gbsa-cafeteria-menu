"""
OCR 결과 캐시.

같은 식단표 이미지를 몇 번이고 다시 OCR 하는 걸 막는다.

재시도 워크플로우가 하루에 여러 번 돌면서 매번 채널당 최대 5장을 OCR 하면
Gemini 무료 할당량(모델당 1일 20회)이 오전 중에 바닥난다. 이미지 바이트의
sha256을 키로 OCR 결과를 저장해두면, 같은 게시글이 계속 후보로 잡혀도
API를 다시 호출하지 않는다.

주의: "이번 주 식단표가 맞는지"(rules.menu_matches_current_week)는 캐시하지
않는다. 그 판정은 실행 시점에 따라 달라지므로, 캐시에는 OCR 원본 결과만
담고 날짜 검증은 매번 새로 한다.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

CACHE_PATH = Path(__file__).parent.parent / "data" / "ocr_cache.json"

# 캐시 파일이 무한정 커지지 않도록 보관할 최대 항목 수 (오래 안 쓴 것부터 버림)
MAX_ENTRIES = 150

CACHE_VERSION = 1


def image_key(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def _disabled() -> bool:
    """OCR 결과가 잘못 캐시된 경우 OCR_CACHE_DISABLED=1 로 우회할 수 있다."""
    return os.environ.get("OCR_CACHE_DISABLED", "").strip() not in ("", "0", "false", "False")


class OcrCache:
    def __init__(self, path: Path = CACHE_PATH):
        self.path = path
        self.entries = {}
        self.disabled = _disabled()
        self.hits = 0
        self.misses = 0
        self._dirty = False
        if not self.disabled:
            self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[ocr_cache] 캐시 로드 실패({e}) — 캐시 없이 진행합니다.")
            return
        if raw.get("version") != CACHE_VERSION:
            print("[ocr_cache] 캐시 버전이 달라 새로 시작합니다.")
            return
        self.entries = raw.get("entries") or {}

    def get(self, key: str):
        if self.disabled:
            return None
        entry = self.entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        self.hits += 1
        entry["last_used"] = datetime.now(timezone.utc).isoformat()
        self._dirty = True
        return entry.get("ocr")

    def put(self, key: str, ocr: dict, model: str):
        if self.disabled:
            return
        now = datetime.now(timezone.utc).isoformat()
        self.entries[key] = {"ocr": ocr, "model": model, "cached_at": now, "last_used": now}
        self._dirty = True

    def save(self):
        if self.disabled or not self._dirty:
            return
        # 오래 안 쓴 항목부터 정리
        if len(self.entries) > MAX_ENTRIES:
            ordered = sorted(
                self.entries.items(),
                key=lambda kv: kv[1].get("last_used", ""),
                reverse=True,
            )
            self.entries = dict(ordered[:MAX_ENTRIES])

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": CACHE_VERSION, "entries": self.entries}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ocr_cache] 저장 완료: {len(self.entries)}건 (적중 {self.hits} / 신규 {self.misses})")
