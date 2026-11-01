/**
 * The sign-up QR code on the koers screen, end to end, at an insecure origin
 * (B-10 T8: AC3, AC5, AC11-AC20; plan PD9).
 *
 * Chromium maps the made-up host `signup.test` onto loopback, so the display runs at
 * `http://signup.test:<port>` -- not a secure context, as at `http://192.168.8.10` --
 * against the real server (`signup-qr.spec.ts`). The shared server runs with no
 * `BB_PUBLIC_URL` (`realapp/harness.py`), so the screen links to the address it is
 * open at, and at `127.0.0.1` it has none (AC3).
 *
 * The QR code is decoded from the drawn SVG: its rects rasterised as a camera would
 * see them, then read with `jsqr`. The server is shared: the switch and the code are
 * reset over the API before and after, so a failure cannot leave the block on for
 * the other specs.
 */
import { request as http, type Browser, type Page } from '@playwright/test'
import jsQR from 'jsqr'
import { expect, server, submitKey, test } from './fixtures'

const SIGNUP_HOST = 'signup.test'
// 1x1 PNG: a promo image to give the board its has-promo grid.
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64',
)

const loopbackUrl = () => server().base_url
const signupUrl = () => {
  const url = new URL(loopbackUrl())
  url.hostname = SIGNUP_HOST
  return url.origin
}
const foreign: string[] = []

test.describe.configure({ mode: 'serial' })
test.use({ launchOptions: { args: [`--host-resolver-rules=MAP ${SIGNUP_HOST} 127.0.0.1`] } })

/** An admin API context on the loopback address, logged in. */
async function adminApi() {
  const base = loopbackUrl()
  const api = await http.newContext({ baseURL: base, extraHTTPHeaders: { Origin: base } })
  expect((await api.post('/api/auth/login', { data: { key: server().keys.admin } })).ok()).toBe(
    true,
  )
  return api
}

/** `PUT /api/admin/wallet-settings` over HTTP, changing only `changes`. */
async function putSettings(changes: Record<string, unknown>): Promise<void> {
  const api = await adminApi()
  try {
    const stored = await api.get('/api/admin/wallet-settings')
    expect(stored.ok()).toBe(true)
    const body = { ...(await stored.json()), ...changes }
    expect((await api.put('/api/admin/wallet-settings', { data: body })).ok()).toBe(true)
  } finally {
    await api.dispose()
  }
}

const reset = () => putSettings({ signup_code: null, show_signup_on_screen: false })

async function setPromo(on: boolean): Promise<void> {
  const api = await adminApi()
  try {
    const response = on
      ? await api.post('/api/theme/images/promo', {
          multipart: { file: { name: 'promo.png', mimeType: 'image/png', buffer: PNG } },
        })
      : await api.delete('/api/theme/images/promo')
    expect(response.ok()).toBe(true)
  } finally {
    await api.dispose()
  }
}

async function startCrash(durationMs: number): Promise<void> {
  const api = await adminApi()
  try {
    const response = await api.post('/api/market/events', {
      data: { kind: 'crash', duration_ms: durationMs },
    })
    expect(response.status()).toBe(201)
  } finally {
    await api.dispose()
  }
}

/** A page of `role` at `baseURL`, in a context that aborts any request leaving its origin. */
async function openAs(
  browser: Browser,
  baseURL: string,
  key: string,
  path: string,
  viewport = { width: 1920, height: 1080 },
): Promise<Page> {
  const context = await browser.newContext({ baseURL, viewport })
  const origin = new URL(baseURL).origin
  await context.route('**/*', (route) => {
    const url = route.request().url()
    if (new URL(url).origin === origin) return route.continue()
    foreign.push(url)
    return route.abort()
  })
  const page = await context.newPage()
  await page.goto('/login')
  await submitKey(page, key)
  await page.waitForURL((url) => url.pathname !== '/login')
  await page.goto(path)
  return page
}

const qr = (page: Page) => page.getByRole('img', { name: 'Aanmeld-QR-code' })
const card = (page: Page) => qr(page).locator('..')

/** The drawn QR code rasterised as a camera would see it, then decoded. */
async function decode(page: Page): Promise<string | undefined> {
  const { size, cells } = await qr(page).evaluate((svg) => ({
    size: Number(svg.getAttribute('viewBox')!.split(' ')[2]),
    cells: Array.from(svg.querySelectorAll('rect'), (r) => [
      Number(r.getAttribute('x')),
      Number(r.getAttribute('y')),
    ]),
  }))
  const k = 6
  const width = size * k
  const data = new Uint8ClampedArray(width * width * 4).fill(255)
  for (const [x, y] of cells) {
    for (let py = y * k; py < (y + 1) * k; py++) {
      for (let px = x * k; px < (x + 1) * k; px++) {
        data.fill(0, (py * width + px) * 4, (py * width + px) * 4 + 3)
      }
    }
  }
  return jsQR(data, width, width, { inversionAttempts: 'dontInvert' })?.data
}

