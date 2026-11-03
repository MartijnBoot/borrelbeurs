/**
 * The organiser role end to end (B-13 T8: the spec's Playwright flows 1-5; AC1, AC5,
 * AC6, AC8, AC10, AC11, AC14; plan PD9).
 *
 * The admin mints an organiser key and a kassa key on Toegangssleutels. The
 * organiser lands on `/`, sets a drink's Maximumprijs and the Prijsstap on
 * Spelopzet, "Rood staan tot" and the sign-up code on Mensen en wallets, and tops
 * up a player's wallet on `/kassa`. Beheer is "Geen toegang", and an engine setting
 * sent from the organiser's own page is 403 and changes nothing the admin sees.
 * The organiser then closes the borrel by its name. The kassa gets Mensen en
 * wallets without Betalen, and no Spelopzet.
 *
 * The spec starts its own `serve.py --empty` (as `wallets.spec.ts`), so closing
 * its borrel leaves the shared server's alone. Every context records and blocks
 * any request that leaves the origin, and the flow asserts none did.
 */
import {
  test as base,
  expect,
  request as http,
  type Browser,
  type BrowserContext,
  type Page,
} from '@playwright/test'
import { readFileSync } from 'node:fs'
import { startServer, STOP_HOOK_TIMEOUT_MS, stopServer, type ServerProcess } from './serverProcess'

const BORREL = 'Organisatieborrel'
const CODE = 'Organisatie2026'
const GROUPED = /^[0-9A-HJKMNP-TV-Z]{3}(-[0-9A-HJKMNP-TV-Z]{3}){2}$/

let server: ServerProcess
let baseUrl: string
let adminKey: string
const foreign: string[] = []

const test = base.extend({
  // eslint-disable-next-line no-empty-pattern -- Playwright requires the destructuring
  baseURL: async ({}, provide) => provide(baseUrl),
})

test.describe.configure({ mode: 'serial' })

