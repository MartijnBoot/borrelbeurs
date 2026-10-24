/**
 * B-02's pixel icons in the built app, in Chromium against the real server:
 * the favicon (AC12).
 */
import { readFileSync } from 'node:fs'
import { expect, server, test } from './fixtures'

const FAVICON = readFileSync(new URL('../public/favicon.png', import.meta.url))

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
