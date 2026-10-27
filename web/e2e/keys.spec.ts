/**
 * Short keys at the venue, end to end (B-08: AC2, AC4, AC16, AC17; D-50).
 *
 * The venue serves plain HTTP on a LAN address, where the browser has no
 * `navigator.clipboard`. Chromium maps the made-up host `keys.test` onto
 * loopback, so every page here runs at `http://keys.test:<port>` -- not a secure
 * context, as at `http://192.168.8.10` (B-05 PD16's mapping, as in
 * `payments.spec.ts`). There, "Kopieer" must not throw: it selects the key and
 * says so. A key is typed the way people type what they hear -- lowercase, with
 * spaces, or without dashes -- and still logs in.
 *
 * The spec starts its own `serve.py --empty`. Every context records and blocks
 * any request that leaves its origin, and the flow asserts none did.
 */
import { test, expect, type Browser, type BrowserContext, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { startServer, stopServer, type ServerProcess } from './serverProcess'

const VENUE_HOST = 'keys.test'
const GROUPED = /^[0-9A-HJKMNP-TV-Z]{3}(-[0-9A-HJKMNP-TV-Z]{3}){2}$/

let server: ServerProcess
let venueUrl: string
let adminKey: string
const foreign: string[] = []

test.describe.configure({ mode: 'serial' })
test.use({ launchOptions: { args: [`--host-resolver-rules=MAP ${VENUE_HOST} 127.0.0.1`] } })

test.beforeAll(async () => {
  test.setTimeout(150_000)
  server = await startServer('keys', ['--empty'])
  const written = JSON.parse(readFileSync(server.out, 'utf-8')) as {
    base_url: string
    keys: { admin: string }
  }
  const venue = new URL(written.base_url)
  venue.hostname = VENUE_HOST
  venueUrl = venue.origin
  adminKey = written.keys.admin
})

test.afterAll(async () => {
  await stopServer(server?.child)
})

/** A context at the venue origin that records and aborts every request leaving it. */
async function guarded(browser: Browser): Promise<BrowserContext> {
  const context = await browser.newContext({ baseURL: venueUrl })
  await context.route('**/*', (route) => {
    const url = route.request().url()
    if (new URL(url).origin === venueUrl) return route.continue()
    foreign.push(url)
    return route.abort()
  })
  return context
}

async function typeKey(page: Page, key: string): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Toegangscode').fill(key)
  await page.getByRole('button', { name: 'Inloggen' }).click()
}

const section = (page: Page, name: string) => page.getByRole('region', { name, exact: true })

/** `GET /api/auth/me` from the page itself: Node's request client cannot resolve `keys.test`. */
const me = (page: Page) => page.evaluate(() => fetch('/api/auth/me').then((r) => r.status))

test('a short key is minted, copied by hand, typed loosely and revoked at an HTTP venue', async ({
  browser,
}) => {
  test.setTimeout(120_000)
  const errors: Error[] = []

  // 1. The admin logs in with the CLI-minted key, lowercase and spaced.
  expect(adminKey).toMatch(GROUPED)
  const admin = await (await guarded(browser)).newPage()
  admin.on('pageerror', (error) => errors.push(error))
  await typeKey(admin, adminKey.toLowerCase().replaceAll('-', ' '))
  await admin.waitForURL((url) => url.pathname === '/')
  expect(await admin.evaluate(() => window.isSecureContext)).toBe(false)
  // D-50's premise: no clipboard here. If Chromium ever exposes one, the owner must hear it.
  expect(await admin.evaluate(() => navigator.clipboard === undefined)).toBe(true)

  // 2. A bar key, under Toegangssleutels.
  await admin.goto('/settings')
  const keys = section(admin, 'Toegangssleutels')
  await keys.getByLabel('Rol').selectOption({ label: 'Bar' })
  await keys.getByLabel('Label').fill('Tap 1')
  await keys.getByRole('button', { name: 'Nieuwe sleutel' }).click()
  await expect(keys.getByText('Wordt maar één keer getoond')).toBeVisible()
  const barKey = (await keys.locator('code').textContent()) ?? ''
  expect(barKey).toMatch(GROUPED)

  // 3. "Kopieer" cannot reach a clipboard: no error, the hint, the key selected.
  await keys.getByRole('button', { name: 'Kopieer' }).click()
  await expect(keys.getByRole('status')).toHaveText(
    'Kopiëren lukt hier niet. De sleutel is geselecteerd: kopieer hem zelf.',
  )
  expect(await admin.evaluate(() => window.getSelection()?.toString())).toBe(barKey)
  expect(errors).toEqual([])
  await keys.getByRole('button', { name: 'Sluiten' }).click()

  // 4. Typed without dashes on another device: the bar.
  const tap = await guarded(browser)
  const bar = await tap.newPage()
  await typeKey(bar, barKey.replaceAll('-', ''))
  await bar.waitForURL((url) => url.pathname === '/bar')
  expect(await me(bar)).toBe(200)

  // 5. Revoked: the bar's session is gone on its next request.
  await keys.getByRole('row', { name: /Tap 1/ }).getByRole('button', { name: 'Intrekken' }).click()
  await admin.getByRole('button', { name: 'Bevestigen' }).click()
  await expect(keys.getByRole('row', { name: /Tap 1/ })).not.toContainText('Actief')
  expect(await me(bar)).toBe(401)

  // 6. An old long key is just an invalid one.
  const stranger = await (await guarded(browser)).newPage()
  await typeKey(stranger, 'bb_1_' + 'x'.repeat(43))
  await expect(stranger.getByRole('alert')).toHaveText('Ongeldige toegangscode.')
  await expect(stranger).toHaveURL((url) => url.pathname === '/login')

  expect(errors).toEqual([])
  expect(foreign).toEqual([])
})
