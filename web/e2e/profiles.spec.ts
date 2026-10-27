/**
 * Setting profiles, in the browser, against the real server (B-04 T12: AC1, AC7,
 * AC11, AC12, AC16, AC19, AC20).
 *
 * On a draft, Sterkte ruis and Kaarsbreedte are changed and saved as "Wilde
 * beurs"; set back; loaded again; then the draft is deleted and "Nieuwe borrel"
 * with the profile brings the values back. The spec starts its own `serve.py
 * --empty` (as `admin.spec.ts`), so the shared server's live run is not in the way.
 */
import { test as base, expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { startServer, STOP_HOOK_TIMEOUT_MS, stopServer, type ServerProcess } from './serverProcess'

let server: ServerProcess
let baseUrl: string
let adminKey: string

const test = base.extend({
  // eslint-disable-next-line no-empty-pattern -- Playwright requires the destructuring
  baseURL: async ({}, provide) => provide(baseUrl),
})

test.describe.configure({ mode: 'serial' })

test.beforeAll(async () => {
  test.setTimeout(150_000)
  server = await startServer('profiles', ['--empty'])
  const written = JSON.parse(readFileSync(server.out, 'utf-8')) as {
    base_url: string
    keys: { admin: string }
  }
  baseUrl = written.base_url
  adminKey = written.keys.admin
})

test.afterAll(async () => {
  test.setTimeout(STOP_HOOK_TIMEOUT_MS)
  await stopServer(server?.child)
})

async function login(page: Page, key: string): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Toegangscode').fill(key)
  await page.getByRole('button', { name: 'Inloggen' }).click()
  await page.waitForURL((url) => url.pathname !== '/login')
}

const section = (page: Page, name: string) => page.getByRole('region', { name, exact: true })

/** Sterkte ruis and Kaarsbreedte in Globale instellingen, then "Opslaan instellingen". */
async function setNoise(page: Page, sigma: string, candle: string): Promise<void> {
  const global = section(page, 'Globale instellingen')
  await global.getByRole('textbox', { name: 'Sterkte ruis' }).fill(sigma)
  await global.getByRole('textbox', { name: 'Kaarsbreedte (sec)' }).fill(candle)
  await global.getByRole('button', { name: 'Opslaan instellingen' }).click()
  // `exact`: a profile row's "opgeslagen" would match the substring.
  await expect(page.getByText('Opgeslagen', { exact: true })).toBeVisible()
}

async function expectNoise(page: Page, sigma: string, candle: string): Promise<void> {
  const global = section(page, 'Globale instellingen')
  await expect(global.getByRole('textbox', { name: 'Sterkte ruis' })).toHaveValue(sigma)
  await expect(global.getByRole('textbox', { name: 'Kaarsbreedte (sec)' })).toHaveValue(candle)
}

test('a profile saved from a draft is loaded back and starts a new borrel', async ({ page }) => {
  test.setTimeout(150_000)
  await login(page, adminKey)
  await page.goto('/settings')

  // 1. A draft.
  const borrel = section(page, 'Borrel')
  await borrel.getByLabel('Naam').fill('Proef')
  await borrel.getByRole('button', { name: 'Nieuwe borrel' }).click()
  await expect(borrel.getByText('Proef')).toBeVisible()

  // 2. Tuned wild.
  await expectNoise(page, '0,18', '60')
  await setNoise(page, '0,5', '30')

  // 3. Saved as "Wilde beurs" (AC1, AC19, AC20).
  const profiles = section(page, 'Profielen')
  await expect(
    page.getByRole('heading', { level: 2, name: 'Profielen' }).locator('svg'),
  ).toHaveCount(1)
  await expect(profiles.getByText('Nog geen profielen')).toBeVisible()
  await profiles.getByLabel('Naam').fill('Wilde beurs')
  await profiles.getByRole('button', { name: 'Opslaan als profiel' }).click()
  const row = profiles.getByRole('listitem')
  await expect(row).toHaveCount(1)
  await expect(row.locator('span').first()).toHaveText(
    /^Wilde beurs · opgeslagen \d{1,2} [a-z]{3} \d{2}:\d{2} · uit 'Proef'$/,
  )

  // 4. Set back to the defaults.
  await setNoise(page, '0,18', '60')

  // 5. Loaded again, without a page reload (AC11, AC12, AC16).
  await profiles.getByLabel('Profiel laden').selectOption({ label: 'Wilde beurs' })
  await profiles.getByRole('button', { name: 'Laden' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText(
    "Profiel 'Wilde beurs' laden op 'Proef'? Dit vervangt de instellingen van deze borrel.",
  )
  await dialog.getByRole('button', { name: 'Laden' }).click()
  await expect(dialog).toHaveCount(0)
  await expectNoise(page, '0,5', '30')

  // 6. The draft deleted on /analytics (Phase 7 SD3).
  await page.goto('/analytics')
  const run = page.getByRole('row', { name: /^Proef\b/ })
  await run.getByRole('button', { name: 'Verwijderen' }).click()
  await page.getByLabel("Typ de naam 'Proef' om te bevestigen").fill('Proef')
  await page.getByRole('button', { name: 'Verwijderen bevestigen' }).click()
  await expect(run).toHaveCount(0)

  // 7. "Nieuwe borrel" with the profile brings the values back (AC7).
  await page.goto('/settings')
  await borrel.getByLabel('Naam').fill('Proef 2')
  await borrel.getByLabel('Profiel').selectOption({ label: 'Wilde beurs' })
  await borrel.getByRole('button', { name: 'Nieuwe borrel' }).click()
  await expect(borrel.getByText('Proef 2')).toBeVisible()
  await expectNoise(page, '0,5', '30')
})
