"""
[2단계] 실제 스크래핑 스크립트
1단계 진단에서 확인된 HTML 구조를 기반으로, 각 채널의 "가장 최근 게시글" 1건에서
식단표 이미지를 찾아 다운로드한다.

확인된 구조 (2026-07-08 진단 기준):
  <div class="area_card">                         <- 게시글 1개 단위, 최신순 정렬
    <strong class="tit_card">...날짜/제목...</strong>
    <div class="desc_card">...설명...</div>
    <div class="wrap_archive_content">
      <img class="img_thumb" src="...">            <- 식단표 이미지 (원본급 화질)

주의: 이미지 도메인(k.kakaocdn.net)은 pf.kakao.com과 달라서 리퍼러(Referer) 헤더 없이
다운로드하면 핫링크 방지에 걸려 차단될 수 있다. 아래 코드에서 Referer를 명시적으로 붙인다.
"""

import asyncio
import json
from pathlib import Path

import requests
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


async def scrape_channel(playwright, name: str, info: dict):
    url = info["url"]
    print(f"\n=== [{name}] {url} 스크래핑 시작 ===")
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context(
        viewport={"width": 430, "height": 932},
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        locale="ko-KR",
    )
    page = await context.new_page()

    result = {
        "name": name,
        "label": info["label"],
        "channel_url": url,
        "status": "unknown",
    }

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # 첫 번째 area_card(가장 최근 게시글) 하나만 선택
        first_card = page.locator("div.area_card").first
        count = await page.locator("div.area_card").count()
        print(f"발견된 게시글 카드 수: {count}")

        if count == 0:
            result["status"] = "no_card_found"
            return result

        title = await first_card.locator("strong.tit_card").inner_text()
        try:
            desc = await first_card.locator("div.desc_card").inner_text()
        except Exception:
            desc = ""

        post_href = await first_card.locator("a.link_title").first.get_attribute("href")
        post_url = f"https://pf.kakao.com{post_href}" if post_href and post_href.startswith("/") else post_href

        img_src = await first_card.locator("img.img_thumb").first.get_attribute("src")

        result.update({
            "status": "success",
            "title": title.strip(),
            "desc": desc.strip(),
            "post_url": post_url,
            "image_url": img_src,
        })
        print(f"제목: {title.strip()}")
        print(f"이미지 URL: {img_src}")

        # 이미지 다운로드 (Referer 헤더 필수 — 없으면 핫링크 차단 가능성)
        if img_src:
            IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            ext = ".png" if img_src.lower().endswith(".png") else ".jpg"
            image_path = IMAGES_DIR / f"{name}{ext}"

            resp = requests.get(
                img_src,
                headers={
                    "Referer": "https://pf.kakao.com/",
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                    ),
                },
                timeout=20,
            )
            print(f"이미지 다운로드 상태: {resp.status_code}, 크기: {len(resp.content)} bytes")

            if resp.status_code == 200 and len(resp.content) > 1000:
                image_path.write_bytes(resp.content)
                result["local_image_path"] = str(image_path)
                result["image_download_status"] = "success"
            else:
                result["image_download_status"] = f"failed (status={resp.status_code})"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"[오류] {name}: {e}")

    finally:
        await context.close()
        await browser.close()

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
