# frontend

React + Vite + TypeScript, Tailwind CSS, TanStack Query, vite-plugin-pwa. API 계약은 `docs/API.md`.

## 로컬 개발
1. 백엔드를 로컬에서 띄운다 (`backend/README.md`의 "로컬 실행": `COOKIE_SECURE=0`, `ALLOWED_ORIGINS=http://localhost:5173`, `SITE_DOMAIN`은 넣지 않음).
2. 프론트:
   ```sh
   npm ci
   npm run dev        # http://localhost:5173 — /api 는 http://127.0.0.1:8000 으로 프록시 (vite.config.ts)
   ```
3. 브라우저에서 `http://localhost:5173`을 연다 (`127.0.0.1:5173`으로 열면 허용 출처가 달라 쓰기 요청이 403 `origin_mismatch`).
   사용자가 없으면 가입 화면이 나온다. 가입 토큰은 백엔드를 띄울 때 정한 값이다.

## 검사 (CI와 동일)
```sh
npm run lint
npm run typecheck
npm test           # vitest (jsdom): 마크다운 렌더링 안전, URL 표시, API 오류 처리, 소스 검사
npm run build      # dist/ + 서비스워커(sw.js) + manifest
```

## 구조
- `src/api/` — API 호출은 모두 여기 (`http.ts`의 `request`: 같은 출처 `/api`, `credentials: 'include'`). 화면 분기는 `error.code`로 한다.
- `src/hooks/queries.ts` — TanStack Query 훅. 401 `unauthorized`(이 코드일 때만)는 로그인 필요 상태로 바꾸고 `AppLayout`이 로그인 화면으로 보낸다.
- `src/pages/`, `src/components/` — 화면. 모바일(~767px) 하단 탭바 + "+", 데스크톱(1024px~) 사이드바 + 목록 + 상세 패널.

## 규칙
- **`VITE_` 환경변수는 공개 값 전용.** `VITE_`로 시작하는 값은 빌드 결과물(브라우저 번들, 공개 GHCR 이미지)에 그대로 들어간다. API 키·세션 비밀값·가입 토큰 같은 비밀값은 절대 `VITE_`로 넘기지 않는다. 지금은 `VITE_` 변수를 쓰지 않는다.
- 화면 문구·코드에 서버 비밀값 변수의 "이름=값" 형태를 넣지 않는다 (CI가 `dist/`에서 이 형태를 비밀값으로 잡는다).
- 인증 토큰은 브라우저 저장소(localStorage 등)에 두지 않는다. 세션은 서버가 설정하는 HttpOnly 쿠키뿐이다.
- 렌더링 안전: 제목·메모·URL에 HTML 삽입 API를 쓰지 않는다. 메모 마크다운은 원시 HTML을 렌더링하지 않고(`skipHtml`), 링크는 http/https만, 이미지는 `<img>` 대신 링크로 보여 준다 (`src/components/MarkdownRenderer.tsx`, 테스트 `MarkdownRenderer.test.tsx`).
- AI가 제안한 값은 입력칸에만 채우고, 저장은 사용자가 "저장"을 눌러야 한다.

## PWA
- `vite.config.ts`의 `VitePWA`: `registerType: 'prompt'` — 새 버전이 있으면 "새로고침" 안내만 띄우고 자동으로 새로고침하지 않는다 (작성 중인 내용 보호). 등록은 `src/components/UpdatePrompt.tsx`가 `virtual:pwa-register`로 한다 (index.html에 인라인 스크립트 없음, 운영 CSP `script-src 'self'`).
- 서비스워커는 빌드된 정적 자산만 미리 캐시한다. `/api/*`는 캐시하지 않는다 (`navigateFallbackDenylist`, 런타임 캐시 없음).
- 아이콘은 `scripts/generate-icons.mjs`(외부 의존성 없음)로 만든다: `npm run icons` → `public/`의 PNG·SVG를 다시 쓴다.
