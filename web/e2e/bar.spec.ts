/**
 * The bar page in Chromium against the real server and its live run (Phase 5
 * T16): AC1, AC3, AC9, AC10, AC12, AC13, AC19, AC24, AC28.
 *
 * Database facts come through the API with the page's own cookies:
 * `/api/state` gives the server's `earnings`, `/api/earnings/series` the SQL
 * Σ `line_total_cents`. The run is shared with the other specs, so every
 * assertion is a delta, never an absolute total (R6).
 */
import type { APIRequestContext, Browser, Page, Request } from '@playwright/test'
import { expect, server, submitKey, test } from './fixtures'

const DRINK = /^\+1 /
const EUR = new Intl.NumberFormat('nl-NL', {
  style: 'currency',
  currency: 'EUR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/** As the page shows it, with the no-break space as a plain one. */
const euro = (cents: number) => plain(EUR.format(cents / 100))
const plain = (text: string | null) => (text ?? '').replace(/\xa0/g, ' ')

interface Earnings {
  qty: number
  revenue_cents: number
}

async function earnings(request: APIRequestContext): Promise<Record<string, Earnings>> {
  const response = await request.get('/api/state')
  expect(response.ok()).toBe(true)
  return ((await response.json()) as { earnings: Record<string, Earnings> }).earnings
}

const qtyOf = (all: Record<string, Earnings>, drinkId: number) => all[drinkId]?.qty ?? 0
const totalQty = (all: Record<string, Earnings>) =>
  Object.values(all).reduce((sum, e) => sum + e.qty, 0)

interface OrderBody {
  quote_version: number
  lines: { drink_id: number; qty: number; unit_price_cents: number }[]
}

const isOrder = (r: Request) => r.method() === 'POST' && new URL(r.url()).pathname === '/api/orders'
const keyOf = (r: Request) => r.headers()['idempotency-key']

/** Wait until the pad has a fresh quote and the first drink button is usable. */
async function readyPad(page: Page) {
  await expect(page).toHaveURL((url) => url.pathname === '/bar')
  const button = page.getByRole('button', { name: DRINK }).first()
  await expect(button).toBeEnabled()
  return button
}

/** Confirm every 409 dialog that shows up until `done` holds. */
async function confirmUntil(page: Page, done: () => Promise<boolean>) {
  await expect(async () => {
    const dialog = page.getByRole('dialog')
    if (await dialog.isVisible()) await page.getByRole('button', { name: 'Bevestigen' }).click()
    expect(await done()).toBe(true)
  }).toPass({ timeout: 15_000 })
}

test.describe('the bar page (Phase 5)', () => {
  test('a tap posts the held quote and confirms at the receipt price (AC1, AC3)', async ({
    page,
    loginAs,
  }) => {
    await loginAs('bar')
    const button = await readyPad(page)

    // Inside the hold, the DOM is the displayed quote the tap will read.
    await button.dispatchEvent('pointerdown')
    const label = plain(await button.textContent())
    const version = Number(
      await page.locator('[data-quote-version]').getAttribute('data-quote-version'),
    )
    const name = label.replace(/^\+1 /, '').split(' — ')[0]

    const posted = page.waitForRequest(isOrder)
    const answered = page.waitForResponse((r) => isOrder(r.request()))
    await button.click()
    const body = (await posted).postDataJSON() as OrderBody
    const response = await answered

    expect(body.quote_version).toBe(version)
    expect(body.lines).toHaveLength(1)
    expect(label).toBe(`+1 ${name} — ${euro(body.lines[0].unit_price_cents)}`)
    expect(response.status()).toBe(201)
    const receipt = (await response.json()) as { lines: { unit_price_cents: number }[] }
    await expect(page.getByRole('listitem').filter({ hasText: 'besteld' })).toHaveText(
      `1× ${name} besteld — ${EUR.format(receipt.lines[0].unit_price_cents / 100)}`,
    )
  })

  test('a 409 asks to confirm at its price; confirming posts a new key at it (AC12, AC13)', async ({
    page,
    loginAs,
  }) => {
    await loginAs('bar')
    const button = await readyPad(page)
    const before = await earnings(page.request)

    let forced = false
    await page.route('**/api/orders', async (route) => {
      if (forced) return route.continue()
      forced = true
      const body = route.request().postDataJSON() as OrderBody
      body.lines[0].unit_price_cents += 100_000 // far outside the grace step
      await route.continue({ postData: JSON.stringify(body) })
    })

    const first = page.waitForResponse((r) => isOrder(r.request()))
    await button.click()
    let conflict = await first
    expect(conflict.status()).toBe(409)
    const drinkId = (conflict.request().postDataJSON() as OrderBody).lines[0].drink_id
    const keys = [keyOf(conflict.request())]

    for (let attempt = 0; ; attempt++) {
      const error = (
        (await conflict.json()) as {
          error: { prices: { drink_id: number; price_cents: number }[] }
        }
      ).error
      const price = error.prices.find((p) => p.drink_id === drinkId)!.price_cents
      const dialog = page.getByRole('dialog')
      await expect(dialog).toContainText(`prijs is nu ${EUR.format(price / 100)} — bevestigen?`)
      expect(qtyOf(await earnings(page.request), drinkId)).toBe(qtyOf(before, drinkId) + 0)

      const next = page.waitForResponse((r) => isOrder(r.request()))
      await page.getByRole('button', { name: 'Bevestigen' }).click()
      const response = await next
      const sent = response.request().postDataJSON() as OrderBody
      expect(keys).not.toContain(keyOf(response.request()))
      keys.push(keyOf(response.request()))
      expect(sent.lines[0].unit_price_cents).toBe(price)
      if (response.status() === 201) {
        const receipt = (await response.json()) as { lines: { unit_price_cents: number }[] }
        expect(receipt.lines[0].unit_price_cents).toBe(price)
        break
      }
      expect(response.status()).toBe(409) // prices moved again: a new dialog, newer price
      expect(attempt).toBeLessThan(3)
      conflict = response
    }
    await expect
      .poll(async () => qtyOf(await earnings(page.request), drinkId))
      .toBe(qtyOf(before, drinkId) + 1)
  })

  test('a double tap posts two orders with distinct keys (AC9)', async ({ page, loginAs }) => {
    await loginAs('bar')
    const button = await readyPad(page)
    const before = totalQty(await earnings(page.request))
    const requests: Request[] = []
    page.on('request', (r) => {
      if (isOrder(r)) requests.push(r)
    })

    await button.dblclick()
    await expect.poll(() => requests.length).toBeGreaterThanOrEqual(2)
    expect(keyOf(requests[0])).not.toBe(keyOf(requests[1]))
    await confirmUntil(page, async () => totalQty(await earnings(page.request)) === before + 2)
  })

  test('an aborted request is retried with the same key and body, and books once (AC10)', async ({
    page,
    loginAs,
  }) => {
    await loginAs('bar')
    const button = await readyPad(page)
    const before = await earnings(page.request)
    const seen: { key: string; body: string }[] = []
    await page.route('**/api/orders', async (route) => {
      seen.push({ key: keyOf(route.request()), body: route.request().postData() ?? '' })
      if (seen.length === 1) return route.abort()
      return route.continue()
    })

    await button.click()
    await expect.poll(() => seen.length, { timeout: 10_000 }).toBe(2)
    expect(seen[1]).toEqual(seen[0])
    const drinkId = (JSON.parse(seen[0].body) as OrderBody).lines[0].drink_id
    await confirmUntil(
      page,
      async () => qtyOf(await earnings(page.request), drinkId) === qtyOf(before, drinkId) + 1,
    )
    await expect(page.getByRole('listitem').filter({ hasText: 'besteld' })).toBeVisible()
  })

  test('two bar sessions converge on the database total (AC19)', async ({ browser }) => {
    const [a, b] = [await barPage(browser), await barPage(browser)]
    const before = totalQty(await earnings(a.request))
    await (await readyPad(a)).click()
    await (await readyPad(b)).click()
    await confirmUntil(a, async () => totalQty(await earnings(a.request)) >= before + 1)
    await confirmUntil(b, async () => totalQty(await earnings(b.request)) === before + 2)

    const series = (await (await a.request.get('/api/earnings/series')).json()) as {
      cum_revenue_cents: number
    }[]
    const total = euro(series.at(-1)!.cum_revenue_cents)
    for (const page of [a, b]) {
      await expect
        .poll(async () => plain(await page.getByTestId('total-revenue').textContent()))
        .toBe(total)
    }
    await a.context().close()
    await b.context().close()
  })

  test('at 640 px there is no chart and no series request (AC24)', async ({ page, loginAs }) => {
    await page.setViewportSize({ width: 640, height: 900 })
    const series: string[] = []
    page.on('request', (r) => {
      if (new URL(r.url()).pathname === '/api/earnings/series') series.push(r.url())
    })
    await loginAs('bar')
    await readyPad(page)
    await expect(page.getByRole('heading', { name: '💶 Financieel overzicht' })).toBeVisible()
    await expect(page.getByTestId('total-revenue')).toBeVisible()
    await expect(page.locator('canvas')).toHaveCount(0)
    expect(series).toEqual([])
  })

  test('display on /bar sees "Geen toegang" (AC28)', async ({ page, loginAs }) => {
    await loginAs('display')
    await page.goto('/bar')
    await expect(page.getByText('Geen toegang')).toBeVisible()
    await expect(page.getByRole('button', { name: DRINK })).toHaveCount(0)
  })
})

/** A fresh bar session in its own context, on `/bar`. */
async function barPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ baseURL: server().base_url })
  const page = await context.newPage()
  await page.goto('/login')
  await submitKey(page, server().keys.bar)
  await page.waitForURL((url) => url.pathname === '/bar')
  return page
}