const wallets = (page: Page) => page.getByRole('region', { name: 'Aanmeldcode', exact: true })

type Box = { x: number; y: number; width: number; height: number }
const disjoint = (a: Box, b: Box) =>
  a.x + a.width <= b.x + 0.5 ||
  b.x + b.width <= a.x + 0.5 ||
  a.y + a.height <= b.y + 0.5 ||
  b.y + b.height <= a.y + 0.5

async function box(page: Page, selector: string): Promise<Box[]> {
  return page.locator(selector).evaluateAll((els) =>
    els.map((el) => {
      const { x, y, width, height } = el.getBoundingClientRect()
      return { x, y, width, height }
    }),
  )
}

test.beforeAll(async () => {
  await reset()
})

// The server is shared: a failure midway must not leave the block on or a promo set (PD9).
test.afterAll(async () => {
  await setPromo(false)
  await reset()
})

test('the koers screen shows the sign-up QR code, follows changes live and hides itself', async ({
  browser,
}) => {
  test.setTimeout(180_000)
  const display = await openAs(browser, signupUrl(), server().keys.display, '/koers')
  const errors: Error[] = []
  display.on('pageerror', (error) => errors.push(error))
  const admin = await openAs(browser, signupUrl(), server().keys.admin, '/settings')

  // 1. The switch is off: no block (AC13). Not a secure context (AC20).
  expect(await display.evaluate(() => window.isSecureContext)).toBe(false)
  await expect(display.locator('[class*="_tile_"]').first()).toBeVisible()
  await expect(qr(display)).toHaveCount(0)

  // 2. A code with the switch off: still none. The checkbox turns it on, with no reload (AC11, AC18).
  await putSettings({ signup_code: 'BORREL' })
  await expect(wallets(admin).getByRole('textbox', { name: 'Aanmeldcode' })).toBeVisible()
  await display.waitForTimeout(500)
  await expect(qr(display)).toHaveCount(0)
  await admin.reload()
  const onScreen = wallets(admin).getByRole('checkbox', { name: 'QR-code op het scherm' })
  await onScreen.click() // controlled: it flips when the save returns
  await expect(onScreen).toBeChecked()
  await expect(qr(display)).toBeVisible()
  expect(await decode(display)).toBe(`${signupUrl()}/speler?code=BORREL`) // AC12
  await expect(card(display)).toHaveText('Meld je aan')

  // 3. A different code, confirmed: the screen redraws, and the link opens the player page.
  await wallets(admin).getByRole('textbox', { name: 'Aanmeldcode' }).fill('ANDERS')
  await wallets(admin).getByRole('button', { name: 'Opslaan' }).click()
  await admin.getByRole('dialog').getByRole('button', { name: 'Wijzigen' }).click()
  await expect.poll(() => decode(display)).toBe(`${signupUrl()}/speler?code=ANDERS`)
  const player = await (await browser.newContext()).newPage()
  await player.goto(`${signupUrl()}/speler?code=ANDERS`)
  await expect(player.getByLabel('Aanmeldcode')).toHaveValue('ANDERS')
  await player.context().close()

  // 4. A crash: the block stays inside the viewport, clear of the banner, and decodes in the glow (AC14).
  await startCrash(8_000)
  const banner = display.locator('.market-banner')
  await expect(banner).toBeVisible()
  const [card4] = await box(display, 'div:has(> svg[aria-label="Aanmeld-QR-code"])')
  const [banner4] = await box(display, '.market-banner')
  expect(card4.x).toBeGreaterThanOrEqual(0)
  expect(card4.y).toBeGreaterThanOrEqual(0)
  expect(card4.x + card4.width).toBeLessThanOrEqual(1920)
  expect(card4.y + card4.height).toBeLessThanOrEqual(1080)
  expect(disjoint(card4, banner4)).toBe(true)
  expect(await decode(display)).toBe(`${signupUrl()}/speler?code=ANDERS`)
  await expect(banner).toHaveCount(0, { timeout: 15_000 })

  // 5. A reload shows it at once (AC5). Clearing the code removes it (AC18).
  await display.reload()
  await expect(qr(display)).toBeVisible()
  await putSettings({ signup_code: null })
  await expect(qr(display)).toHaveCount(0)
  await putSettings({ signup_code: 'ANDERS' })
  await expect(qr(display)).toBeVisible()

  // 6. The switch off removes it too; on again, it is back.
  await putSettings({ show_signup_on_screen: false })
  await expect(qr(display)).toHaveCount(0)
  await putSettings({ show_signup_on_screen: true })
  await expect(qr(display)).toBeVisible()

  expect(errors).toEqual([])
  await display.context().close()
  await admin.context().close()
})

