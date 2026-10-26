/**
 * Player wallets end to end, over the venue path (B-05 T21: AC1, AC3, AC4, AC15,
 * AC17, AC20, AC21, AC26, AC34, AC40, AC41, AC42, AC43; plan PD16).
 *
 * The venue serves plain HTTP on a LAN address, which a browser does not treat as
 * a secure context: no camera, no `crypto.randomUUID`. Chromium maps the made-up
 * host `wallets.test` onto loopback, so the pages run at `http://wallets.test:<port>`
 * -- not secure, as at `http://192.168.8.10` -- while the server is the real one.
 * `OriginGuard` compares `Origin` with `Host`, so the writes pass as at the venue.
 *
 * The spec starts its own `serve.py --empty` (as `profiles.spec.ts`), so the
 * shared server's live run is not in the way. Every context records and blocks
 * any request that leaves the origin, and the flow asserts none did (AC43).
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
import { startServer, stopServer, type ServerProcess } from './serverProcess'

const VENUE_HOST = 'wallets.test'
const EURO_15 = /€\s15,00/

let server: ServerProcess
let loopbackUrl: string
let venueUrl: string
let adminKey: string
let kassaKey: string
const foreign: string[] = []

const test = base.extend({
  // eslint-disable-next-line no-empty-pattern -- Playwright requires the destructuring
  baseURL: async ({}, provide) => provide(venueUrl),
})

test.describe.configure({ mode: 'serial' })
test.use({ launchOptions: { args: [`--host-resolver-rules=MAP ${VENUE_HOST} 127.0.0.1`] } })

test.beforeAll(async () => {
  test.setTimeout(150_000)
  server = await startServer('wallets', ['--empty'])
  const written = JSON.parse(readFileSync(server.out, 'utf-8')) as {
    base_url: string
    keys: { admin: string }
  }
  loopbackUrl = written.base_url
  const venue = new URL(loopbackUrl)
  venue.hostname = VENUE_HOST
  venueUrl = venue.origin
  adminKey = written.keys.admin
})

test.afterAll(async () => {
  await stopServer(server?.child)
})

/** A borrel with one drink, live: over HTTP, since the borrel is not what is tested. */
async function goLive(): Promise<void> {
  const api = await http.newContext({
    baseURL: loopbackUrl,
    extraHTTPHeaders: { Origin: loopbackUrl },
  })
  try {
    expect((await api.post('/api/auth/login', { data: { key: adminKey } })).ok()).toBe(true)
    const run = await api.post('/api/runs', { data: { name: 'Walletborrel' } })
    expect(run.ok()).toBe(true)
    const { run_id: runId } = (await run.json()) as { run_id: number }
    const drink = { name: 'Bier', p_min_cents: 100, p0_cents: 250, p_max_cents: 500 }
    expect((await api.post(`/api/runs/${runId}/drinks`, { data: drink })).ok()).toBe(true)
    expect((await api.post(`/api/runs/${runId}/go-live`)).ok()).toBe(true)
  } finally {
    await api.dispose()
  }
}

/** A context on `baseURL` that records and aborts every request leaving its origin. */
async function guarded(browser: Browser, baseURL: string): Promise<BrowserContext> {
  const context = await browser.newContext({ baseURL })
  const origin = new URL(baseURL).origin
  await context.route('**/*', (route) => {
    const url = route.request().url()
    if (new URL(url).origin === origin) return route.continue()
    foreign.push(url)
    return route.abort()
  })
  return context
}

async function open(browser: Browser, baseURL: string, path: string): Promise<Page> {
  const page = await (await guarded(browser, baseURL)).newPage()
  await page.goto(path)
  return page
}

async function login(page: Page, key: string): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Toegangscode').fill(key)
  await page.getByRole('button', { name: 'Inloggen' }).click()
  await page.waitForURL((url) => url.pathname !== '/login')
}

const section = (page: Page, name: string) => page.getByRole('region', { name, exact: true })
const dialog = (page: Page) => page.getByRole('dialog')

