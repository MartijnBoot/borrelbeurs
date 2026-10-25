/**
 * Two borrels, closed, compared, exported and one deleted -- in the browser,
 * against the real server (Phase 7 T23: AC3 end to end, AC33, AC36).
 *
 * Like `admin.spec.ts` (Phase 6 PD15) the spec starts its own `serve.py
 * --empty`: own scratch database, own advisory lock, only an admin key. The bar
 * and display keys come from the one-time display. Every request any of the
 * three contexts makes must stay on the app's origin (AC36): one that does not
 * is aborted and fails the test.
 */
import {
  test as base,
  expect,
  type Browser,
  type BrowserContext,
  type Page,
} from '@playwright/test'
import { readFileSync, statSync } from 'node:fs'
import { startServer, stopServer, type ServerProcess } from './serverProcess'

const TILE = '[class^="_tile_"]' // see board.spec.ts
const DRINKS = [
  ['Bier', '1,00', '2,50', '5,00'],
  ['Wijn', '1,50', '3,00', '6,00'],
  ['Fris', '0,50', '1,50', '3,00'],
] as const

let server: ServerProcess
let baseUrl: string
let adminKey: string
const offOrigin: string[] = []

const test = base.extend({
  // eslint-disable-next-line no-empty-pattern -- Playwright requires the destructuring
  baseURL: async ({}, provide) => provide(baseUrl),
})

test.describe.configure({ mode: 'serial' })

test.beforeAll(async () => {
  test.setTimeout(150_000)
  server = await startServer('analytics', ['--empty'])
  const written = JSON.parse(readFileSync(server.out, 'utf-8')) as {
    base_url: string
    keys: { admin: string }
  }
  baseUrl = written.base_url
  adminKey = written.keys.admin
})

test.afterAll(async () => {
  await stopServer(server?.child)
})

/** AC36: no request leaves the origin; one that tries is recorded and aborted. */
async function sameOriginOnly(context: BrowserContext): Promise<void> {
  const origin = new URL(baseUrl).origin
  await context.route('**/*', (route) => {
    const url = new URL(route.request().url())
    if (url.origin === origin) return route.continue()
    offOrigin.push(url.href)
    return route.abort()
  })
}

async function login(page: Page, key: string): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Toegangscode').fill(key)
  await page.getByRole('button', { name: 'Inloggen' }).click()
  await page.waitForURL((url) => url.pathname !== '/login')
}

async function signedIn(browser: Browser, key: string): Promise<Page> {
  const context = await browser.newContext({ baseURL: baseUrl })
  await sameOriginOnly(context)
  const page = await context.newPage()
  await login(page, key)
  return page
}

const section = (page: Page, name: string) => page.getByRole('region', { name, exact: true })

async function createKey(page: Page, role: 'Scherm' | 'Bar', label: string): Promise<string> {
  const keys = section(page, 'Toegangssleutels')
  await keys.getByLabel('Rol').selectOption({ label: role })
  await keys.getByLabel('Label').fill(label)
  await keys.getByRole('button', { name: 'Nieuwe sleutel' }).click()
  const key = (await keys.locator('code').textContent()) ?? ''
  expect(key).toMatch(/^bb_/)
  await keys.getByRole('button', { name: 'Sluiten' }).click()
  return key
}

async function addDrink(page: Page, name: string, min: string, start: string, max: string) {
  const drinks = section(page, 'Drankjes beheren')
  const add = drinks.getByRole('form', { name: 'Drankje toevoegen' })
  await add.getByLabel('Naam').fill(name)
  await add.getByLabel('Minimumprijs (€)', { exact: true }).fill(min)
  await add.getByLabel('Startprijs (€)', { exact: true }).fill(start)
  await add.getByLabel('Maximumprijs (€)', { exact: true }).fill(max)
  await add.getByRole('button', { name: 'Toevoegen' }).click()
  await expect(drinks.getByRole('group', { name, exact: true })).toBeVisible()
}

/**
 * A borrel made with "Nieuwe borrel" starts with "Wallet verplicht" on (B-06 SD1). This
 * spec is about analytics, not wallets, so it turns the switch off over the admin API
 * (the page's own session) and its orders book without one.
 */
async function walletOptional(page: Page) {
  const current = await page.request.get('/api/runs/current')
  expect(current.ok()).toBe(true)
  const { run_id: runId } = (await current.json()) as { run_id: number }
  const patched = await page.request.patch(`/api/runs/${runId}/config`, {
    data: { wallet_required: false },
    headers: { Origin: new URL(baseUrl).origin },
  })
  expect(patched.ok()).toBe(true)
}

async function goLive(page: Page) {
  const borrel = section(page, 'Borrel')
  await borrel.getByRole('button', { name: 'Live zetten' }).click()
  await page.getByRole('button', { name: 'Bevestigen' }).click()
  await expect(borrel.getByText('Live', { exact: true })).toBeVisible()
}

async function closeBorrel(page: Page, name: string) {
  const borrel = section(page, 'Borrel')
  await borrel.getByRole('button', { name: 'Borrel afsluiten' }).click()
  await page.getByLabel(`Typ de naam '${name}' om te bevestigen`).fill(name)
  await page.getByRole('button', { name: 'Afsluiten', exact: true }).click()
  await expect(borrel.getByText('Geen borrel')).toBeVisible()
}