test('a dropped socket keeps the block, and reconnecting shows what the server holds (AC19)', async ({
  browser,
}) => {
  test.setTimeout(90_000)
  await putSettings({ signup_code: 'ANDERS', show_signup_on_screen: true })
  const context = await browser.newContext({ baseURL: signupUrl() })
  const page = await context.newPage()
  let severed = false
  let current: import('@playwright/test').WebSocketRoute | undefined
  await page.routeWebSocket('**/ws', (ws) => {
    if (severed) return ws.close({ code: 1011 })
    current = ws
    ws.connectToServer()
  })
  await page.goto('/login')
  await submitKey(page, server().keys.display)
  await page.waitForURL((url) => url.pathname !== '/login')
  await page.goto('/koers')
  await expect(qr(page)).toBeVisible()

  severed = true
  await current!.close({ code: 1001 })
  await expect(page.getByText('Verbinding verbroken — opnieuw verbinden…')).toBeVisible()
  await expect(qr(page)).toBeVisible() // kept as it was
  expect(await decode(page)).toBe(`${signupUrl()}/speler?code=ANDERS`)

  // The code changes while the screen is cut off; the reconnect brings the current one.
  await putSettings({ signup_code: 'LATER' })
  severed = false
  await expect(page.getByText('Verbinding verbroken — opnieuw verbinden…')).toHaveCount(0, {
    timeout: 30_000,
  })
  await expect.poll(() => decode(page)).toBe(`${signupUrl()}/speler?code=LATER`)
  await context.close()
})

for (const promo of [false, true]) {
  for (const size of [
    { width: 1920, height: 1080 },
    { width: 1280, height: 720 },
  ]) {
    test(`the block covers nothing at ${size.width}x${size.height}${promo ? ' with a promo image' : ''} (AC16)`, async ({
      browser,
    }) => {
      await putSettings({ signup_code: 'BORREL', show_signup_on_screen: true })
      await setPromo(promo)
      try {
        const page = await openAs(browser, signupUrl(), server().keys.display, '/koers', size)
        await expect(qr(page)).toBeVisible()
        await expect(page.locator('[class*="_tile_"]').first()).toBeVisible()
        if (promo) await expect(page.locator('img[alt="Promotie"]')).toBeVisible()

        const [block] = await box(page, 'div:has(> svg[aria-label="Aanmeld-QR-code"])')
        const [band] = await box(page, '[class*="_band_"]')
        const [marquees] = await box(page, '[class*="_marquees_"]')
        const others = [
          ...(await box(page, '[class*="_marquees_"] > *')),
          ...(await box(page, '[class*="_tile_"]')),
          ...(await box(page, '.market-banner')),
        ]
        for (const other of others) expect(disjoint(block, other)).toBe(true)
        // The marquees fill the width to the block's right, to the band's right edge.
        expect(marquees.x).toBeGreaterThanOrEqual(block.x + block.width - 0.5)
        expect(Math.abs(marquees.x + marquees.width - (band.x + band.width))).toBeLessThanOrEqual(1)
        expect(Math.abs(band.x + band.width - size.width)).toBeLessThanOrEqual(1)
        // At least 96 px square.
        const [svg] = await box(page, 'svg[aria-label="Aanmeld-QR-code"]')
        expect(svg.width).toBeGreaterThanOrEqual(96)
        expect(svg.height).toBeGreaterThanOrEqual(96)
        await page.context().close()
      } finally {
        await setPromo(false)
      }
    })
  }
}

test('at 700 px wide the block is not shown (AC15)', async ({ browser }) => {
  await putSettings({ signup_code: 'BORREL', show_signup_on_screen: true })
  const page = await openAs(browser, signupUrl(), server().keys.display, '/koers', {
    width: 700,
    height: 900,
  })
  await expect(page.locator('[class*="_tile_"]').first()).toBeVisible()
  await expect(qr(page)).toBeHidden() // display: none
  await page.context().close()
})

test('at the loopback address, with no public address, there is no block (AC3)', async ({
  browser,
}) => {
  await putSettings({ signup_code: 'BORREL', show_signup_on_screen: true })
  const page = await openAs(browser, loopbackUrl(), server().keys.display, '/koers')
  expect(new URL(page.url()).hostname).toBe('127.0.0.1')
  await expect(page.locator('[class*="_tile_"]').first()).toBeVisible()
  await expect(qr(page)).toHaveCount(0)
  await page.context().close()
  expect(foreign).toEqual([])
})