test.beforeAll(async () => {
  test.setTimeout(150_000)
  server = await startServer('organiser', ['--empty'])
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

/** A borrel with one drink, live: over HTTP, since making it is not what is tested. */
async function goLive(): Promise<number> {
  const api = await http.newContext({ baseURL: baseUrl, extraHTTPHeaders: { Origin: baseUrl } })
  try {
    expect((await api.post('/api/auth/login', { data: { key: adminKey } })).ok()).toBe(true)
    const run = await api.post('/api/runs', { data: { name: BORREL } })
    expect(run.ok()).toBe(true)
    const { run_id: runId } = (await run.json()) as { run_id: number }
    const drink = { name: 'Bier', p_min_cents: 100, p0_cents: 250, p_max_cents: 500 }
    expect((await api.post(`/api/runs/${runId}/drinks`, { data: drink })).ok()).toBe(true)
    expect((await api.post(`/api/runs/${runId}/go-live`)).ok()).toBe(true)
    return runId
  } finally {
    await api.dispose()
  }
}

/** A context that records and aborts every request leaving the origin. */
async function guarded(browser: Browser): Promise<BrowserContext> {
  const context = await browser.newContext({ baseURL: baseUrl })
  await context.route('**/*', (route) => {
    const url = route.request().url()
    if (new URL(url).origin === new URL(baseUrl).origin) return route.continue()
    foreign.push(url)
    return route.abort()
  })
  return context
}

async function open(browser: Browser, path: string): Promise<Page> {
  const page = await (await guarded(browser)).newPage()
  await page.goto(path)
  return page
}

async function login(page: Page, key: string): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Toegangscode').fill(key)
  await page.getByRole('button', { name: 'Inloggen' }).click()
  await page.waitForURL((url) => url.pathname !== '/login')
}

async function logout(page: Page): Promise<void> {
  await page.getByRole('button', { name: /Menu/ }).click()
  await page.getByRole('menuitem', { name: 'Uitloggen' }).click()
  await page.waitForURL((url) => url.pathname === '/login')
}

const section = (page: Page, name: string) => page.getByRole('region', { name, exact: true })
const dialog = (page: Page) => page.getByRole('dialog')
const bier = (page: Page) =>
  section(page, 'Prijzen').getByRole('group', { name: 'Bier', exact: true })

async function newKey(admin: Page, role: string, label: string): Promise<string> {
  const keys = section(admin, 'Toegangssleutels')
  await keys.getByLabel('Rol').selectOption({ label: role })
  await keys.getByLabel('Label').fill(label)
  await keys.getByRole('button', { name: 'Nieuwe sleutel' }).click()
  await expect(keys.getByText('Wordt maar één keer getoond')).toBeVisible()
  const key = (await keys.locator('code').textContent()) ?? ''
  expect(key).toMatch(GROUPED)
  await keys.getByRole('button', { name: 'Sluiten' }).click()
  return key
}

/** Beheer's two engine settings the refused PATCH names (eta and K), as the admin sees them. */
async function engineValues(admin: Page): Promise<string[]> {
  await admin.goto('/settings/beheer')
  const global = section(admin, 'Globale instellingen')
  const values = []
  for (const name of ['Beweging per bestelling', 'Drukdrempel']) {
    const field = global.getByRole('textbox', { name, exact: true })
    await expect(field).not.toHaveValue('')
    values.push(await field.inputValue())
  }
  return values
}

/** The next `PATCH` to a path matching `path`: its status, once the server answered. */
async function patched(page: Page, path: RegExp, act: () => Promise<void>): Promise<number> {
  const answered = page.waitForResponse(
    (response) =>
      response.request().method() === 'PATCH' && path.test(new URL(response.url()).pathname),
  )
  await act()
  return (await answered).status()
}

test('an organiser sets up, runs the cash desk and closes a borrel; the kassa keeps to its screen', async ({
  browser,
}) => {
  test.setTimeout(240_000)
  const runId = await goLive()

  // 1. The admin makes an "Organisator" key and a "Kassa" key, then logs out (AC1).
  const admin = await open(browser, '/login')
  await login(admin, adminKey)
  const before = await engineValues(admin)
  const organiserKey = await newKey(admin, 'Organisator', 'Organisatie')
  const kassaKey = await newKey(admin, 'Kassa', 'Kassa 1')
  await expect(
    section(admin, 'Toegangssleutels').getByRole('row', { name: /Organisatie/ }),
  ).toContainText('Organisator')
  await logout(admin)

  // 2. The organiser lands on `/` (AC5) ...
  const organiser = await open(browser, '/login')
  await login(organiser, organiserKey)
  await expect(organiser).toHaveURL((url) => url.pathname === '/')

  // ... sets Bier's Maximumprijs and the Prijsstap on Spelopzet,
  await organiser.goto('/settings/spel')
  await bier(organiser).getByLabel('Maximumprijs (€)', { exact: true }).fill('4,50')
  const bound = await patched(organiser, /\/drinks\/\d+$/, () =>
    bier(organiser).getByRole('button', { name: 'Opslaan' }).click(),
  )
  expect(bound).toBe(200)
  const prices = section(organiser, 'Prijzen')
  await prices.getByLabel('Prijsstap (€)', { exact: true }).fill('0,05')
  const step = await patched(organiser, /\/config$/, () =>
    prices.getByRole('button', { name: 'Opslaan prijsstap' }).click(),
  )
  expect(step).toBe(200)
  await organiser.reload()
  await expect(bier(organiser).getByLabel('Maximumprijs (€)', { exact: true })).toHaveValue('4,50')
  await expect(prices.getByLabel('Prijsstap (€)', { exact: true })).toHaveValue('0,05')

  // ... the sign-up code and "Rood staan tot" on Mensen en wallets (AC8),
  await organiser.goto('/settings/wallets')
  const wallets = section(organiser, 'Wallets')
  await wallets.getByRole('textbox', { name: 'Aanmeldcode' }).fill(CODE)
  await wallets.getByRole('button', { name: 'Opslaan' }).first().click()
  await expect(wallets.getByText(`/speler?code=${CODE}`)).toBeVisible()
  const betalen = section(organiser, 'Betalen')
  await betalen.getByRole('textbox', { name: 'Rood staan tot (€)' }).fill('2,50')
  const limit = await patched(organiser, /\/config$/, () =>
    betalen.getByRole('button', { name: 'Opslaan' }).click(),
  )
  expect(limit).toBe(200)
  await organiser.reload()
  await expect(betalen.getByRole('textbox', { name: 'Rood staan tot (€)' })).toHaveValue('2,50')

  // ... and tops up a wallet signed up on /speler, on /kassa (AC14).
  const player = await open(browser, `/speler?code=${CODE}`)
  await player.getByLabel('Naam').fill('Jan')
  await player.getByRole('button', { name: 'Aanmelden' }).click()
  await expect(player.getByRole('heading', { name: 'Jan', exact: true })).toBeVisible()
  const janCode = (await player.getByText(/^[0-9A-Z]{4}-[0-9A-Z]{4}$/).textContent()) ?? ''
  await organiser.goto('/kassa')
  await organiser.getByLabel('Code typen').fill(janCode)
  await organiser.getByRole('button', { name: 'Zoeken' }).click()
  const card = section(organiser, 'Jan')
  await card.getByRole('button', { name: 'Opwaarderen' }).click()
  await dialog(organiser).getByRole('button', { name: 'Opwaarderen' }).click()
  await expect(card.locator('p').getByText(/€\s10,00/)).toBeVisible()
  await expect(player.getByText(/€\s10,00/)).toBeVisible({ timeout: 15_000 })

  // 3. Beheer is "Geen toegang"; an engine setting from the page's own session is 403
  //    (AC6, AC11), and the admin sees Beweging per bestelling and Drukdrempel unchanged.
  await organiser.goto('/settings/beheer')
  await expect(organiser.getByText('Geen toegang')).toBeVisible()
  await expect(organiser).toHaveURL((url) => url.pathname === '/settings/beheer')
  const refused = await organiser.evaluate(
    (path) =>
      fetch(path, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ params: { eta: 0.9, K: 9 } }),
      }).then((r) => r.status),
    `/api/runs/${runId}/config`,
  )
  expect(refused).toBe(403)
  await login(admin, adminKey)
  expect(await engineValues(admin)).toEqual(before)

  // 4. The organiser closes the borrel by its name (AC10).
  await organiser.goto('/settings/spel')
  const borrel = section(organiser, 'Borrel')
  await borrel.getByRole('button', { name: 'Borrel afsluiten' }).click()
  await organiser.getByLabel(`Typ de naam '${BORREL}' om te bevestigen`).fill(BORREL)
  await organiser.getByRole('button', { name: 'Afsluiten', exact: true }).click()
  await expect(borrel.getByText('Geen borrel')).toBeVisible()

  // 5. The kassa: Mensen en wallets without Betalen, and no Spelopzet (AC6, AC8).
  const kassa = await open(browser, '/login')
  await login(kassa, kassaKey)
  await expect(kassa).toHaveURL(/\/kassa$/)
  await kassa.goto('/settings/wallets')
  await expect(section(kassa, 'Wallets')).toBeVisible()
  await expect(section(kassa, 'Betalen')).toHaveCount(0)
  await kassa.goto('/settings/spel')
  await expect(kassa.getByText('Geen toegang')).toBeVisible()

  expect(foreign).toEqual([])
})
