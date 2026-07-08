# GBSA 구내식당 식단표 자동화

카카오톡 채널 3곳(GBSA 구내식당, 경기R&DB센터 구내식당, 나노기술원 가람푸드써비스)의
최신 게시글에서 식단표 이미지를 자동으로 가져와 OCR로 읽고, 하나의 웹페이지로 정리해
매주 월요일 오전 7시(KST)에 자동 갱신합니다.

## 1단계 진단 결과 (완료)

- 3개 채널 모두 **로그인 없이, 클라우드 서버(GitHub Actions)에서 접속 가능** 확인됨
- 최신 게시글의 날짜/제목/이미지가 담긴 HTML 구조 확인 완료 (`div.area_card` 안의 `img.img_thumb`)

## 파이프라인 구조

```
scripts/scrape_menu.py   → 각 채널 최신 글의 식단표 이미지 다운로드 (output/images/)
scripts/ocr_menu.py       → Claude Vision API로 이미지를 구조화된 JSON으로 변환 (output/data/menu_final.json)
scripts/generate_site.py  → JSON을 읽어 index.html 생성 (output/site/index.html)
```

GitHub Actions 워크플로우(`.github/workflows/update-menu.yml`)가 이 3단계를 순서대로 실행하고,
결과 웹페이지를 **GitHub Pages**로 자동 배포합니다.

## 설정 방법 (최초 1회)

### ① Anthropic API 키 등록 (OCR에 필요)

1. 저장소의 **Settings → Secrets and variables → Actions** 이동
2. **New repository secret** 클릭
3. Name: `ANTHROPIC_API_KEY`
4. Value: 발급받은 API 키 값 입력 (console.anthropic.com에서 발급)
5. **Add secret** 저장

> API 키가 없으면 OCR 단계에서 실패합니다. 유료 API 키가 필요하며, 이미지 1건당 호출 비용이 소액 발생합니다.

### ② GitHub Pages 활성화

1. 저장소의 **Settings → Pages** 이동
2. **Build and deployment → Source**를 **Deploy from a branch**로 설정
3. Branch를 **gh-pages** 로 선택 (워크플로우를 한 번 실행한 뒤에 `gh-pages` 브랜치가 생성됩니다. 처음엔 안 보일 수 있으니, 1번 수동 실행 후 다시 와서 설정)
4. 저장하면 `https://[깃허브아이디].github.io/gbsa-cafeteria-menu/` 주소로 접속 가능

## 테스트 실행 방법

1. **Actions 탭** → `구내식당 식단표 자동 업데이트` 선택
2. **Run workflow** 버튼으로 수동 실행
3. 완료 후:
   - 실패했다면 실행 로그에서 어느 단계(스크래핑/OCR/사이트생성)에서 막혔는지 확인
   - 성공했다면 **Artifacts**에서 `menu-run-output`을 받아 다운로드받은 이미지와 OCR 결과 JSON을 확인
   - `gh-pages` 브랜치가 생겼는지 확인 후, Pages 설정을 완료하면 실제 웹페이지 확인 가능

## 알려진 리스크 / 다음에 확인할 것

- **OCR 정확도**: 표 형식이 복잡하거나 손글씨/공지사항이 섞여 있으면 Claude가 완벽하게 못 읽을 수 있습니다. 실제 실행 결과(JSON)를 보고 프롬프트를 조정해야 할 수 있습니다.
- **이미지 다운로드 차단 가능성**: `k.kakaocdn.net` 이미지 서버가 Referer 헤더 없이는 핫링크를 차단할 수 있어 코드에 Referer 헤더를 추가해뒀지만, 실제로 될지는 첫 실행에서 확인이 필요합니다.
- **채널 구조 변경**: 카카오가 페이지 구조(class명 등)를 바꾸면 스크래핑이 깨질 수 있습니다. 이 경우 `scripts/scrape_menu.py`의 셀렉터를 다시 진단해야 합니다.
- **API 키 비용**: 매주 자동 실행되므로, API 사용량이 예상 밖으로 쌓이지 않는지 가끔 console.anthropic.com에서 확인하시는 걸 권장합니다.

## 실행 후 결과 공유해주세요

첫 수동 실행 후 성공/실패 여부와 (가능하면) Artifacts 안의 `menu_final.json` 내용을 공유해주시면,
OCR 품질이나 사이트 디자인을 다음 단계에서 다듬어드리겠습니다.
