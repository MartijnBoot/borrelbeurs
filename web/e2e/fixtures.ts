/**
 * The suite's fixtures: the real server global setup started (`baseURL` and
 * the minted keys, read from the file `E2E_SERVER` names), `loginAs`, and
 * `storeTheme`.
 */
import { test as base, expect, request as http, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

export type Role = 'display' | 'bar' | 'admin' | 'kassa'
/** The roles `serve.py` mints a key for; a kassa key is made by the flow that needs it. */
export type MintedRole = Exclude<Role, 'kassa'>

export interface Server {
  base_url: string
  keys: Record<MintedRole, string>
}

export function server(): Server {
  const file = process.env.E2E_SERVER
  if (file === undefined) throw new Error('E2E_SERVER is unset: run through playwright.config.ts')
  return JSON.parse(readFileSync(file, 'utf-8')) as Server
}

/** Type a key into the login form already on screen and submit it. */
export async function submitKey(page: Page, key: string): Promise<void> {
  await page.getByLabel('Toegangscode').fill(key)
  await page.getByRole('button', { name: 'Inloggen' }).click()
}

export type Preset = 'oudgeld' | 'blauw' | 'groen' | 'paars' | 'rood'

/** `PUT /api/theme` as admin, over HTTP rather than the UI. */
export async function storeTheme(preset: Preset): Promise<void> {
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

export const test = base.extend<{ loginAs: (role: MintedRole) => Promise<void> }>({
  // `provide` is Playwright's `use`, renamed so react-hooks does not take it
  // for a hook.
  // eslint-disable-next-line no-empty-pattern -- Playwright requires the destructuring
  baseURL: async ({}, provide) => provide(server().base_url),
  loginAs: async ({ page }, provide) => {
    await provide(async (role) => {
      await page.goto('/login')
      await submitKey(page, server().keys[role])
      await page.waitForURL((url) => url.pathname !== '/login')
    })
  },
})

export { expect } from '@playwright/test'
