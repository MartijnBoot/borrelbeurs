/**
 * Paying at the bar by scanning a player's wallet, end to end (B-06 T19: AC2, AC4,
 * AC5, AC13, AC15, AC18, AC21, AC25, AC26, AC31, AC32; D-49; plan PD20).
 *
 * Steps 1-6 run on loopback, a secure origin, so the bar offers "Camera" beside
 * "Code typen" (AC32). Step 7 repeats the bar on the venue path: Chromium maps the
 * made-up host `payments.test` onto loopback, so the page runs at
 * `http://payments.test:<port>` -- not secure, as at `http://192.168.8.10` -- and
 * the bar must book with and without a wallet there, with no camera and no
 * `crypto.randomUUID` (AC31, AC32). This is B-05 PD16's mapping.
 *
 * Prices move with every order, so the baskets are sized from the prices the pad
 * shows, with room either side for a tick's drift. Step 5 (no delete in debt) runs
 * before step 4's refund, because that refund lifts the debt step 5 needs.
 *
 * The spec starts its own `serve.py --empty`, so the shared server's live run is
 * not in the way. Every context records and blocks any request that leaves its
 * origin, and the flow asserts none did.
 */
import {
  test as base,
  expect,
  request as http,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from '@playwright/test'
import { readFileSync } from 'node:fs'
import { startServer, stopServer, type ServerProcess } from './serverProcess'

const VENUE_HOST = 'payments.test'
const LIMIT = 250
const CODE = 'Borrel2026'

let server: ServerProcess
let loopbackUrl: string
let venueUrl: string
let adminKey: string
let barKey: string
let janCode: string
const foreign: string[] = []

const test = base.extend({
  // eslint-disable-next-line no-empty-pattern -- Playwright requires the destructuring
  baseURL: async ({}, provide) => provide(loopbackUrl),
})

test.describe.configure({ mode: 'serial' })
test.use({ launchOptions: { args: [`--host-resolver-rules=MAP ${VENUE_HOST} 127.0.0.1`] } })

test.beforeAll(async () => {
  test.setTimeout(150_000)
  server = await startServer('payments', ['--empty'])
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

/** A borrel with a dear and a cheap drink, live, made as admin does: switch on. */
async function goLive(): Promise<void> {
  const api = await http.newContext({
    baseURL: loopbackUrl,
    extraHTTPHeaders: { Origin: loopbackUrl },
  })
  try {
    expect((await api.post('/api/auth/login', { data: { key: adminKey } })).ok()).toBe(true)
    const run = await api.post('/api/runs', { data: { name: 'Betaalborrel' } })
    expect(run.ok()).toBe(true)
    const { run_id: runId } = (await run.json()) as { run_id: number }
    for (const drink of [
      { name: 'Bier', p_min_cents: 100, p0_cents: 250, p_max_cents: 500 },
      { name: 'Fris', p_min_cents: 50, p0_cents: 100, p_max_cents: 200 },
    ]) {
      expect((await api.post(`/api/runs/${runId}/drinks`, { data: drink })).ok()).toBe(true)
    }
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

/** `formatBalance`'s spelling, as a pattern: "−€ 2,10", "€ 7,50" (PD11). */
function money(cents: number): RegExp {
  const euros = (Math.abs(cents) / 100).toFixed(2).replace('.', ',')
  return new RegExp(`${cents < 0 ? '−' : ''}€\\s${euros}(?!\\d)`)
}

function cents(text: string | null): number {
  const match = /€\s(\d+),(\d\d)/.exec(text ?? '')
  if (match === null) throw new Error(`no amount in ${text}`)
  return Number(match[1]) * 100 + Number(match[2])
}

async function newKey(admin: Page, role: string, label: string): Promise<string> {
  const keys = section(admin, 'Toegangssleutels')
  await keys.getByLabel('Rol').selectOption({ label: role })
  await keys.getByLabel('Label').fill(label)
  await keys.getByRole('button', { name: 'Nieuwe sleutel' }).click()
  await expect(keys.getByText('Wordt maar één keer getoond')).toBeVisible()
  const key = (await keys.locator('code').textContent()) ?? ''
  expect(key).toMatch(/^bb_/)
  await keys.getByRole('button', { name: 'Sluiten' }).click()
  return key
}

const pad = (bar: Page) => bar.getByRole('group', { name: 'Drankjes' })
const drink = (bar: Page, name: string): Locator =>
  pad(bar).getByRole('button', { name: new RegExp(`^${name} — `) })
const checkout = (bar: Page) => bar.getByRole('button', { name: /^(Afrekenen|Scan eerst|Saldo )/ })
const held = (bar: Page) => bar.getByRole('region', { name: 'Wallet' })
const payments = (bar: Page) =>
  section(bar, 'Betalingen (laatste 10 minuten)').getByRole('listitem')

interface Receipt {
  total_cents: number
  wallet: { name: string; balance_after_cents: number } | null
}

/** Type the player's code into the bar's picker; the wallet is then held. */
async function scan(bar: Page, code: string): Promise<void> {
  await bar.getByLabel('Code typen').fill(code)
  await bar.getByRole('button', { name: 'Zoeken' }).click()
  await expect(held(bar).getByText('Jan', { exact: true })).toBeVisible()
}

/** Tap "Afrekenen…" and return the order's receipt. */
async function pay(bar: Page): Promise<Receipt> {
  const answer = bar.waitForResponse(
    (r) => r.url().endsWith('/api/orders') && r.request().method() === 'POST',
  )
  await checkout(bar).click()
  const response = await answer
  expect(response.status()).toBe(201)
  return (await response.json()) as Receipt
}

async function tap(bar: Page, name: string, times: number): Promise<void> {
  for (let n = 0; n < times; n++) await drink(bar, name).click()
}

test('a borrel paid from a wallet: pay, a shortfall, debt, a refund, the switch off', async ({
  browser,
}) => {
  test.setTimeout(240_000)
  await goLive()

  // 1. Admin: the sign-up code, "Rood staan tot" €2,50, a kassa and a bar key (AC2).
  const admin = await open(browser, loopbackUrl, '/login')
  await login(admin, adminKey)
  await admin.goto('/settings')
  const wallets = section(admin, 'Wallets')
  await wallets.getByRole('textbox', { name: 'Aanmeldcode' }).fill(CODE)
  await wallets.getByRole('button', { name: 'Opslaan' }).first().click()
  await expect(wallets.getByText(`/speler?code=${CODE}`)).toBeVisible()
  const global = section(admin, 'Globale instellingen')
  await expect(global.getByRole('switch', { name: 'Wallet verplicht' })).toHaveAttribute(
    'aria-checked',
    'true',
  )
  await global.getByRole('textbox', { name: 'Rood staan tot (€)' }).fill('2,50')
  await global.getByRole('button', { name: 'Opslaan instellingen' }).click()
  await expect(admin.getByText('Opgeslagen', { exact: true })).toBeVisible()
  const kassaKey = await newKey(admin, 'Kassa', 'Kassa 1')
  barKey = await newKey(admin, 'Bar', 'Bar 1')

  // The player signs up; the kassa tops up €10.
  const player = await open(browser, loopbackUrl, `/speler?code=${CODE}`)
  await player.getByLabel('Naam').fill('Jan')
  await player.getByRole('button', { name: 'Aanmelden' }).click()
  await expect(player.getByRole('heading', { name: 'Jan', exact: true })).toBeVisible()
  janCode = (await player.getByText(/^[0-9A-Z]{4}-[0-9A-Z]{4}$/).textContent()) ?? ''
  const kassa = await open(browser, loopbackUrl, '/login')
  await login(kassa, kassaKey)
  await kassa.getByLabel('Code typen').fill(janCode)
  await kassa.getByRole('button', { name: 'Zoeken' }).click()
  const card = section(kassa, 'Jan')
  await card.getByRole('button', { name: 'Opwaarderen' }).click()
  await dialog(kassa).getByRole('button', { name: 'Opwaarderen' }).click()
  await expect(card.locator('p').getByText(money(1000))).toBeVisible()
  await expect(player.getByText(money(1000))).toBeVisible({ timeout: 15_000 })

  // 2. The bar, on a secure origin: "Camera" beside "Code typen" (AC32); no wallet, no
  // paying (AC14). It types the code, sees the name large, buys 3× Bier (AC4, AC5, AC13).
  const bar = await open(browser, loopbackUrl, '/login')
  await login(bar, barKey)
  await bar.goto('/bar')
  await expect(bar.getByRole('button', { name: 'Camera' })).toBeVisible()
  await tap(bar, 'Bier', 1)
  await expect(checkout(bar)).toHaveText('Scan eerst een wallet')
  await expect(checkout(bar)).toBeDisabled()
  await scan(bar, janCode.toLowerCase())
  await expect(held(bar)).toContainText(money(1000))
  await tap(bar, 'Bier', 2)
  await expect(checkout(bar)).toHaveText(/^Afrekenen €\s[\d,]+$/)
  const first = await pay(bar)
  expect(first.wallet?.name).toBe('Jan')
  const afterFirst = first.wallet!.balance_after_cents
  expect(afterFirst).toBe(1000 - first.total_cents)
  await expect(
    bar.getByText(
      new RegExp(
        `^Betaald ${money(first.total_cents).source} — Jan, saldo ${money(afterFirst).source}$`,
      ),
    ),
  ).toBeVisible()
  await expect(held(bar)).toHaveCount(0)
  await expect(player.getByText(money(afterFirst))).toBeVisible({ timeout: 20_000 })

  // 3. Over balance + €2,50 the button is the shortfall, disabled (AC18). Without the Bier
  // the basket fits, and paying takes the balance below zero (AC25).
  await scan(bar, janCode)
  const fris = cents(await drink(bar, 'Fris').textContent())
  expect(2 * fris).toBeLessThan(LIMIT) // the sizing below needs a cheap drink
  const count = Math.floor((afterFirst + LIMIT) / fris) - 1
  expect(count * fris).toBeGreaterThan(afterFirst)
  await tap(bar, 'Fris', count)
  await tap(bar, 'Bier', 1)
  await expect(checkout(bar)).toHaveText(/^Saldo €\s[\d,]+ — nog €\s[\d,]+ tekort$/)
  await expect(checkout(bar)).toBeDisabled()
  await bar.getByRole('button', { name: 'Eén Bier minder' }).click()
  await expect(checkout(bar)).toBeEnabled()
  const debt = await pay(bar)
  const inDebt = debt.wallet!.balance_after_cents
  expect(inDebt).toBeLessThan(0)
  expect(inDebt).toBeGreaterThanOrEqual(-LIMIT)
  await expect(bar.getByText(money(inDebt))).toBeVisible()
  await expect(player.getByText(money(inDebt))).toBeVisible({ timeout: 20_000 })

  // 5. The player cannot delete a wallet in debt (AC26).
  await player.getByRole('button', { name: 'Wallet verwijderen' }).click()
  await expect(player.getByText('Eerst aanvullen bij de kassa')).toBeVisible()
  await expect(player.getByRole('heading', { name: 'Jan', exact: true })).toBeVisible()

  // 4. The bar refunds that payment; the balance returns (AC21).
  const newest = payments(bar).first()
  await expect(newest).toContainText(
    new RegExp(`${count}× Fris — ${money(debt.total_cents).source} om \\d\\d:\\d\\d, Jan`),
  )
  await newest.getByRole('button', { name: 'Terugboeken' }).click()
  await expect(dialog(bar)).toContainText(
    new RegExp(`${money(debt.total_cents).source} terugboeken naar Jan\\?`),
  )
  await dialog(bar).getByRole('button', { name: 'Terugboeken' }).click()
  await expect(newest).toContainText('teruggeboekt')
  await expect(player.getByText(money(afterFirst))).toBeVisible({ timeout: 20_000 })

  // 6. Admin turns the switch off; the bar follows live (AC2) and books an order with no
  // wallet, writing no payment (AC15).
  await admin.goto('/settings')
  await global.getByRole('switch', { name: 'Wallet verplicht' }).click()
  await global.getByRole('button', { name: 'Opslaan instellingen' }).click()
  await expect(admin.getByText('Opgeslagen', { exact: true })).toBeVisible()
  const listed = await payments(bar).count()
  await tap(bar, 'Fris', 1)
  await expect(checkout(bar)).toHaveText(/^Afrekenen zonder wallet €\s[\d,]+$/)
  const unpaid = await pay(bar)
  expect(unpaid.wallet).toBeNull()
  await expect(bar.getByText(/^1× Fris besteld — /)).toBeVisible()
  await bar.reload()
  await expect(payments(bar)).toHaveCount(listed)
  await expect(player.getByText(money(afterFirst))).toBeVisible()

  expect(foreign).toEqual([])
})

test('on the venue path the bar books with and without a wallet (AC31, AC32)', async ({
  browser,
}) => {
  // 7. Plain HTTP on a non-loopback name: no secure context, no camera, no randomUUID.
  const bar = await open(browser, venueUrl, '/login')
  expect(await bar.evaluate(() => window.isSecureContext)).toBe(false)
  expect(await bar.evaluate(() => typeof crypto.randomUUID)).toBe('undefined')
  await login(bar, barKey)
  await bar.goto('/bar')
  await expect(bar.getByLabel('Code typen')).toBeVisible()
  await expect(bar.getByRole('button', { name: 'Camera' })).toHaveCount(0)

  await scan(bar, janCode)
  await tap(bar, 'Fris', 1)
  const paid = await pay(bar)
  expect(paid.wallet?.name).toBe('Jan')
  await expect(bar.getByText(/^Betaald .* — Jan, saldo /)).toBeVisible()

  await tap(bar, 'Fris', 1)
  await expect(checkout(bar)).toHaveText(/^Afrekenen zonder wallet /)
  const unpaid = await pay(bar)
  expect(unpaid.wallet).toBeNull()

  expect(foreign).toEqual([])
})