async function shortCode(player: Page): Promise<string> {
  const code = (await player.getByText(/^[0-9A-Z]{4}-[0-9A-Z]{4}$/).textContent()) ?? ''
  expect(code).toMatch(/^[0-9A-Z]{4}-[0-9A-Z]{4}$/)
  return code
}

async function find(kassa: Page, code: string): Promise<void> {
  await kassa.getByLabel('Code typen').fill(code)
  await kassa.getByRole('button', { name: 'Zoeken' }).click()
}

test('a player signs up, the kassa tops up, reverses and moves, admin sees the totals', async ({
  browser,
}) => {
  test.setTimeout(180_000)
  await goLive()

  // 1. Admin, on the venue host: the sign-up code and a kassa key (AC40).
  const admin = await open(browser, venueUrl, '/login')
  expect(await admin.evaluate(() => window.isSecureContext)).toBe(false) // PD16: the venue path
  await login(admin, adminKey)
  await admin.goto('/settings')
  const wallets = section(admin, 'Wallets')
  await wallets.getByRole('textbox', { name: 'Aanmeldcode' }).fill('Borrel2026')
  await wallets.getByRole('button', { name: 'Opslaan' }).first().click()
  await expect(wallets.getByText(`${venueUrl}/speler?code=Borrel2026`)).toBeVisible()

  const keys = section(admin, 'Toegangssleutels')
  await keys.getByLabel('Rol').selectOption({ label: 'Kassa' })
  await keys.getByLabel('Label').fill('Kassa 1')
  await keys.getByRole('button', { name: 'Nieuwe sleutel' }).click()
  await expect(keys.getByText('Wordt maar één keer getoond')).toBeVisible()
  kassaKey = (await keys.locator('code').textContent()) ?? ''
  expect(kassaKey).toMatch(/^bb_/)
  await keys.getByRole('button', { name: 'Sluiten' }).click()

  // 2. Player A at `/`: "Speler", then the poster's link, signs up as "Jan" (AC1, AC3).
  const playerA = await open(browser, venueUrl, '/')
  await expect(playerA.getByRole('link', { name: 'Crew' })).toBeVisible()
  await playerA.getByRole('link', { name: 'Speler' }).click()
  await expect(playerA.getByRole('heading', { name: 'Wallet aanmaken' })).toBeVisible()
  await playerA.goto('/speler?code=Borrel2026')
  await expect(playerA.getByLabel('Aanmeldcode')).toHaveValue('Borrel2026')
  await playerA.getByLabel('Naam').fill('Jan')
  await playerA.getByRole('button', { name: 'Aanmelden' }).click()
  await expect(playerA.getByRole('heading', { name: 'Jan', exact: true })).toBeVisible()
  await expect(playerA.getByText(/€\s0,00/)).toBeVisible()
  await expect(playerA.getByRole('img', { name: 'QR-code' })).toBeVisible()
  const janCode = await shortCode(playerA)

  // 3. Player B tries "jan" and is offered "jan 2" (AC4).
  const playerB = await open(browser, venueUrl, '/speler?code=Borrel2026')
  await playerB.getByLabel('Naam').fill('jan')
  await playerB.getByLabel('Aanmeldcode').focus() // the name check runs on blur
  await expect(playerB.getByText('Die naam is al bezet. Kies een andere:')).toBeVisible()
  await expect(playerB.getByRole('button', { name: 'jan 2' })).toBeVisible()

  // 4. The kassa lands on /kassa, sees no camera, and tops up €15 (AC15, AC20, AC41, AC42).
  const kassa = await open(browser, venueUrl, '/login')
  await login(kassa, kassaKey)
  await expect(kassa).toHaveURL(/\/kassa$/)
  expect(await kassa.evaluate(() => typeof crypto.randomUUID)).toBe('undefined')
  await expect(kassa.getByLabel('Code typen')).toBeVisible()
  await expect(kassa.getByRole('button', { name: 'Camera' })).toHaveCount(0)
  await find(kassa, janCode.toLowerCase())
  const card = section(kassa, 'Jan')
  await expect(card.getByRole('heading', { name: 'Jan', exact: true })).toBeVisible()
  await card.getByRole('button', { name: '€ 5 meer' }).click()
  await card.getByRole('button', { name: 'Opwaarderen' }).click()
  await expect(dialog(kassa)).toContainText(/€\s15,00 opwaarderen voor Jan\?/)
  await dialog(kassa).getByRole('button', { name: 'Opwaarderen' }).click()
  await expect(card.getByText(EURO_15).first()).toBeVisible()

  // A second top-up within 2 minutes asks again (AC17), and is then reversed (AC21).
  await card.getByRole('button', { name: 'Opwaarderen' }).click()
  await expect(dialog(kassa)).toContainText(/Jan is om \d\d:\d\d al opgewaardeerd met €\s15,00/)
  await dialog(kassa).getByRole('button', { name: 'Ja, nog een keer' }).click()
  await expect(card.getByText(/€\s30,00/)).toBeVisible()
  const newest = card.getByRole('list', { name: 'Opwaarderingen' }).getByRole('listitem').first()
  await newest.getByRole('button', { name: 'Terugdraaien' }).click()
  await expect(dialog(kassa)).toContainText(/€\s15,00 van .* terugdraaien\?/)
  await dialog(kassa).getByRole('button', { name: 'Terugdraaien' }).click()
  await expect(newest).toContainText('teruggedraaid')
  await expect(card.locator('p').getByText(EURO_15)).toBeVisible()

  // 5. A's page shows the balance within 10 s (AC10).
  await expect(playerA.getByText(EURO_15)).toBeVisible({ timeout: 15_000 })

  // 6. B signs up as "jan 2"; the kassa moves Jan's balance onto it (AC26).
  await playerB.getByRole('button', { name: 'jan 2' }).click()
  await expect(playerB.getByRole('heading', { name: 'jan 2', exact: true })).toBeVisible()
  const bCode = await shortCode(playerB)
  await find(kassa, bCode)
  const target = section(kassa, 'jan 2')
  await target.getByRole('button', { name: 'Saldo overzetten van…' }).click()
  const move = section(kassa, 'Saldo overzetten')
  await move.getByLabel('Naam of code van de oude wallet').fill('Jan')
  await move.getByRole('button', { name: 'Zoeken' }).click()
  await move.getByRole('button', { name: /^Jan aangemaakt/ }).click()
  await expect(dialog(kassa)).toContainText(
    /€\s15,00 en de naam 'Jan' van Jan \(aangemaakt .*\) naar jan 2 overzetten\?/,
  )
  await dialog(kassa).getByRole('button', { name: 'Overzetten' }).click()
  await expect(
    section(kassa, 'Jan').getByRole('heading', { name: 'Jan', exact: true }),
  ).toBeVisible()

  // 7. B's page shows "Jan" and €15,00; A's page shows sign-up (AC13, AC26).
  await expect(playerB.getByRole('heading', { name: 'Jan', exact: true })).toBeVisible({
    timeout: 15_000,
  })
  await expect(playerB.getByText(EURO_15)).toBeVisible({ timeout: 15_000 })
  await expect(playerA.getByRole('heading', { name: 'Wallet aanmaken' })).toBeVisible({
    timeout: 15_000,
  })

  // 8. Admin: the outstanding balance and the borrel's top-ups (AC34); the kassa counted (AC40).
  await admin.reload()
  const totals = section(admin, 'Wallets').getByRole('region', { name: 'Totalen' })
  await expect(totals).toContainText(/Tegoed: €\s15,00/)
  await expect(totals).toContainText(/Walletborrel: opgewaardeerd €\s15,00, besteed €\s0,00/)
  await admin.goto('/')
  await expect(admin.getByText(/Kassa: 1/)).toBeVisible({ timeout: 15_000 })

  expect(foreign).toEqual([])
})

test('on a secure origin the kassa offers the camera (AC42)', async ({ browser }) => {
  const kassa = await open(browser, loopbackUrl, '/login')
  expect(await kassa.evaluate(() => window.isSecureContext)).toBe(true)
  await login(kassa, kassaKey)
  await expect(kassa).toHaveURL(/\/kassa$/)
  await expect(kassa.getByRole('button', { name: 'Camera' })).toBeVisible()
  await expect(kassa.getByLabel('Code typen')).toBeVisible()
  expect(foreign).toEqual([])
})
