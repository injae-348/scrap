import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { defineConfig } from 'vitest/config'

// ⚠️ VITE_ 로 시작하는 환경변수는 빌드 결과물(브라우저 번들, 공개 이미지)에 그대로 들어간다.
//    공개해도 되는 값만 쓴다. 비밀값(API 키, 세션 비밀값, 가입 토큰)은 절대 VITE_ 로 넘기지 않는다.
//    지금은 VITE_ 변수를 쓰지 않는다.

const isTest = !!process.env.VITEST

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
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
