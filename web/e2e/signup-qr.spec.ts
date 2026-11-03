/**
 * The sign-up QR code end to end, at an insecure origin (B-09 T4: AC9, and end to
 * end AC1, AC2, AC4, AC6, AC8, AC10, AC11, AC12, AC13, AC14; plan PD7).
 *
 * Chromium maps the made-up host `signup.test` onto loopback, so the admin page
 * runs at `http://signup.test:<port>` -- not a secure context, as at
 * `http://192.168.8.10` -- while the server is the real one (`wallets.spec.ts`).
 * It runs on the shared server: no other spec there sets a sign-up code, and
 * this one clears it first and leaves sign-up closed.
 *
 * The downloaded PNG is decoded by the browser itself (`createImageBitmap`, an
 * `OffscreenCanvas`), and its pixels are read in Node with `jsqr`, so no PNG
 * library is needed. The loopback check runs while a code is still saved,
 * since the preview only shows then, and before the closing step.
 */
import { request as http, type Browser, type Page } from '@playwright/test'
import jsQR from 'jsqr'
import { readFile } from 'node:fs/promises'
import { expect, server, submitKey, test } from './fixtures'

const SIGNUP_HOST = 'signup.test'
const HINT =
  'Open deze pagina via het netwerkadres (bijv. http://192.168.8.10/) om de QR-code te downloaden.'

const loopbackUrl = () => server().base_url
const signupUrl = () => {
  const url = new URL(loopbackUrl())
  url.hostname = SIGNUP_HOST
  return url.origin
}
const foreign: string[] = []

test.describe.configure({ mode: 'serial' })
test.use({ launchOptions: { args: [`--host-resolver-rules=MAP ${SIGNUP_HOST} 127.0.0.1`] } })

/** `PUT /api/admin/wallet-settings` with no code, over HTTP: the starting state. */
async function closeSignup(): Promise<void> {
  const base = loopbackUrl()
  const api = await http.newContext({ baseURL: base, extraHTTPHeaders: { Origin: base } })
  try {
    expect((await api.post('/api/auth/login', { data: { key: server().keys.admin } })).ok()).toBe(
      true,
    )
    const stored = await api.get('/api/admin/wallet-settings')
    expect(stored.ok()).toBe(true)
    const settings = { ...(await stored.json()), signup_code: null }
    expect((await api.put('/api/admin/wallet-settings', { data: settings })).ok()).toBe(true)
  } finally {
    await api.dispose()
  }
}

/** An admin page at `baseURL`, in a context that aborts any request leaving its origin. */
async function adminSettings(browser: Browser, baseURL: string): Promise<Page> {
  const context = await browser.newContext({ baseURL, acceptDownloads: true })
  const origin = new URL(baseURL).origin
  await context.route('**/*', (route) => {
    const url = route.request().url()
    if (new URL(url).origin === origin) return route.continue()
    foreign.push(url)
    return route.abort()
  })
  const page = await context.newPage()
  await page.goto('/login')
  await submitKey(page, server().keys.admin)
  await page.waitForURL((url) => url.pathname !== '/login')
  await page.goto('/settings/wallets') // B-12 SD3: Aanmeldcode is on Mensen en wallets
  return page
}

const signup = (page: Page) => page.getByRole('region', { name: 'Aanmeldcode', exact: true })
const preview = (page: Page) => signup(page).getByRole('img', { name: 'Aanmeld-QR-code' })
const dialog = (page: Page) => page.getByRole('dialog')

async function saveCode(page: Page, code: string): Promise<void> {
  await signup(page).getByRole('textbox', { name: 'Aanmeldcode' }).fill(code)
  await signup(page).getByRole('button', { name: 'Opslaan' }).click()
}

async function download(page: Page, name: string) {
  const [file] = await Promise.all([
    page.waitForEvent('download'),
    signup(page).getByRole('button', { name }).click(),
  ])
  return { name: file.suggestedFilename(), bytes: await readFile(await file.path()) }
}

/** The PNG decoded by the browser, its RGBA pixels handed back as base64. */
async function pngPixels(page: Page, png: Buffer) {
  const { width, height, rgba } = await page.evaluate(async (base64) => {
    const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0))
    const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }))
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height)
    const context = canvas.getContext('2d')!
    context.drawImage(bitmap, 0, 0)
    const { data } = context.getImageData(0, 0, bitmap.width, bitmap.height)
    let binary = ''
    for (let i = 0; i < data.length; i += 0x8000) {
      binary += String.fromCharCode(...data.subarray(i, i + 0x8000))
    }
    return { width: bitmap.width, height: bitmap.height, rgba: btoa(binary) }
  }, png.toString('base64'))
  return { width, height, data: new Uint8ClampedArray(Buffer.from(rgba, 'base64')) }
}

test.beforeAll(async () => {
  await closeSignup()
})

// The server is shared: a failure midway must not leave a code saved (PD7).
test.afterAll(async () => {
  await closeSignup()
})

