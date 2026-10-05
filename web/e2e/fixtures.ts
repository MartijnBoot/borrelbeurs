/**
 * The suite's fixtures: the real server global setup started (`baseURL` and
 * the minted keys, read from the file `E2E_SERVER` names) and `loginAs`.
 */
import { test as base, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

export type Role = 'display' | 'bar' | 'admin'

export interface Server {
  base_url: string
  keys: Record<Role, string>
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

export const test = base.extend<{ loginAs: (role: Role) => Promise<void> }>({
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
