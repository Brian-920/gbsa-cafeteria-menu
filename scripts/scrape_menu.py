"""
[2단계] 실제 스크래핑 스크립트 (v3 — 최근 게시글 N개 후보 탐색 방식)

v2에서는 각 채널의 "가장 최신 글"만 식단표라고 가정하고 1개만 가져왔다.
그런데 아주 가끔 채널이 최신 글로 긴급 공지(텍스트) 또는 별도 안내 이미지를
올리는 경우가 있어, 이 경우 식단표를 못 찾는 문제가 있었다 (2026-07-10 확인).

v3에서는 최신순으로 최대 MAX_CANDIDATES개의 게시글을 후보로 남겨두고,
이후 단계(ocr_menu.py)에서 각 후보를 순서대로 OCR + 날짜 검증하며
"이번 주 식단표"를 찾을 때까지 시도한다. 이 스크립트는 후보 목록과
각 후보의 이미지 다운로드까지만 담당한다.

확인된 구조 (2026-07-08 진단 기준):
  <div class="area_card">                         <- 게시글 1개 단위, 최신순 정렬
    <strong class="tit_card">...날짜/제목...</strong>
    <div class="desc_card">...설명...</div>
    <div class="wrap_archive_content">
      <img class="img_thumb" src="...">            <- 식단표 이미지 (원본급 화질)

스크롤 관련 참고:
  카카오 채널 posts 피드가 초기 로드 시 몇 개의 게시글까지 DOM에 담아두는지는
  실측 전까지 확실치 않다. 그래서 초기 로드 후 유효 카드 수가 MAX_CANDIDATES에
  못 미치면 스크롤을 시도해 추가 로드를 유도하고, 그 결과(카드 수 변화)를
  scrape_result.json의 scroll_diagnostics에 기록한다. 실행 로그/아티팩트로
  스크롤이 실제로 필요했는지, 몇 번 만에 몇 개까지 늘었는지 확인할 수 있다.
"""

import asyncio
import json
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

CHANNELS = {
    "gbsa": {
        "label": "경기도경제과학진흥원 구내식당",
        "url": "https://pf.kakao.com/_MgUGn/posts",
    },
    "rdb_center": {
        "label": "경기R&DB센터 구내식당",
        "url": "https://pf.kakao.com/_XCVXb/posts",
    },
    "nano_gaeram": {
        "label": "나노기술원 가람푸드써비스 구내식당",
        "url": "https://pf.kakao.com/_PxhQqX/posts",
    },
}

# 최신 글이 공지/안내인 경우를 대비해, 최근 게시글 최대 몇 개까지를
# 식단표 후보로 볼 것인지. (2026-07-10 요청 반영: 5개)
MAX_CANDIDATES = 5
MAX_SCROLL_ATTEMPTS = 5

OUTPUT_DIR = Path(__file__).parent.parent / "output"
IMAGES_DIR = OUTPUT_DIR / "images"
DATA_DIR = OUTPUT_DIR / "data"

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def count_valid_cards(html: str) -> int:
    """실제 게시글 카드(strong.tit_card를 가진 area_card) 개수만 센다.
    상단 '소식 84' 같은 카운트 위젯도 area_card 클래스를 재사용하므로
    tit_card 유무로 걸러낸다."""
    soup = BeautifulSoup(html, "html.parser")
    return len([c for c in soup.select("div.area_card") if c.select_one("strong.tit_card")])


async def fetch_rendered_html(playwright, url: str, min_cards: int = MAX_CANDIDATES):
    """카드가 min_cards개 이상 나타날 때까지 스크롤을 시도하며 렌더링한다.

    반환값: (최종 HTML, 진단 정보 dict)
    """
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context(
        viewport={"width": 430, "height": 932},
        user_agent=MOBILE_UA,
        locale="ko-KR",
    )
    page = await context.new_page()
    diag = {"initial_card_count": 0, "scroll_attempts": 0, "final_card_count": 0, "scroll_log": []}

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)  # 안정화 대기

        html = await page.content()
        prev_count = count_valid_cards(html)
        diag["initial_card_count"] = prev_count

        attempts = 0
        while prev_count < min_cards and attempts < MAX_SCROLL_ATTEMPTS:
            await page.mouse.wheel(0, 3000)
            await page.wait_for_timeout(1500)
            html = await page.content()
            new_count = count_valid_cards(html)
            attempts += 1
            diag["scroll_log"].append({"attempt": attempts, "card_count": new_count})
            print(f"  [스크롤 {attempts}회] 카드 수: {prev_count} -> {new_count}")

            if new_count <= prev_count:
                # 더 스크롤해도 카드 수가 늘지 않음 = 게시글 끝에 도달했거나
                # 스크롤 트리거 방식이 다름(추가 검토 필요)
                prev_count = new_count
                break
            prev_count = new_count

        diag["scroll_attempts"] = attempts
        diag["final_card_count"] = prev_count
        return html, diag
    finally:
        await context.close()
        await browser.close()


