/**
 * The board's shapes in Chromium (AC24, AC25, AC30, AC32, AC34), fed by
 * `frames.ts` through a mocked `/ws`; login and everything over HTTP is the
 * real app. Screenshots are attached per viewport as artifacts, not diffed.
 */
import type { Page, TestInfo } from '@playwright/test'
import { expect, test, type Role } from './fixtures'
import { drinks, hello, mockSocket, newsItem, snapshot, XSS } from './frames'
import type { ServerMessage } from '../src/features/exchange/model/schemas'

// CSS-module classes keep their local name as a prefix in the build
// (`_tile_<hash>_<n>`); `_tile_` does not match `_tiles_`.
const TILE = '[class^="_tile_"]'
const TILES = '[class^="_tiles_"]'

async function openBoard(
  page: Page,
  loginAs: (role: Role) => Promise<void>,
  viewport: { width: number; height: number },
  frames: () => ServerMessage[],
) {
  await page.setViewportSize(viewport)
  const socket = await mockSocket(page, frames)
  await loginAs('display')
  await expect(page).toHaveURL((url) => url.pathname === '/koers')
  return socket
}

async function expectTilesWithCharts(page: Page, n: number) {
  await expect(page.locator(TILE)).toHaveCount(n)
  for (const tile of await page.locator(TILE).all()) {
    await expect(tile.locator('canvas').first()).toBeAttached()
  }
}

async function attachScreenshot(page: Page, testInfo: TestInfo, name: string) {
  await testInfo.attach(name, { body: await page.screenshot(), contentType: 'image/png' })
}

/** `scrollHeight`/`clientHeight` of the document, the shell's main, the board and its grid. */
function heights(page: Page) {
  return page.evaluate(() =>
    [
      document.scrollingElement!,
      document.querySelector('main')!,
      document.querySelector('[class^="_board_"]')!,
      document.querySelector('[class^="_tiles_"]')!,
    ].map((el) => ({ scroll: el.scrollHeight, client: el.clientHeight })),
  )
}

function columns(page: Page) {
  return page
    .locator(TILES)
    .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').length)
}

for (const n of [6, 9]) {
  test(`1920×1080 with ${n} drinks fits one viewport (AC24)`, async ({
    page,
    loginAs,
  }, testInfo) => {
    await openBoard(page, loginAs, { width: 1920, height: 1080 }, () => [
      hello(1),
      snapshot({ drinks: drinks(n) }),
    ])
    await expectTilesWithCharts(page, n)
    for (const { scroll, client } of await heights(page)) {
      expect(scroll).toBeLessThanOrEqual(client)
    }
    await attachScreenshot(page, testInfo, `1920x1080-${n}-drinks`)
  })
}

test('390×844 portrait is one scrolling column (AC25)', async ({ page, loginAs }, testInfo) => {
  await openBoard(page, loginAs, { width: 390, height: 844 }, () => [
    hello(1),
    snapshot({ drinks: drinks(6) }),
  ])
  await expectTilesWithCharts(page, 6)
  expect(await columns(page)).toBe(1)
  const main = await page
    .locator('main')
    .evaluate((el) => ({ scroll: el.scrollHeight, client: el.clientHeight }))
  expect(main.scroll).toBeGreaterThan(main.client)
  await attachScreenshot(page, testInfo, '390x844')
})

// AC25 bounds the landscape case at ≤700 px wide (v1's breakpoint): a
// wider landscape screen, 844×390 say, keeps the three-column grid.
test('690×390 landscape is two columns (AC25)', async ({ page, loginAs }, testInfo) => {
  await openBoard(page, loginAs, { width: 690, height: 390 }, () => [
    hello(1),
    snapshot({ drinks: drinks(6) }),
  ])
  await expectTilesWithCharts(page, 6)
  expect(await columns(page)).toBe(2)
  await attachScreenshot(page, testInfo, '690x390')
})

test('an HTML drink name and news text are literal text (AC32)', async ({ page, loginAs }) => {
  let dialogs = 0
  page.on('dialog', (dialog) => {
    dialogs += 1
    void dialog.dismiss()
  })
  await openBoard(page, loginAs, { width: 1920, height: 1080 }, () => [
    hello(1),
    snapshot({ drinks: drinks(6, [XSS]), news: [newsItem(XSS)] }),
  ])
  await expectTilesWithCharts(page, 6)
  // the tile, the price strip twice over, the news strip
  await expect(page.getByText(XSS, { exact: true })).toHaveCount(4)
  await expect(page.locator('img[src="x"]')).toHaveCount(0)
  expect(dialogs).toBe(0)
})

test('no live run shows the empty state, then a snapshot shows the board in place (AC34)', async ({
  page,
  loginAs,
}) => {
  const socket = await openBoard(page, loginAs, { width: 1920, height: 1080 }, () => [hello(null)])
  await expect(page.getByText('Geen actieve borrel')).toBeVisible()

  let navigations = 0
  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame()) navigations += 1
  })
  socket.send(snapshot({ drinks: drinks(6) }))

  await expectTilesWithCharts(page, 6)
  await expect(page.getByText('Geen actieve borrel')).toHaveCount(0)
  expect(navigations).toBe(0)
  await expect(page).toHaveURL((url) => url.pathname === '/koers')
})

test('a crash ends at t_end_ms on server time, with the client 5 min slow and no end frame (AC30)', async ({
  page,
  loginAs,
}) => {
  const SLOW_MS = 5 * 60_000
  await page.clock.install({ time: Date.now() - SLOW_MS })
  let tEnd = 0
  await openBoard(page, loginAs, { width: 1920, height: 1080 }, () => {
    const now = Date.now() // this process plays the server
    tEnd = now + 6_000
    return [
      hello(1, now),
      snapshot({
        drinks: drinks(6),
        tsMs: now,
        marketEvents: [
          { event_id: 1, kind: 'crash', drink_ids: [1], t_start_ms: now - 1_000, t_end_ms: tEnd },
        ],
      }),
    ]
  })

  const banner = page.locator('.market-banner')
  await expect(banner).toHaveText('⚠ MARKTCRASH')
  await page.waitForTimeout(Math.max(0, tEnd - 1_000 - Date.now()))
  await expect(banner).toBeVisible()

  await expect(banner).toHaveCount(0, { timeout: tEnd + 1_500 - Date.now() })
  expect(Date.now() - tEnd).toBeLessThanOrEqual(1_500)
})
