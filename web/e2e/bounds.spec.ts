/**
 * Price bounds on the Prijsstap grid, in the browser, against the real server
 * (B-07 T12: AC4, AC6, AC10).
 *
 * On a draft, Bier is added at 1,50 / 2,00 / 3,10 on the first borrel's 0,10
 * step. Prijsstap 0,25 asks first, listing "Maximumprijs 3,10 → 3,00"; after
 * "Opslaan" and a reload the row reads 3,00. Then a typed Minimumprijs of 1,60
 * is refused under the field and nothing is stored. The spec starts its own
 * `serve.py --empty` (as `profiles.spec.ts`), so the shared server's live run is
 * not in the way.
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
  server = await startServer('bounds', ['--empty'])
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
const bier = (page: Page) =>
  section(page, 'Min/Max/Startprijs').getByRole('group', { name: 'Bier', exact: true })

test('a Prijsstap change moves a bound inward, and an off-grid bound is refused', async ({
  page,
}) => {
  test.setTimeout(150_000)
  await login(page, adminKey)
  await page.goto('/settings')

  // 1. A borrel.
  const borrel = section(page, 'Borrel')
  await borrel.getByLabel('Naam').fill('Grenzen')
  await borrel.getByRole('button', { name: 'Nieuwe borrel' }).click()
  await expect(borrel.getByText('Grenzen')).toBeVisible()

  // 2. Bier at 1,50 / 2,00 / 3,10.
  const add = section(page, 'Drankjes beheren').getByRole('form', { name: 'Drankje toevoegen' })
  await add.getByLabel('Naam').fill('Bier')
  await add.getByLabel('Minimumprijs (€)', { exact: true }).fill('1,50')
  await add.getByLabel('Startprijs (€)', { exact: true }).fill('2,00')
  await add.getByLabel('Maximumprijs (€)', { exact: true }).fill('3,10')
  await add.getByRole('button', { name: 'Toevoegen' }).click()
  await expect(bier(page).getByLabel('Maximumprijs (€)', { exact: true })).toHaveValue('3,10')

  // 3. Prijsstap 0,10 -> 0,25: the dialog lists the moving bound (AC10).
  const global = section(page, 'Globale instellingen')
  await expect(global.getByLabel('Prijsstap (€)', { exact: true })).toHaveValue('0,1')
  await global.getByLabel('Prijsstap (€)', { exact: true }).fill('0,25')
  await global.getByRole('button', { name: 'Opslaan instellingen' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Prijsstap 0,25 opslaan? Deze grenzen schuiven mee:')
  await expect(dialog.getByRole('listitem')).toHaveText(['Bier: Maximumprijs 3,10 → 3,00'])

  // 4. "Opslaan", then a reload: the bound moved (AC6).
  await dialog.getByRole('button', { name: 'Opslaan' }).click()
  await expect(page.getByText('Opgeslagen', { exact: true })).toBeVisible()
  await page.reload()
  await expect(bier(page).getByLabel('Maximumprijs (€)', { exact: true })).toHaveValue('3,00')
  await expect(bier(page).getByLabel('Minimumprijs (€)', { exact: true })).toHaveValue('1,50')

  // 5. Minimumprijs 1,60 is off the 0,25 grid: refused, nothing stored (AC4).
  await bier(page).getByLabel('Minimumprijs (€)', { exact: true }).fill('1,60')
  await bier(page).getByRole('button', { name: 'Opslaan' }).click()
  await expect(
    bier(page).getByText('Moet een veelvoud van de Prijsstap (0,25) zijn: 1,50 of 1,75.'),
  ).toBeVisible()
  await page.reload()
  await expect(bier(page).getByLabel('Minimumprijs (€)', { exact: true })).toHaveValue('1,50')
})
