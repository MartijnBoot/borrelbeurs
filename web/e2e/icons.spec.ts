/**
 * B-02's pixel icons in the built app, in Chromium against the real server:
 * the favicon (AC12), an icon as tall as its text (AC5), re-coloured live with
 * the theme (AC6), and no emoji or font symbol on any page under any preset
 * (AC10). The board's crash and price rise come from a mocked `/ws`, as in
 * `board.spec.ts`; everything else is v1's seeded live run. The theme is put
 * back to Blauw afterwards.
 */
import { readFileSync } from 'node:fs'
import type { Browser, Locator, Page } from '@playwright/test'
import { drinks, hello, mockSocket, order, snapshot } from './frames'
import { expect, server, storeTheme, submitKey, test, type Preset, type Role } from './fixtures'

const FAVICON = readFileSync(new URL('../public/favicon.png', import.meta.url))
const TILE = '[class^="_tile_"]' // see board.spec.ts
const PROPAGATION_MS = 2_000

/** SD12's set: any emoji, U+FE0F, and U+25B2, U+25BC, U+25BE, U+26A0 -- as escapes, like the scan's. */
const BANNED = /\p{Extended_Pictographic}|\u{FE0F}|[\u{25B2}\u{25BC}\u{25BE}\u{26A0}]/u

function rgb(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
  return `rgb(${r}, ${g}, ${b})`
}

test.afterAll(async () => {
  await storeTheme('blauw')
})

test('the favicon is linked and served from the app’s own origin (AC12)', async ({
  page,
  request,
}) => {
  const origin = new URL(server().base_url).origin
  await page.goto('/login')

  const href = await page
    .locator('link[rel="icon"]')
    .evaluate((link) => (link as HTMLLinkElement).href)
  expect(href).toBe(`${origin}/favicon.png`)

  const response = await request.get(href)
  expect(response.status()).toBe(200)
  expect(response.headers()['content-type']).toBe('image/png')
  expect(Buffer.compare(await response.body(), FAVICON)).toBe(0)
})

/** The icon's rendered height and its container's computed font size, in px. */
async function heightAndFontSize(container: Locator) {
  return container.evaluate((el) => ({
    icon: el.querySelector('svg')!.getBoundingClientRect().height,
    font: parseFloat(getComputedStyle(el).fontSize),
  }))
}

async function expectAsTallAsItsText(container: Locator) {
  await expect(container.locator('svg')).toBeVisible()
  const { icon, font } = await heightAndFontSize(container)
  expect(Math.abs(icon - font), `icon ${icon}px, font ${font}px`).toBeLessThanOrEqual(1)
}

test.describe('an icon is as tall as its text (AC5)', () => {
  test('the Systeemacties heading on /settings', async ({ page, loginAs }) => {
    await loginAs('admin')
    await page.goto('/settings')
    await expectAsTallAsItsText(page.getByRole('heading', { name: 'Systeemacties' }))
  })

  test('the Bar — Bestellen heading on /bar', async ({ page, loginAs }) => {
    await loginAs('bar')
    await page.goto('/bar')
    await expectAsTallAsItsText(page.getByRole('heading', { name: 'Bar — Bestellen' }))
  })

  test('the crash banner at 1920×1080', async ({ page, loginAs }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await mockSocket(page, () => {
      const now = Date.now()
      return [
        hello(1, now),
        snapshot({
          drinks: drinks(6),
          tsMs: now,
          marketEvents: [
            {
              event_id: 1,
              kind: 'crash',
              drink_ids: [1],
              t_start_ms: now - 1_000,
              t_end_ms: now + 60_000,
            },
          ],
        }),
      ]
    })
    await loginAs('display')
    await expectAsTallAsItsText(page.getByRole('status', { name: 'MARKTCRASH' }))
  })

  test('a tile’s rise icon at 360×800', async ({ page, loginAs }) => {
    await page.setViewportSize({ width: 360, height: 800 })
    const socket = await mockSocket(page, () => [hello(1), snapshot({ drinks: drinks(6) })])
    await loginAs('display')
    const tile = page.locator(TILE).first()
    await expect(tile).toBeVisible()

    socket.send(order(1, 300))

    const rise = tile.getByRole('img', { name: 'stijgt' })
    await expect(rise).toBeVisible()
    await expectAsTallAsItsText(rise.locator('..'))
  })
})

