# Tailwind CSS 정식 빌드 안내

`scripts/generate_site.py`가 만드는 페이지는 더 이상 Tailwind Play CDN
(`cdn.tailwindcss.com`)을 쓰지 않습니다. 대신 이 폴더에서 미리 빌드한
`../assets/styles.css`를 정적 파일로 불러옵니다.

## 언제 다시 빌드해야 하나요?
`scripts/generate_site.py` 안에서 **새로운 Tailwind 클래스 이름을 추가/변경**했을 때만
다시 빌드하면 됩니다. 메뉴 데이터(음식 이름 등)만 바뀌는 평소 자동 업데이트에는
전혀 영향이 없습니다 — 그 경우엔 이 폴더를 건드릴 필요가 없습니다.

## 재빌드 방법
```bash
cd tailwind
npm install
npm run build
```
`assets/styles.css`가 새로 생성됩니다. 이 파일을 커밋하면 다음 배포부터 반영됩니다.