/** The bar's first drink into the basket and "Afrekenen", until the server has booked it (201). */
async function order(bar: Page) {
  const button = bar.getByRole('group', { name: 'Drankjes' }).getByRole('button').first()
  await expect(button).toBeEnabled()
  let booked = false
  const listener = (response: {
    url(): string
    status(): number
    request(): { method(): string }
  }) => {
    if (
      response.request().method() === 'POST' &&
      new URL(response.url()).pathname === '/api/orders' &&
      response.status() === 201
    ) {
      booked = true
    }
  }
  bar.on('response', listener)
  await button.click()
  await bar.getByRole('button', { name: /^Afrekenen zonder wallet/ }).click()
  // A price that moved mid-tap asks first (Phase 5 SD9); confirming books it.
  await expect(async () => {
    const dialog = bar.getByRole('dialog')
    if (await dialog.isVisible()) await bar.getByRole('button', { name: 'Bevestigen' }).click()
    expect(booked).toBe(true)
  }).toPass({ timeout: 15_000 })
  bar.off('response', listener)
}

test('two borrels: close, copy, compare, export and delete', async ({ page, browser }) => {
  test.setTimeout(180_000)
  const started = Date.now()
  await sameOriginOnly(page.context())
  await login(page, adminKey)
  await page.goto('/settings')
  const borrel = section(page, 'Borrel')

  // 1. A borrel with three drinks, live.
  await borrel.getByLabel('Naam').fill('Vrijdag')
  await borrel.getByRole('button', { name: 'Nieuwe borrel' }).click()
  await expect(borrel.getByText('Vrijdag')).toBeVisible()
  await walletOptional(page)
  for (const [name, min, start, max] of DRINKS) await addDrink(page, name, min, start, max)
  const displayKey = await createKey(page, 'Scherm', 'Koersbord')
  const barKey = await createKey(page, 'Bar', 'Tap 1')
  await goLive(page)

  // 2. Orders from the bar, a changed bar price, and a drink added live.
  const display = await signedIn(browser, displayKey)
  await expect(display.locator(TILE)).toHaveCount(3)
  const bar = await signedIn(browser, barKey)
  await order(bar)
  await order(bar)
  const bier = section(page, 'Drankjes beheren').getByRole('group', {
    name: 'Bier',
    exact: true,
  })
  await bier.getByLabel('Normale barprijs (€)', { exact: true }).fill('2,75')
  const saved = page.waitForResponse(
    (r) => r.request().method() === 'PATCH' && /\/drinks\/\d+$/.test(new URL(r.url()).pathname),
  )
  await bier.getByRole('button', { name: 'Opslaan' }).click()
  expect((await saved).ok()).toBe(true)
  await order(bar)
  await addDrink(page, 'Cola', '0,50', '2,00', '4,00')
  await expect(display.locator(TILE)).toHaveCount(4)

  // 3. The admin closes it with the typed name; the board says so without a reload.
  await closeBorrel(page, 'Vrijdag')
  await expect(display.getByText('Borrel afgelopen')).toBeVisible()
  await expect(bar.getByText('Geen actieve borrel')).toBeVisible()

  // 4. A second borrel copying the first's drinks: live, an order, closed.
  await borrel.getByLabel('Naam').fill('Zaterdag')
  const copy = borrel.getByLabel('Kopieer drankjes uit')
  await expect(copy.locator('option', { hasText: 'Vrijdag' })).toHaveCount(1)
  await copy.selectOption({ label: 'Vrijdag' })
  await borrel.getByRole('button', { name: 'Nieuwe borrel' }).click()
  await expect(borrel.getByText('Zaterdag')).toBeVisible()
  await walletOptional(page)
  await expect(
    section(page, 'Drankjes beheren').getByRole('group', { name: 'Cola', exact: true }),
  ).toBeVisible()
  await goLive(page)
  await expect(display.locator(TILE)).toHaveCount(4)
  await order(bar)
  await closeBorrel(page, 'Zaterdag')

  // 5. /analytics: compare the two, download Vrijdag's final export, delete Zaterdag.
  await page.goto('/analytics')
  const row = (name: string) => page.getByRole('row', { name: new RegExp(`^${name}\\b`) })
  await expect(row('Vrijdag')).toBeVisible()
  await expect(row('Zaterdag')).toBeVisible()

  await row('Vrijdag').getByRole('radio', { name: 'A' }).check()
  await row('Zaterdag').getByRole('radio', { name: 'B' }).check()
  const compare = page.getByRole('region', { name: 'Vergelijk' })
  await expect(compare.getByRole('row', { name: /^Bier\b/ })).toBeVisible()
  await expect(compare.getByLabel('Drankje')).toBeVisible()

  await row('Vrijdag').getByRole('button', { name: 'Details' }).click()
  const detail = page.getByRole('region', { name: 'Details van Vrijdag' })
  await expect(detail.getByRole('row', { name: /^Bier\b/ })).toBeVisible()
  const link = detail.getByRole('link', { name: 'Download' })
  await expect(link).toBeVisible({ timeout: 60_000 }) // the close queued it; the worker builds
  const [download] = await Promise.all([page.waitForEvent('download'), link.click()])
  expect(download.suggestedFilename()).toMatch(/^borrel-vrijdag-\d{8}-\d{4}\.xlsx$/)
  expect(statSync(await download.path()).size).toBeGreaterThan(0)

  await row('Zaterdag').getByRole('button', { name: 'Verwijderen' }).click()
  await page.getByLabel("Typ de naam 'Zaterdag' om te bevestigen").fill('Zaterdag')
  await page.getByRole('button', { name: 'Verwijderen bevestigen' }).click()
  await expect(row('Zaterdag')).toHaveCount(0)
  await expect(row('Vrijdag')).toBeVisible()

  expect(offOrigin).toEqual([])
  console.log(`analytics.spec: ${((Date.now() - started) / 1000).toFixed(1)} s`)
})
