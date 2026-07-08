"""
[2단계] 실제 스크래핑 스크립트 (v2 — HTML 파싱 방식)

v1에서는 Playwright locator(.inner_text() 등)로 "화면에 보이는" 요소를 기다리다가
카카오 채널의 캐러셀/스와이프 UI 특성상 요소가 DOM에는 있지만 "visible" 판정을
받지 못해 타임아웃이 발생했다 (1차 실행 결과로 확인됨).

v2에서는 1단계 진단 스크립트와 동일한 방식 — 페이지의 HTML 원본을 그대로 가져와
BeautifulSoup으로 파싱 — 을 사용한다. "화면에 보이는지"를 따지지 않고 렌더링된
DOM 텍스트에서 바로 필요한 값을 뽑아내므로 훨씬 안정적이다.

확인된 구조 (2026-07-08 진단 기준):
  <div class="area_card">                         <- 게시글 1개 단위, 최신순 정렬
    <strong class="tit_card">...날짜/제목...</strong>
    <div class="desc_card">...설명...</div>
    <div class="wrap_archive_content">
      <img class="img_thumb" src="...">            <- 식단표 이미지 (원본급 화질)
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

OUTPUT_DIR = Path(__file__).parent.parent / "output"
IMAGES_DIR = OUTPUT_DIR / "images"
DATA_DIR = OUTPUT_DIR / "data"

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


async def fetch_rendered_html(playwright, url: str) -> str:
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context(
        viewport={"width": 430, "height": 932},
        user_agent=MOBILE_UA,
        locale="ko-KR",
    )
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)  # 1단계 진단과 동일하게 안정화 대기
        html = await page.content()
        return html
    finally:
        await context.close()
        await browser.close()


def parse_first_post(html: str):
    """가장 최근 게시글에서 제목/설명/링크/이미지 URL을 추출한다.

    주의: "div.area_card" 클래스는 실제 게시글 카드 외에
    "소식 84" 같은 상단 카운트 위젯에도 재사용되고 있어(2026-07-08 확인),
    단순히 첫 번째 매칭 요소를 쓰면 안 된다. strong.tit_card를 가진
    첫 번째 area_card를 실제 게시글로 판단한다.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates = soup.select("div.area_card")

    card = None
    for c in candidates:
        if c.select_one("strong.tit_card") is not None:
            card = c
            break

    if card is None:
        return None

    title_tag = card.select_one("strong.tit_card")
    desc_tag = card.select_one("div.desc_card")
    link_tag = card.select_one("a.link_title")
    img_tag = card.select_one("img.img_thumb")

    title = title_tag.get_text(strip=True) if title_tag else ""
    desc = desc_tag.get_text(strip=True) if desc_tag else ""
    href = link_tag.get("href") if link_tag else None
    post_url = f"https://pf.kakao.com{href}" if href and href.startswith("/") else href
    img_src = img_tag.get("src") if img_tag else None

    return {
        "title": title,
        "desc": desc,
        "post_url": post_url,
        "image_url": img_src,
    }


def download_image(img_src: str, dest_path: Path) -> dict:
    resp = requests.get(
        img_src,
        headers={
            "Referer": "https://pf.kakao.com/",
            "User-Agent": MOBILE_UA,
        },
        timeout=20,
    )
    print(f"이미지 다운로드 상태: {resp.status_code}, 크기: {len(resp.content)} bytes")

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
    }

    try:
        html = await fetch_rendered_html(playwright, url)
        print(f"HTML 길이: {len(html)}")

        parsed = parse_first_post(html)
        if parsed is None:
            result["status"] = "no_card_found"
            return result

        result.update({
            "status": "success",
            "title": parsed["title"],
            "desc": parsed["desc"],
            "post_url": parsed["post_url"],
            "image_url": parsed["image_url"],
        })
        print(f"제목: {parsed['title']}")
        print(f"이미지 URL: {parsed['image_url']}")

        if parsed["image_url"]:
            IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            ext = ".png" if parsed["image_url"].lower().endswith(".png") else ".jpg"
            image_path = IMAGES_DIR / f"{name}{ext}"

            dl_result = download_image(parsed["image_url"], image_path)
            if dl_result["status"] == "success":
                result["local_image_path"] = dl_result["path"]
                result["image_download_status"] = "success"
            else:
                result["image_download_status"] = dl_result["status"]
        else:
            result["image_download_status"] = "no_image_url_found"

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
        print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
