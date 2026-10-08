/**
 * An admin builds a borrel from an empty database, in the browser, against the
 * real server (Phase 6 T38: AC23, AC24, AC25, AC30, AC35, AC39, AC41; PD15).
 *
 * The spec starts its own `serve.py --empty` beside the shared server -- its own
 * scratch database, so its own advisory lock -- since the shared one's v1 run
 * is live and go-live would be refused. Only the CLI-minted admin key exists;
 * the display and bar keys are read from the one-time display.
 */
import { test as base, expect, type Browser, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { startServer, stopServer, type ServerProcess } from './serverProcess'

const TILE = '[class^="_tile_"]' // see board.spec.ts
const DRINK = /^\+1 /
const CUSTOM_BG = '#123456'
const DRINKS = [
  ['Bier', '1,00', '2,50', '5,00'],
  ['Wijn', '1,50', '3,00', '6,00'],
  ['Fris', '0,50', '1,50', '3,00'],
] as const

// A 1×1 PNG: the logo the test uploads.
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
)

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
  server = await startServer('admin', ['--empty'])
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

async function login(page: Page, key: string): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Toegangscode').fill(key)
  await page.getByRole('button', { name: 'Inloggen' }).click()
  await page.waitForURL((url) => url.pathname !== '/login')
}

async function signedIn(browser: Browser, key: string): Promise<Page> {
  const context = await browser.newContext({ baseURL: baseUrl })
  const page = await context.newPage()
  await login(page, key)
  return page
}

const section = (page: Page, name: string) => page.getByRole('region', { name, exact: true })

/** "Nieuwe sleutel" for `role`; the key read from the one-time display, then closed. */
async function createKey(page: Page, role: 'Scherm' | 'Bar', label: string): Promise<string> {
  const keys = section(page, '🔑 Toegangssleutels')
  await keys.getByLabel('Rol').selectOption({ label: role })
  await keys.getByLabel('Label').fill(label)
  await keys.getByRole('button', { name: 'Nieuwe sleutel' }).click()
  await expect(keys.getByText('Wordt maar één keer getoond')).toBeVisible()
  const key = (await keys.locator('code').textContent()) ?? ''
  expect(key).toMatch(/^bb_/)
  await keys.getByRole('button', { name: 'Sluiten' }).click()
  await expect(keys.locator('code')).toHaveCount(0)
  return key
}

