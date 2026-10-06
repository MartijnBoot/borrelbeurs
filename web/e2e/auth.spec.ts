/**
 * Login, role routing and a lost session in a real browser against the real
 * app (AC20-AC23, PD10).
 */
import type { WebSocketRoute } from '@playwright/test'
import { expect, server, submitKey, test, type Role } from './fixtures'

// Phase 3 SD2's allowed routes per role, in order, as the nav labels them.
const NAV: Record<Role, string[]> = {
  display: ['Live koersbord'],
  bar: ['Bar', 'Spel mechanica'],
  admin: ['Home', 'Live koersbord', 'Bar', 'Spel mechanica', 'Instellingen'],
}

const LANDING: Record<Role, string> = { display: '/koers', bar: '/bar', admin: '/' }

const ROLES: Role[] = ['display', 'bar', 'admin']

test.describe('login (AC21)', () => {
  for (const role of ROLES) {
    test(`${role} lands on ${LANDING[role]}`, async ({ page, loginAs }) => {
      await loginAs(role)
      await expect(page).toHaveURL((url) => url.pathname === LANDING[role])
    })
  }

  test('a wrong key says so, and stays on the login page', async ({ page }) => {
    await page.goto('/login')
    await submitKey(page, 'bb_nosuchkey_nosuchsecret')
    await expect(page.getByRole('alert')).toHaveText('Ongeldige toegangscode.')
    await expect(page).toHaveURL((url) => url.pathname === '/login')
  })
})

test.describe('navigation (AC22, AC23)', () => {
  for (const role of ROLES) {
    test(`${role}'s menu lists exactly its routes`, async ({ page, loginAs }) => {
      await loginAs(role)
      await page.getByRole('button', { name: 'Menu' }).click()
      await expect(page.getByRole('menuitem')).toHaveText([...NAV[role], 'Uitloggen'])
    })
  }

  test('display at /settings sees "Geen toegang"', async ({ page, loginAs }) => {
    await loginAs('display')
    await page.goto('/settings')
    await expect(page.getByText('Geen toegang')).toBeVisible()
    await expect(page).toHaveURL((url) => url.pathname === '/settings')
  })

  test('bar at /bar sees the bar page (Phase 5)', async ({ page, loginAs }) => {
    await loginAs('bar')
    await expect(page).toHaveURL((url) => url.pathname === '/bar')
    await expect(page.getByRole('heading', { name: '🍺 Bar — Bestellen' })).toBeVisible()
  })
})

test('a session lost while on /koers goes to login and back (AC20, PD10)', async ({
  page,
  loginAs,
}) => {
  const sockets: WebSocketRoute[] = []
  await page.routeWebSocket('**/ws', (ws) => {
    sockets.push(ws)
    ws.connectToServer()
  })

  await loginAs('display')
  await expect(page).toHaveURL((url) => url.pathname === '/koers')
  await expect.poll(() => sockets.length).toBeGreaterThan(0)

  // The cookie goes, then the socket: the browser sees a close it cannot
  // tell from a network failure, and the offline poll's 401 is what routes it.
  await page.context().clearCookies()
  await sockets.at(-1)!.close({ code: 1001 })

  await expect(page).toHaveURL((url) => url.pathname + url.search === '/login?next=%2Fkoers')
  await submitKey(page, server().keys.display)
  await expect(page).toHaveURL((url) => url.pathname === '/koers')
})
