/**
 * End-to-end tests against the real app (SD28, PD14): global setup starts
 * `tests/integration/realapp/serve.py` -- a scratch database on the compose
 * `db`, v1's live run, minted keys, `python -m app.main` serving the built
 * bundle -- and global teardown stops it. Chromium only, one worker: one real
 * server, one advisory lock. Run after `pnpm build`; `scripts/check.sh` does.
 */
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  reporter: 'list',
  outputDir: 'test-results',
  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',
  use: {
    screenshot: 'only-on-failure',
    trace: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
