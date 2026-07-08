"""
[진단 스크립트] 1단계
목적: pf.kakao.com 채널 페이지에 실제로 무엇이 렌더링되는지 확인한다.
- 로그인 없이 접근 가능한지
- "소식" 탭의 게시글 목록/이미지가 실제 DOM에 존재하는지
- 클라우드(GitHub Actions) IP에서 접속이 차단되지는 않는지

실행 결과로 각 채널마다:
  1) 전체 페이지 스크린샷 (.png)
  2) 렌더링된 HTML 원본 (.html)
  3) 발견된 <img> 태그 src 목록 (.txt)
을 output/ 폴더에 저장한다. 이 결과물을 보고 2단계(실제 스크래핑 셀렉터 확정)를 진행한다.
"""

import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

CHANNELS = {
    "gbsa": "https://pf.kakao.com/_MgUGn/posts",
    "rdb_center": "https://pf.kakao.com/_XCVXb/posts",
    "nano_gaeram": "https://pf.kakao.com/_PxhQqX/posts",
}

OUTPUT_DIR = Path(__file__).parent.parent / "output" / "diagnose"


async def diagnose_channel(playwright, name: str, url: str):
    print(f"\n=== [{name}] {url} 접속 시도 ===")
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context(
        viewport={"width": 430, "height": 932},  # 모바일 뷰포트 (카카오는 모바일 최적화 페이지가 많음)
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        locale="ko-KR",
    )
    page = await context.new_page()

    result = {"name": name, "url": url, "status": "unknown", "note": ""}

    try:
        response = await page.goto(url, wait_until="networkidle", timeout=30000)
        status_code = response.status if response else None
        print(f"HTTP status: {status_code}")

        # 렌더링 안정화를 위해 잠시 대기 (SPA는 initial load 이후 추가 렌더링이 있을 수 있음)
        await page.wait_for_timeout(3000)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # 1) 스크린샷 저장
        screenshot_path = OUTPUT_DIR / f"{name}.png"
        await page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"스크린샷 저장: {screenshot_path}")

        # 2) HTML 원본 저장
        html_content = await page.content()
        html_path = OUTPUT_DIR / f"{name}.html"
        html_path.write_text(html_content, encoding="utf-8")
        print(f"HTML 저장: {html_path} ({len(html_content)} bytes)")

        # 3) 이미지 태그 목록 추출
        img_srcs = await page.eval_on_selector_all("img", "els => els.map(e => e.src)")
        img_list_path = OUTPUT_DIR / f"{name}_images.txt"
        img_list_path.write_text("\n".join(img_srcs), encoding="utf-8")
        print(f"발견된 이미지 태그 수: {len(img_srcs)}")

        # 로그인 요구 여부 간단 체크 (문구 기반, 참고용)
        page_text = await page.inner_text("body")
        login_hint = any(k in page_text for k in ["로그인", "카카오계정으로"])

        result["status"] = "success"
        result["http_status"] = status_code
        result["img_count"] = len(img_srcs)
        result["login_hint_detected"] = login_hint
        result["page_text_length"] = len(page_text)

        # 참고용으로 본문 텍스트 앞부분도 저장 (소식 목록 텍스트가 실제로 존재하는지 확인용)
        text_preview_path = OUTPUT_DIR / f"{name}_text_preview.txt"
        text_preview_path.write_text(page_text[:3000], encoding="utf-8")

    except Exception as e:
        result["status"] = "error"
        result["note"] = str(e)
        print(f"[오류] {name}: {e}")

    finally:
        await context.close()
        await browser.close()

    return result


async def main():
    summary = []
    async with async_playwright() as playwright:
        for name, url in CHANNELS.items():
            r = await diagnose_channel(playwright, name, url)
            summary.append(r)

    print("\n\n========== 진단 결과 요약 ==========")
    for r in summary:
        print(r)

    # 요약 파일 저장
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = OUTPUT_DIR / "summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        for r in summary:
            f.write(f"{r}\n")


if __name__ == "__main__":
    asyncio.run(main())