test('an admin builds a borrel from nothing, and every screen follows live', async ({
  page,
  browser,
}) => {
  test.setTimeout(150_000)
  await login(page, adminKey)

  // `/` renders without a page error (AC41).
  const errors: Error[] = []
  page.on('pageerror', (error) => errors.push(error))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Status' })).toBeVisible()
  await expect(page.getByText('Geen actieve borrel')).toBeVisible()
  expect(errors).toEqual([])

  await page.goto('/settings')

  // 1. A borrel.
  const borrel = section(page, 'Borrel')
  await borrel.getByLabel('Naam').fill('Vrijmibo')
  await borrel.getByRole('button', { name: 'Nieuwe borrel' }).click()
  await expect(borrel.getByText('Vrijmibo')).toBeVisible()

  // 2. Three drinks.
  const add = section(page, '🥤 Drankjes beheren').getByRole('form', { name: 'Drankje toevoegen' })
  for (const [name, min, start, max] of DRINKS) {
    await add.getByLabel('Naam').fill(name)
    await add.getByLabel('Min').fill(min)
    await add.getByLabel('Start').fill(start)
    await add.getByLabel('Max').fill(max)
    await add.getByRole('button', { name: 'Toevoegen' }).click()
    await expect(
      section(page, '🥤 Drankjes beheren').getByRole('group', { name, exact: true }),
    ).toBeVisible()
  }

  // 3. Params.
  const global = section(page, '⚙️ Globale instellingen')
  await global.getByLabel('🧱 Tickgrootte').fill('0,05')
  await global.getByRole('button', { name: '💾 Opslaan instellingen' }).click()
  await expect(page.getByText('Opgeslagen')).toBeVisible()

  // 4. A preset, then a custom theme.
  const colours = section(page, '🎨 Kleurenschema')
  await colours.getByRole('button', { name: 'Rood', exact: true }).click()
  await colours.getByLabel('--bg', { exact: true }).fill(CUSTOM_BG)
  await colours.getByRole('button', { name: 'Opslaan', exact: true }).click()
  await expect
    .poll(() =>
      page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--bg')),
    )
    .toBe(CUSTOM_BG)

  // 5. A logo; removing it asks first, and Annuleren keeps it (AC39).
  const images = section(page, '🖼️ Afbeeldingen')
  const logo = images.getByRole('group', { name: 'Logo', exact: true })
  await logo.getByLabel('Logo kiezen').setInputFiles({
    name: 'logo.png',
    mimeType: 'image/png',
    buffer: PNG,
  })
  await expect(logo.getByRole('img', { name: 'Logo' })).toHaveAttribute('src', /^\/assets\/\d+$/)
  await logo.getByRole('button', { name: 'Verwijderen' }).click()
  await page.getByRole('button', { name: 'Annuleren' }).click()
  await expect(logo.getByRole('img', { name: 'Logo' })).toBeVisible()

  // 6. A display key and a bar key, read from the one-time display.
  const displayKey = await createKey(page, 'Scherm', 'Koersbord')
  const barKey = await createKey(page, 'Bar', 'Tap 1')

  // Revoking asks first; Annuleren revokes nothing (AC39).
  const keys = section(page, '🔑 Toegangssleutels')
  await keys
    .getByRole('row', { name: /Koersbord/ })
    .getByRole('button', { name: 'Intrekken' })
    .click()
  await page.getByRole('button', { name: 'Annuleren' }).click()
  await expect(keys.getByRole('row', { name: /Koersbord/ })).toContainText('Actief')

  // The board is open before go-live, so it must follow without a reload (AC25).
  const display = await signedIn(browser, displayKey)
  await expect(display).toHaveURL(/\/koers$/)
  await expect(display.getByText('Geen actieve borrel')).toBeVisible()

  // 7. Go live; Annuleren first (AC39).
  await borrel.getByRole('button', { name: 'Live zetten' }).click()
  await page.getByRole('button', { name: 'Annuleren' }).click()
  await expect(borrel.getByText('Concept')).toBeVisible()
  await borrel.getByRole('button', { name: 'Live zetten' }).click()
  await page.getByRole('button', { name: 'Bevestigen' }).click()
  await expect(borrel.getByText('Live', { exact: true })).toBeVisible()

  // The display: three tiles, the custom --bg and the logo, with no reload (AC24, AC30, AC35).
  await expect(display.locator(TILE)).toHaveCount(3)
  const rootVar = (name: string) =>
    display.evaluate((n) => getComputedStyle(document.documentElement).getPropertyValue(n), name)
  expect(await rootVar('--bg')).toBe(CUSTOM_BG)
  expect(await rootVar('--img-logo')).toMatch(/^url\("\/assets\/\d+"\)$/)

  // The bar: one button per drink; the admin removes one and its button goes (AC23).
  const bar = await signedIn(browser, barKey)
  await expect(bar.getByRole('button', { name: DRINK })).toHaveCount(3)
  const wijn = section(page, '🥤 Drankjes beheren').getByRole('group', {
    name: 'Wijn',
    exact: true,
  })
  await wijn.getByRole('button', { name: 'Verwijderen' }).click()
  await expect(page.getByRole('dialog', { name: "'Wijn' verwijderen?" })).toBeVisible()
  await page.getByRole('button', { name: 'Annuleren' }).click()
  await expect(bar.getByRole('button', { name: DRINK })).toHaveCount(3)
  await wijn.getByRole('button', { name: 'Verwijderen' }).click()
  await page.getByRole('button', { name: 'Bevestigen' }).click()
  await expect(bar.getByRole('button', { name: DRINK })).toHaveCount(2)
  await expect(bar.getByRole('button', { name: /Wijn/ })).toHaveCount(0)
  await expect(display.locator(TILE)).toHaveCount(2)

  // `/` shows the live run, still without a page error (AC41).
  await page.goto('/')
  await expect(page.getByText(/Vrijmibo \(live\)/)).toBeVisible()
  expect(errors).toEqual([])
})
