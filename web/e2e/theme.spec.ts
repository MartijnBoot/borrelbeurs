/**
 * The server-side theme in Chromium against the real app (AC3, AC4, AC10):
 * an admin's pick on `/settings` reaches a display on `/koers` live, and the
 * blocking `/theme.css` paints the stored theme before any script runs.
 * Expected colours are the presets' own `--bg` (`app/runtime/theme.py`,
 * ported from v1's `theme.js`). The theme is put back to Blauw afterwards.
 */
import { request as http, type Browser, type Page } from '@playwright/test'
import { expect, server, submitKey, test, type Role } from './fixtures'

type Preset = 'blauw' | 'rood' | 'oudgeld'

/** Each preset's `--bg`, as `getComputedStyle` reports it. */
const BG: Record<Preset, string> = {
  blauw: rgb('#070b16'),
  rood: rgb('#0f0505'),
  oudgeld: rgb('#0e0c07'),
}

const PROPAGATION_MS = 2_000

function rgb(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
  return `rgb(${r}, ${g}, ${b})`
}

/** `PUT /api/theme` as admin, over HTTP rather than the UI. */
async function storeTheme(preset: Preset): Promise<void> {
  const base = server().base_url
  const api = await http.newContext({ baseURL: base, extraHTTPHeaders: { Origin: base } })
  try {
    expect((await api.post('/api/auth/login', { data: { key: server().keys.admin } })).ok()).toBe(
      true,
    )
    expect((await api.put('/api/theme', { data: { preset } })).ok()).toBe(true)
  } finally {
    await api.dispose()
  }
}

async function pageAs(browser: Browser, role: Role): Promise<Page> {
  const context = await browser.newContext({ baseURL: server().base_url })
  const page = await context.newPage()
  await page.goto('/login')
  await submitKey(page, server().keys[role])
  await page.waitForURL((url) => url.pathname !== '/login')
  return page
}

const bodyBackground = (page: Page) =>
  page.evaluate(() => getComputedStyle(document.body).backgroundColor)

test.afterAll(async () => {
  await storeTheme('blauw')
})

test('a preset picked on /settings re-themes /koers within 2 s, without navigation (AC3)', async ({
  browser,
}) => {
  await storeTheme('blauw')
  const admin = await pageAs(browser, 'admin')
  await admin.goto('/settings')
  const display = await pageAs(browser, 'display')
  await expect(display).toHaveURL((url) => url.pathname === '/koers')
  await expect.poll(() => bodyBackground(display)).toBe(BG.blauw)

  let navigations = 0
  display.on('framenavigated', (frame) => {
    if (frame === display.mainFrame()) navigations += 1
  })
  await admin.getByRole('button', { name: 'Rood' }).click()

  await expect.poll(() => bodyBackground(display), { timeout: PROPAGATION_MS }).toBe(BG.rood)
  expect(navigations).toBe(0)
})

test('picking Oud Geld sets EB Garamond on the display, loaded (AC10)', async ({ browser }) => {
  await storeTheme('blauw')
  const admin = await pageAs(browser, 'admin')
  await admin.goto('/settings')
  const display = await pageAs(browser, 'display')
  await expect(display).toHaveURL((url) => url.pathname === '/koers')

  await admin.getByRole('button', { name: 'Oud Geld' }).click()

  await expect
    .poll(() => display.evaluate(() => getComputedStyle(document.body).fontFamily), {
      timeout: PROPAGATION_MS,
    })
    .toContain('EB Garamond')
  const font = await display.evaluate(async () => {
    await document.fonts.ready
    let loaded = false
    document.fonts.forEach((face) => {
      if (face.family.replace(/["']/g, '') === 'EB Garamond' && face.status === 'loaded') {
        loaded = true
      }
    })
    return { loaded, check: document.fonts.check('16px "EB Garamond"') }
  })
  expect(font).toEqual({ loaded: true, check: true })
  expect(await bodyBackground(display)).toBe(BG.oudgeld)
})

test('with every script blocked, /koers is painted in the stored theme (AC4)', async ({
  browser,
}) => {
  await storeTheme('rood')
  const context = await browser.newContext({ baseURL: server().base_url })
  let blocked = 0
  await context.route('**/assets/*.js', (route) => {
    blocked += 1
    return route.abort()
  })
  const page = await context.newPage()
  await page.goto('/koers')

  expect(await bodyBackground(page)).toBe(BG.rood)
  expect(blocked).toBeGreaterThan(0)
})
