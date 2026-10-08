/**
 * The board with no internet (AC1, D-13) and a lost connection (AC16), in
 * Chromium against the real app.
 */
import type { Page, WebSocketRoute } from '@playwright/test'
import { expect, server, test } from './fixtures'

const TILE = '[class^="_tile_"]' // see board.spec.ts
const BANNER = 'Verbinding verbroken — opnieuw verbinden…'
const STATE = '/api/state'

/** The body's theme font: requested, loaded, and passing `document.fonts.check`. */
async function expectThemeFontLoaded(page: Page) {
  const font = await page.evaluate(async () => {
    await document.fonts.ready
    const name = getComputedStyle(document.body).fontFamily.includes('EB Garamond')
      ? 'EB Garamond'
      : 'Inter'
    let loaded = false
    document.fonts.forEach((face) => {
      if (face.family.replace(/["']/g, '') === name && face.status === 'loaded') loaded = true
    })
    return { name, loaded, check: document.fonts.check(`16px "${name}"`) }
  })
  expect(font).toEqual({ name: font.name, loaded: true, check: true })
}

test('every Phase 4 page works with every non-origin request blocked (AC1)', async ({
  page,
  context,
  loginAs,
}) => {
  const origin = new URL(server().base_url).origin
  const foreign: string[] = []
  await context.route('**/*', (route) => {
    const url = route.request().url()
    if (new URL(url).origin === origin) return route.continue()
    foreign.push(url)
    return route.abort()
  })

  await page.goto('/login')
  await expectThemeFontLoaded(page)

  await loginAs('admin') // lands on `/`, a placeholder
  await expect(page.getByText('Nog niet beschikbaar')).toBeVisible()
  await expectThemeFontLoaded(page)

  await page.goto('/koers')
  await expect(page.locator(TILE)).toHaveCount(6) // v1's live run
  for (const tile of await page.locator(TILE).all()) {
    await expect(tile.locator('canvas').first()).toBeAttached()
  }
  await expectThemeFontLoaded(page)

  await page.goto('/settings')
  // Phase 6 SD25 renamed the theme section after v1's sidebar.
  await expect(page.getByRole('heading', { name: '🎨 Kleurenschema' })).toBeVisible()
  await expectThemeFontLoaded(page)

  expect(foreign).toEqual([])
})

test('a lost socket shows the banner and polls every 5 s; reconnecting ends both (AC16)', async ({
  page,
  loginAs,
}) => {
  test.setTimeout(90_000)
  let severed = false
  let current: WebSocketRoute | undefined
  await page.routeWebSocket('**/ws', (ws) => {
    // A refused reconnect: the page sees an error and 1006, never an open.
    if (severed) return ws.close({ code: 1011 })
    current = ws
    ws.connectToServer()
  })
  await loginAs('display')
  await expect(page.locator(TILE)).toHaveCount(6)

  const polls: number[] = []
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === STATE) polls.push(Date.now())
  })
  severed = true
  await current!.close({ code: 1001 })

  await expect(page.getByText(BANNER)).toBeVisible()
  await page.waitForTimeout(11_000)
  // once at once, then every 5 s
  expect(polls.length).toBeGreaterThanOrEqual(3)
  for (let i = 1; i < polls.length; i++) {
    expect(polls[i] - polls[i - 1]).toBeGreaterThan(4_500)
    expect(polls[i] - polls[i - 1]).toBeLessThan(5_500)
  }

  severed = false
  await expect(page.getByText(BANNER)).toHaveCount(0, { timeout: 20_000 })
  const polled = polls.length
  await page.waitForTimeout(6_000)
  expect(polls.length).toBe(polled)
})