def parse_candidate_posts(html: str, max_n: int = MAX_CANDIDATES):
    """최신순 게시글 카드 중 최대 max_n개를 파싱해 리스트로 반환한다."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = soup.select("div.area_card")

    posts = []
    for c in candidates:
        if c.select_one("strong.tit_card") is None:
            continue

        title_tag = c.select_one("strong.tit_card")
        desc_tag = c.select_one("div.desc_card")
        link_tag = c.select_one("a.link_title")
        img_tag = c.select_one("img.img_thumb")

        href = link_tag.get("href") if link_tag else None
        post_url = f"https://pf.kakao.com{href}" if href and href.startswith("/") else href

        posts.append({
            "title": title_tag.get_text(strip=True) if title_tag else "",
            "desc": desc_tag.get_text(strip=True) if desc_tag else "",
            "post_url": post_url,
            "image_url": img_tag.get("src") if img_tag else None,
        })

        if len(posts) >= max_n:
            break

    return posts


def download_image(img_src: str, dest_path: Path) -> dict:
    resp = requests.get(
        img_src,
        headers={
            "Referer": "https://pf.kakao.com/",
            "User-Agent": MOBILE_UA,
        },
        timeout=20,
    )
    print(f"    이미지 다운로드 상태: {resp.status_code}, 크기: {len(resp.content)} bytes")

    if resp.status_code == 200 and len(resp.content) > 1000:
        dest_path.write_bytes(resp.content)
        return {"status": "success", "path": str(dest_path)}
    return {"status": f"failed (status={resp.status_code}, size={len(resp.content)})"}


async def scrape_channel(playwright, name: str, info: dict):
    url = info["url"]
    print(f"\n=== [{name}] {url} 스크래핑 시작 ===")

    result = {
        "name": name,
        "label": info["label"],
        "channel_url": url,
        "status": "unknown",
        "candidates": [],
    }

    try:
        html, diag = await fetch_rendered_html(playwright, url)
        print(f"HTML 길이: {len(html)} / 카드 수 진단: {diag}")
        result["scroll_diagnostics"] = diag

        posts = parse_candidate_posts(html)
        if not posts:
            result["status"] = "no_card_found"
            return result

        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        for idx, parsed in enumerate(posts):
            print(f"  [후보 {idx}] 제목: {parsed['title']}")
            cand = {
                "index": idx,
                "title": parsed["title"],
                "desc": parsed["desc"],
                "post_url": parsed["post_url"],
                "image_url": parsed["image_url"],
            }

            if parsed["image_url"]:
                ext = ".png" if parsed["image_url"].lower().endswith(".png") else ".jpg"
                image_path = IMAGES_DIR / f"{name}_{idx}{ext}"
                dl_result = download_image(parsed["image_url"], image_path)
                if dl_result["status"] == "success":
                    cand["local_image_path"] = dl_result["path"]
                    cand["image_download_status"] = "success"
                else:
                    cand["image_download_status"] = dl_result["status"]
            else:
                cand["image_download_status"] = "no_image_url_found"

            result["candidates"].append(cand)

        result["status"] = "success"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"[오류] {name}: {e}")

    return result


async def main():
    results = []
    async with async_playwright() as playwright:
        for name, info in CHANNELS.items():
            r = await scrape_channel(playwright, name, info)
            results.append(r)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "scrape_result.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n\n========== 스크래핑 결과 요약 ==========")
    for r in results:
        summary = {k: v for k, v in r.items() if k != "candidates"}
        summary["candidate_count"] = len(r.get("candidates", []))
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
