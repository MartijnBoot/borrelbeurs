import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // `pnpm dev` only: the page comes from Vite, everything else from the app
  // (`uvicorn ... --port 8000`). The built bundle is served by the app itself,
  // same origin, so production has no proxy.
  server: {
    proxy: {
      '/theme.css': 'http://127.0.0.1:8000',
      // Uploaded images (Phase 6 PD10): numeric ids only; Vite's own `/assets/*.js` stay local.
      '^/assets/\\d+$': 'http://127.0.0.1:8000',
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
    // Under Vitest only: the theme editor's test reads the server's own token
    // manifest, `../app/runtime/theme.py` (Phase 6 AC29). `pnpm dev` keeps
    // Vite's default, which serves nothing outside `web/`.
    ...(mode === 'test' ? { fs: { allow: ['.', '../app/runtime'] } } : {}),
  },
  // Tests run under node by default; a test that needs a DOM opts in with a
  // per-file `// @vitest-environment jsdom` comment.
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
  },
}))
