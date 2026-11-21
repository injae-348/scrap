import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import type { Plugin } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'
import { defineConfig } from 'vitest/config'
import { BUILD_ID_ENV, BUILD_ID_META, resolveBuildId } from './src/lib/buildId.ts'

// ⚠️ VITE_ 로 시작하는 환경변수는 빌드 결과물(브라우저 번들, 공개 이미지)에 그대로 들어간다.
//    공개해도 되는 값만 쓴다. 비밀값(API 키, 세션 비밀값, 가입 토큰)은 절대 VITE_ 로 넘기지 않는다.
//    쓰는 VITE_ 변수는 VITE_APP_BUILD_ID(빌드 식별자, 커밋 SHA 같은 공개 값) 하나뿐이다.
//    허용 목록은 src/envAllowlist.test.ts 가 검사한다 (이 파일의 process.env 읽기 포함. 새 이름은 거기에 이유와 함께 추가).

const isTest = !!process.env.VITEST

// 빌드 식별자를 index.html <head>에 meta로 넣는다 (src/lib/buildId.ts 설명 참고).
// 배포마다 값이 바뀌면 index.html 내용 → sw.js 미리 캐시 revision → sw.js 가 바뀌어 "새 버전" 안내가 뜬다.
// 빌드 뒤 scripts/check-build-id.mjs 가 dist 에서 이 연결을 확인한다 (npm run build 에 포함).
const buildId = resolveBuildId(process.env[BUILD_ID_ENV])

function buildIdPlugin(): Plugin {
  return {
    name: 'app-build-id',
    transformIndexHtml: () => [{ tag: 'meta', attrs: { name: BUILD_ID_META, content: buildId }, injectTo: 'head' }],
  }
}

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    buildIdPlugin(),
    !isTest &&
      VitePWA({
        // 새 버전은 자동으로 적용하지 않고 "새로고침" 안내를 띄운다 (작성 중인 내용 보호).
        registerType: 'prompt',
        // 등록 코드는 src/components/UpdatePrompt.tsx 에서 virtual:pwa-register 로 import 한다.
        // 운영 CSP(script-src 'self')에 맞게 index.html 에 인라인 스크립트를 넣지 않는다.
        injectRegister: false,
        // public/ 의 아이콘은 아래 globPatterns 로 미리 캐시한다 (중복 등록하지 않게 끈다)
        includeAssets: [],
        includeManifestIcons: false,
        manifest: {
          id: '/',
          name: '스크랩',
          short_name: '스크랩',
          description: '혼자 쓰는 북마크·스크랩 관리',
          lang: 'ko',
          dir: 'ltr',
          start_url: '/',
          scope: '/',
          display: 'standalone',
          orientation: 'any',
          theme_color: '#ffffff',
          background_color: '#ffffff',
          icons: [
            { src: '/pwa-192x192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
            { src: '/pwa-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
            { src: '/maskable-icon-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
          ],
        },
        workbox: {
          // 정적 자산만 미리 캐시한다. /api/* 는 어떤 경우에도 캐시하지 않는다
          // (runtimeCaching 없음 → 서비스워커가 /api 요청에 끼어들지 않고 브라우저가 바로 서버로 보낸다).
          globPatterns: ['**/*.{js,css,html,svg,png,ico}'],
          navigateFallback: '/index.html',
          navigateFallbackDenylist: [/^\/api\//],
          cleanupOutdatedCaches: true,
          clientsClaim: false,
          skipWaiting: false,
        },
        devOptions: { enabled: false },
      }),
  ],
  server: {
    // 로컬 개발: /api 를 로컬 백엔드로 넘긴다 (같은 출처처럼 보이므로 쿠키가 그대로 오간다).
    // 백엔드는 COOKIE_SECURE=0, ALLOWED_ORIGINS=http://localhost:5173 으로 띄운다 (backend/README.md).
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
  },
})
