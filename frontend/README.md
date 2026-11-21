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

## 검사
CI `frontend` 잡이 같은 순서로 실행한다. CI는 빌드 뒤 `dist/`에 비밀값 형태가 없는지도 검사한다 (`.github/workflows/ci.yml`의 "Scan build output for secrets", CI 전용 단계).
```sh
npm run lint       # ESLint (렌더링 안전·브라우저 저장소 금지 규칙 포함)
npm run typecheck
npm test           # vitest (jsdom): 마크다운 렌더링 안전, URL 표시, API 오류 처리, 화면 동작, 소스 검사
npm run build      # dist/ + 서비스워커(sw.js) + manifest, 마지막에 빌드 식별자 검사(scripts/check-build-id.mjs)
```
- `npm run check:build-id` — 빌드 식별자만 다르게 두 번 빌드해(임시 폴더) `sw.js`의 index.html revision과 `sw.js` 내용이 달라지는지 확인한다.
- `npm audit` — 개발 의존성 포함 0건을 유지한다. `package.json`의 `overrides`는 `workbox-build`(vite-plugin-pwa 빌드 도구)가 쓰는 `glob`을 취약점이 고쳐진 버전으로 올린다. vite-plugin-pwa·workbox-build를 올릴 때 이 고정이 아직 필요한지 다시 본다 (`npm ls glob`).

## 구조
- `src/api/` — API 호출은 모두 여기 (`http.ts`의 `request`: 같은 출처 `/api`, `credentials: 'include'`). 화면 분기는 `error.code`로 한다.
- `src/hooks/queries.ts` — TanStack Query 훅. 401 `unauthorized`(이 코드일 때만)는 로그인 필요 상태로 바꾸고 `AppLayout`이 로그인 화면으로 보낸다.
- `src/pages/`, `src/components/` — 화면. 모바일(~767px) 하단 탭바 + "+", 데스크톱(1024px~) 사이드바 + 목록 + 상세 패널.

## 규칙
- **`VITE_` 환경변수는 공개 값 전용.** `VITE_`로 시작하는 값은 빌드 결과물(브라우저 번들, 공개 GHCR 이미지)에 그대로 들어간다. API 키·세션 비밀값·가입 토큰 같은 비밀값은 절대 `VITE_`로 넘기지 않는다. 쓰는 변수는 `VITE_APP_BUILD_ID`(빌드 식별자) 하나뿐이고, 허용 목록은 `src/envAllowlist.test.ts`가 검사한다 (새 변수는 거기에 공개해도 되는 이유와 함께 추가).
- 화면 문구·코드에 서버 비밀값 변수의 "이름=값" 형태를 넣지 않는다 (CI가 `dist/`에서 이 형태를 비밀값으로 잡는다).
- 인증 토큰은 브라우저 저장소(localStorage 등)에 두지 않는다. 세션은 서버가 설정하는 HttpOnly 쿠키뿐이다.
- 렌더링 안전: 제목·메모·URL에 HTML 삽입 API를 쓰지 않는다. 메모 마크다운은 원시 HTML을 렌더링하지 않고(`skipHtml`), 링크는 http/https만, 이미지는 `<img>` 대신 링크로 보여 준다 (`src/components/MarkdownRenderer.tsx`, 테스트 `MarkdownRenderer.test.tsx`).
- AI가 제안한 값은 입력칸에만 채우고, 저장은 사용자가 "저장"을 눌러야 한다.

## PWA
- `vite.config.ts`의 `VitePWA`: `registerType: 'prompt'` — 새 버전이 있으면 "새로고침" 안내만 띄우고 자동으로 새로고침하지 않는다 (작성 중인 내용 보호). 등록은 `src/components/UpdatePrompt.tsx`가 `virtual:pwa-register`로 한다 (index.html에 인라인 스크립트 없음, 운영 CSP `script-src 'self'`).
- 서비스워커는 빌드된 정적 자산만 미리 캐시한다. `/api/*`는 캐시하지 않는다 (`navigateFallbackDenylist`, 런타임 캐시 없음).
- **빌드 식별자**: 빌드 때 `VITE_APP_BUILD_ID`(커밋 SHA 같은 공개 값, 영문·숫자·`.`·`_`·`-` 64자 이하)를 주면 index.html `<head>`에 `<meta name="app-build" content="…">`로 들어간다. 없으면 빌드 시각(`local-YYYYMMDDTHHMMSSZ`)을 쓴다. 배포마다 값이 바뀌므로 앱 코드가 같은 재배포에도 미리 캐시의 index.html revision → `sw.js`가 바뀌어 "새 버전이 있어요" 안내가 뜬다. JS 번들에는 넣지 않는다(같은 코드면 JS 파일이 그대로). 지금 실행 중인 빌드는 설정 화면 맨 아래 "앱 빌드"에서 본다 (커밋 SHA는 앞 7자).
- 아이콘은 `scripts/generate-icons.mjs`(외부 의존성 없음)로 만든다: `npm run icons` → `public/`의 PNG·SVG를 다시 쓴다.