test('a heading icon takes the theme’s text colour live, preset and custom (AC6)', async ({
  page,
  loginAs,
}) => {
  await storeTheme('blauw')
  await loginAs('admin')
  await page.goto('/settings')
  const heading = page.getByRole('heading', { name: 'Globale instellingen' })
  await expect(heading.locator('svg')).toBeVisible()
  const colours = () =>
    heading.evaluate((h) => ({
      icon: getComputedStyle(h.querySelector('svg path')!).fill,
      text: getComputedStyle(h).color,
    }))
  const before = await colours()
  expect(before.icon).toBe(before.text)
  let navigations = 0
  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame()) navigations += 1
  })

  const theme = page.getByRole('region', { name: 'Kleurenschema', exact: true })
  await theme.getByRole('button', { name: 'Oud Geld' }).click()
  const oudgeld = rgb('#e8dfc0')
  await expect.poll(colours, { timeout: PROPAGATION_MS }).toEqual({ icon: oudgeld, text: oudgeld })
  expect(before.icon).not.toBe(oudgeld)

  const custom = '#ff8800'
  await theme.getByLabel('--text', { exact: true }).fill(custom)
  await theme.getByRole('button', { name: 'Opslaan', exact: true }).click()
  await expect
    .poll(colours, { timeout: PROPAGATION_MS })
    .toEqual({ icon: rgb(custom), text: rgb(custom) })
  expect(navigations).toBe(0)
})

/** Every route of AC10 (and the board), as the role that may open it. */
const ROUTES: readonly [string, Role | null][] = [
  ['/', 'admin'],
  ['/koers', 'display'],
  ['/bar', 'bar'],
  ['/settings', 'admin'],
  ['/manipulation', 'admin'],
  ['/analytics', 'admin'],
  ['/login', null],
]

async function pageAs(browser: Browser, role: Role | null): Promise<Page> {
  const context = await browser.newContext({ baseURL: server().base_url })
  const page = await context.newPage()
  if (role === null) return page
  await page.goto('/login')
  await submitKey(page, server().keys[role])
  await page.waitForURL((url) => url.pathname !== '/login')
  return page
}

/** The page's text and the attributes a person can read, each hit as "where: text". */
function bannedOnPage(page: Page): Promise<string[]> {
  return page.evaluate((source) => {
    const banned = new RegExp(source, 'u')
    const hits: string[] = []
    if (banned.test(document.body.innerText)) hits.push(`innerText: ${document.body.innerText}`)
    for (const attr of ['aria-label', 'title', 'alt', 'placeholder']) {
      for (const el of document.querySelectorAll(`[${attr}]`)) {
        const value = el.getAttribute(attr)!
        if (banned.test(value)) hits.push(`${el.tagName} ${attr}: ${value}`)
      }
    }
    return hits
  }, BANNED.source)
}

test('no page shows an emoji or font symbol, under any preset (AC10)', async ({ browser }) => {
  test.setTimeout(120_000)
  const pages = new Map<Role | null, Page>()
  for (const role of new Set(ROUTES.map(([, r]) => r))) pages.set(role, await pageAs(browser, role))
  const presets: Preset[] = ['oudgeld', 'blauw', 'groen', 'paars', 'rood']
  let visited = 0

  for (const preset of presets) {
    await storeTheme(preset)
    for (const [route, role] of ROUTES) {
      const page = pages.get(role)!
      await page.goto(route)
      await expect(page).toHaveURL((url) => url.pathname === route)
      await expect(page.locator('main, form').first()).toBeVisible()
      await page.waitForLoadState('networkidle')
      expect(await bannedOnPage(page), `${route} under ${preset}`).toEqual([])
      visited += 1
    }
  }
  expect(visited).toBe(presets.length * ROUTES.length)
})
