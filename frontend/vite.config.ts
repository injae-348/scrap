import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// PWA(vite-plugin-pwa)는 Phase 6에서 추가한다.
export default defineConfig({
  plugins: [react(), tailwindcss()],
})