test('the sign-up QR code downloads, decodes and survives code changes, over plain HTTP', async ({
  browser,
}) => {
  test.setTimeout(120_000)
  const admin = await adminSettings(browser, signupUrl())
  const errors: Error[] = []
  admin.on('pageerror', (error) => errors.push(error))

  // 1. Not a secure context; no code: closed, no preview, no buttons (AC2).
  expect(await admin.evaluate(() => window.isSecureContext)).toBe(false)
  await expect(signup(admin).getByText('Aanmelden is gesloten.')).toBeVisible()
  await expect(preview(admin)).toHaveCount(0)
  await expect(signup(admin).getByRole('button', { name: /^Download/ })).toHaveCount(0)

  // 2. Save BORREL: the link, the preview and both buttons (AC1). No code was saved: no dialog.
  await saveCode(admin, 'BORREL')
  const link = `${signupUrl()}/speler?code=BORREL`
  await expect(signup(admin).getByText(link, { exact: true })).toBeVisible()
  await expect(preview(admin)).toBeVisible()
  await expect(signup(admin).getByRole('button', { name: 'Download PNG' })).toBeEnabled()
  await expect(signup(admin).getByRole('button', { name: 'Download SVG' })).toBeEnabled()

  // 3. Both downloads complete under the SD8 names, and nothing throws (AC8, AC9).
  const port = new URL(signupUrl()).port
  const png = await download(admin, 'Download PNG')
  expect(png.name).toBe(`aanmelden-signup.test-${port}-BORREL.png`)
  const pixels = await pngPixels(admin, png.bytes)
  expect(jsQR(pixels.data, pixels.width, pixels.height)?.data).toBe(link) // AC4
  expect(pixels.width).toBe(pixels.height) // AC6
  expect(pixels.width).toBeLessThanOrEqual(1024)
  const alphas = new Set<number>()
  const colours = new Set<string>()
  for (let i = 0; i < pixels.data.length; i += 4) {
    alphas.add(pixels.data[i + 3])
    colours.add(`${pixels.data[i]},${pixels.data[i + 1]},${pixels.data[i + 2]}`)
  }
  expect(alphas).toEqual(new Set([255]))
  expect(colours).toEqual(new Set(['0,0,0', '255,255,255']))

  const svg = await download(admin, 'Download SVG')
  expect(svg.name).toBe(`aanmelden-signup.test-${port}-BORREL.svg`)
  const svgText = svg.bytes.toString('utf-8')
  expect(svgText.startsWith('<svg xmlns=')).toBe(true)
  expect(svgText).not.toContain('<script')
  expect(svgText).not.toContain('href')
  expect(errors).toEqual([])

  // 4. The decoded link opens the player page with the code filled in.
  const player = await (await browser.newContext()).newPage()
  await player.goto(link)
  await expect(player.getByLabel('Aanmeldcode')).toHaveValue('BORREL')
  await player.context().close()

  // 5. A case-only change saves at once (AC14); a different code asks, "Annuleren" keeps
  //    the saved one (AC13), "Wijzigen" saves it and the preview changes (AC11).
  await saveCode(admin, 'borrel')
  await expect(
    signup(admin).getByText(`${signupUrl()}/speler?code=borrel`, { exact: true }),
  ).toBeVisible()
  await expect(dialog(admin)).toHaveCount(0)
  const before = await preview(admin).innerHTML()

  await saveCode(admin, 'ANDERS')
  await expect(dialog(admin)).toContainText(
    "Aanmeldcode wijzigen? Geprinte QR-codes met 'borrel' werken dan niet meer.",
  )
  await dialog(admin).getByRole('button', { name: 'Annuleren' }).click()
  await expect(dialog(admin)).toHaveCount(0)
  await expect(
    signup(admin).getByText(`${signupUrl()}/speler?code=borrel`, { exact: true }),
  ).toBeVisible()
  await expect(signup(admin).getByRole('textbox', { name: 'Aanmeldcode' })).toHaveValue('ANDERS')
  expect(await preview(admin).innerHTML()).toBe(before)

  await signup(admin).getByRole('button', { name: 'Opslaan' }).click()
  await dialog(admin).getByRole('button', { name: 'Wijzigen' }).click()
  await expect(
    signup(admin).getByText(`${signupUrl()}/speler?code=ANDERS`, { exact: true }),
  ).toBeVisible()
  expect(await preview(admin).innerHTML()).not.toBe(before)

  // The loopback address, while a code is saved: the preview shows, the buttons are
  // disabled and the hint says where to go instead (AC10). Nothing is saved here.
  const local = await adminSettings(browser, loopbackUrl())
  expect(new URL(local.url()).hostname).toBe('127.0.0.1')
  await expect(preview(local)).toBeVisible()
  await expect(signup(local).getByRole('button', { name: 'Download PNG' })).toBeDisabled()
  await expect(signup(local).getByRole('button', { name: 'Download SVG' })).toBeDisabled()
  await expect(signup(local).getByText(HINT)).toBeVisible()
  await local.context().close()
  await expect(signup(admin).getByText(HINT)).toHaveCount(0)

  // 6. "Wissen" asks to close sign-up; its "Wissen" closes it and the buttons go (AC12, AC2).
  await signup(admin).getByRole('button', { name: 'Wissen' }).click()
  await expect(dialog(admin)).toContainText(
    "Aanmelden sluiten? Geprinte QR-codes met 'ANDERS' werken dan niet meer.",
  )
  await dialog(admin).getByRole('button', { name: 'Wissen' }).click()
  await expect(signup(admin).getByText('Aanmelden is gesloten.')).toBeVisible()
  await expect(preview(admin)).toHaveCount(0)
  await expect(signup(admin).getByRole('button', { name: /^Download/ })).toHaveCount(0)

  expect(errors).toEqual([])
  expect(foreign).toEqual([])
  await admin.context().close()
})
