/**
 * The settings screens, in the browser, against the real server (B-12 T14: the
 * spec's flows 1-5, 7 and 8; AC3-AC6, AC14, AC15, AC17, AC19-AC21, AC23-AC25).
 *
 * The spec starts its own `serve.py` with v1's live run (six drinks, Prijsstap
 * 0,10, Vraag/Aanbod off), as `profiles.spec.ts` starts an empty one, so its
 * writes stay out of the shared server's way. The flows run in order on one run.
 */
import { test as base, expect, type Locator, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { startServer, STOP_HOOK_TIMEOUT_MS, stopServer, type ServerProcess } from './serverProcess'

let server: ServerProcess
let baseUrl: string
let keys: { admin: string; display: string }

const test = base.extend({
  // eslint-disable-next-line no-empty-pattern -- Playwright requires the destructuring
  baseURL: async ({}, provide) => provide(baseUrl),
})

test.describe.configure({ mode: 'serial' })

test.beforeAll(async () => {
  test.setTimeout(150_000)
  server = await startServer('settings-screens')
  const written = JSON.parse(readFileSync(server.out, 'utf-8')) as {
    base_url: string
    keys: { admin: string; display: string }
  }
  baseUrl = written.base_url
  keys = written.keys
})

test.afterAll(async () => {
  test.setTimeout(STOP_HOOK_TIMEOUT_MS)
  await stopServer(server?.child)
})

async function login(page: Page, key: string): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Toegangscode').fill(key)
  await page.getByRole('button', { name: 'Inloggen' }).click()
  await page.waitForURL((url) => url.pathname !== '/login')
}

const section = (page: Page, name: string) => page.getByRole('region', { name, exact: true })
const QUESTION = 'Niet-opgeslagen wijzigingen weggooien?'
const leaveDialog = (page: Page) => page.getByRole('dialog', { name: QUESTION })
const NOISE = [
  'Sterkte ruis',
  'Ritme ruis (min)',
  'Extra ruis bij drukte',
  'Reactiesnelheid drukte',
  'Grens ruis',
]

/** Every config or drink PATCH the page sends from now on. */
function watchPatches(page: Page): string[] {
  const sent: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'PATCH') sent.push(new URL(request.url()).pathname)
  })
  return sent
}

/** "Opslaan schakelaars", until its PATCH is answered (the switches show no toast when sent). */
async function saveSwitches(page: Page): Promise<void> {
  const saved = page.waitForResponse(
    (r) => r.request().method() === 'PATCH' && new URL(r.url()).pathname.endsWith('/config'),
  )
  await section(page, 'Vraag/Aanbod').getByRole('button', { name: 'Opslaan schakelaars' }).click()
  expect((await saved).ok()).toBe(true)
}

async function xOf(locator: Locator): Promise<number> {
  return (await locator.boundingBox())!.x
}

async function scrollWidth(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth)
}

test('1. the landing: three tiles, the status line, and "Instellingen" once in the menu (AC4-AC6)', async ({
  page,
}) => {
  await login(page, keys.admin)
  await page.goto('/settings')

  const tiles = page.getByRole('main').getByRole('link')
  await expect(tiles).toHaveCount(3)
  await expect(tiles.nth(0)).toHaveAttribute('href', '/settings/spel')
  await expect(tiles.nth(0)).toContainText('Spelopzet')
  await expect(tiles.nth(1)).toHaveAttribute('href', '/settings/wallets')
  await expect(tiles.nth(1)).toContainText('Mensen en wallets')
  await expect(tiles.nth(2)).toHaveAttribute('href', '/settings/beheer')
  await expect(tiles.nth(2)).toContainText('Beheer')
  await expect(page.getByText(/^Borrel: .+ \(live\)$/)).toBeVisible()

  await page.getByRole('button', { name: 'Menu' }).click()
  const menu = page.getByRole('menu')
  await expect(menu.getByRole('menuitem', { name: 'Instellingen' })).toHaveCount(1)
  for (const path of ['/settings/spel', '/settings/wallets', '/settings/beheer']) {
    await expect(menu.locator(`a[href="${path}"]`)).toHaveCount(0)
  }
})

test('2. Beheer: leaving with an unsaved Drukdrempel asks; saved, it leaves (AC23, AC24)', async ({
  page,
}) => {
  await login(page, keys.admin)
  await page.goto('/settings')
  await page.getByRole('link', { name: /^Beheer/ }).click()
  await expect(page).toHaveURL((url) => url.pathname === '/settings/beheer')
  const global = section(page, 'Globale instellingen')
  const drukdrempel = global.getByRole('textbox', { name: 'Drukdrempel' })
  await expect(drukdrempel).toHaveValue('5')

  await drukdrempel.fill('7')
  // A section link only moves the page (R2): no question.
  await page
    .getByRole('navigation', { name: 'Secties' })
    .getByRole('link', { name: 'Systeemacties' })
    .click()
  await expect(leaveDialog(page)).toHaveCount(0)
  await expect(page).toHaveURL((url) => url.pathname === '/settings/beheer')

  await page.getByRole('link', { name: '← Instellingen' }).click()
  await expect(leaveDialog(page)).toBeVisible()
  await leaveDialog(page).getByRole('button', { name: 'Blijven' }).click()
  await expect(leaveDialog(page)).toHaveCount(0)
  await expect(page).toHaveURL((url) => url.pathname === '/settings/beheer')
  await expect(drukdrempel).toHaveValue('7')

  await global.getByRole('button', { name: 'Opslaan instellingen' }).click()
  await expect(page.getByText('Opgeslagen', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: '← Instellingen' }).click()
  await expect(page).toHaveURL((url) => url.pathname === '/settings')
  await expect(leaveDialog(page)).toHaveCount(0)

  // Back to Beheer through the landing, dirty again: the back button asks too.
  await page.getByRole('link', { name: /^Beheer/ }).click()
  await expect(drukdrempel).toHaveValue('7')
  await drukdrempel.fill('5')
  await page.goBack()
  await expect(leaveDialog(page)).toBeVisible()
  await expect(page).toHaveURL((url) => url.pathname === '/settings/beheer')
  await leaveDialog(page).getByRole('button', { name: 'Weggooien' }).click()
  await expect(page).toHaveURL((url) => url.pathname === '/settings')
})

test('3. Beheer: the five noise fields go with the switch and come back (AC14, AC19)', async ({
  page,
}) => {
  await login(page, keys.admin)
  await page.goto('/settings/beheer')
  const noiseGroup = section(page, 'Globale instellingen').getByRole('region', {
    name: 'Willekeurige ruis',
  })
  const noise = noiseGroup.getByRole('switch', { name: 'Willekeurige ruis' })
  await expect(noise).toHaveAttribute('aria-checked', 'true')
  for (const name of NOISE) await expect(noiseGroup.getByRole('textbox', { name })).toBeVisible()

  await noise.click()
  await expect(noise).toHaveAttribute('aria-checked', 'false')
  for (const name of NOISE) await expect(noiseGroup.getByRole('textbox', { name })).toHaveCount(0)

  // Back on with the keyboard: Enter toggles a switch (AC19).
  await noise.focus()
  await page.keyboard.press('Enter')
  await expect(noise).toHaveAttribute('aria-checked', 'true')
  for (const name of NOISE) await expect(noiseGroup.getByRole('textbox', { name })).toBeVisible()
})

test('4. Vraag/Aanbod: the switch on Beheer decides the table on Spelopzet (AC17)', async ({
  page,
}) => {
  await login(page, keys.admin)
  const note = page.getByText('Vraag/Aanbod staat uit. Zet het aan onder Beheer.', { exact: true })

  // v1's run has it off: Spelopzet shows the sentence, with no link.
  await page.goto('/settings/spel')
  await expect(note).toBeVisible()
  await expect(section(page, 'Vraag/Aanbod').getByRole('table')).toHaveCount(0)
  await expect(section(page, 'Vraag/Aanbod').getByRole('link')).toHaveCount(0)

  await page.goto('/settings/beheer')
  const demand = section(page, 'Vraag/Aanbod')
  await demand.getByRole('switch', { name: 'Verwachte verkoop meetellen' }).click()
  await saveSwitches(page)

  await page.goto('/settings/spel')
  const table = section(page, 'Vraag/Aanbod').getByRole('table', { name: 'Coëfficiënten' })
  await expect(table).toBeVisible()
  await expect(note).toHaveCount(0)
  const patches = watchPatches(page)
  await section(page, 'Vraag/Aanbod').getByRole('button', { name: 'Opslaan coëfficiënten' }).click()
  await expect(page.getByText('Niets te wijzigen', { exact: true })).toBeVisible()
  expect(patches).toEqual([])

  // Off again: the table goes.
  await page.goto('/settings/beheer')
  await demand.getByRole('switch', { name: 'Verwachte verkoop meetellen' }).click()
  await saveSwitches(page)
  await page.goto('/settings/spel')
  await expect(note).toBeVisible()
})

test('5. Spelopzet: a Prijsstap that moves a bound asks first, then stores it (AC15)', async ({
  page,
}) => {
  await login(page, keys.admin)
  await page.goto('/settings/spel')
  const prices = section(page, 'Prijzen')
  const step = prices.getByRole('textbox', { name: 'Prijsstap (€)' })
  await expect(step).toHaveValue('0,1')

  // 0,20: Bier's 1,50 and Wijn's 6,50 are off that grid and move inward.
  await step.fill('0,2')
  await prices.getByRole('button', { name: 'Opslaan prijsstap' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Prijsstap 0,20 opslaan? Deze grenzen schuiven mee:')
  await expect(dialog.getByRole('listitem')).toContainText([
    'Bier: Minimumprijs 1,50 → 1,60',
    'Wijn: Maximumprijs 6,50 → 6,40',
  ])
  await dialog.getByRole('button', { name: 'Opslaan' }).click()
  await expect(page.getByText('Opgeslagen', { exact: true })).toBeVisible()

  await page.reload()
  await expect(step).toHaveValue('0,2')
  const bier = prices.getByRole('group', { name: 'Bier', exact: true })
  await expect(bier.getByLabel('Minimumprijs (€)', { exact: true })).toHaveValue('1,60')
})

test('7. Idle: a drink switched on with Space is saved exactly (AC19, AC21)', async ({ page }) => {
  await login(page, keys.admin)
  await page.goto('/manipulation')
  const down = page.getByRole('group', { name: 'Omlaag bij stilte' })
  const bier = down.getByRole('switch', { name: 'Bier', exact: true })
  await expect(bier).toHaveAttribute('aria-checked', 'false')

  await bier.focus()
  await page.keyboard.press('Space')
  await expect(bier).toHaveAttribute('aria-checked', 'true')
  await page.getByRole('button', { name: 'Opslaan idle' }).click()
  await expect(page.getByText('Opgeslagen', { exact: true })).toBeVisible()

  await page.reload()
  await expect(bier).toHaveAttribute('aria-checked', 'true')
  await expect(down.getByRole('switch', { checked: true })).toHaveCount(1)
})

test('8. a display key at /settings/beheer sees "Geen toegang" (AC3)', async ({ page }) => {
  await login(page, keys.display)
  await page.goto('/settings/beheer')
  await expect(page.getByText('Geen toegang')).toBeVisible()
  await expect(page).toHaveURL((url) => url.pathname === '/settings/beheer')
})

test('at 375 px the tiles stack and no screen scrolls sideways (AC25)', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 })
  await login(page, keys.admin)
  await page.goto('/settings')
  const tiles = page.getByRole('main').getByRole('link')
  await expect(tiles).toHaveCount(3)
  const boxes = await Promise.all([0, 1, 2].map(async (i) => (await tiles.nth(i).boundingBox())!))
  expect(new Set(boxes.map((box) => Math.round(box.x))).size).toBe(1)
  expect(boxes[0].y + boxes[0].height).toBeLessThanOrEqual(boxes[1].y)
  expect(boxes[1].y + boxes[1].height).toBeLessThanOrEqual(boxes[2].y)
  expect(await scrollWidth(page)).toBeLessThanOrEqual(375)

  for (const path of ['/settings/spel', '/settings/wallets', '/settings/beheer']) {
    await page.goto(path)
    await expect(page.getByRole('link', { name: '← Instellingen' })).toBeVisible()
    await expect(page.getByRole('combobox', { name: 'Sectie' })).toBeVisible()
    expect(await scrollWidth(page), path).toBeLessThanOrEqual(375)
  }
})

test('at 1280 px the switches of a section share one x (AC20)', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await login(page, keys.admin)

  await page.goto('/settings/beheer')
  const tracks = section(page, 'Vraag/Aanbod').getByRole('switch')
  await expect(tracks).toHaveCount(2)
  expect(Math.round(await xOf(tracks.nth(0)))).toBe(Math.round(await xOf(tracks.nth(1))))

  // Idle's lists wrap into a grid: within each column the tracks share one x.
  await page.goto('/manipulation')
  for (const list of ['Omlaag bij stilte', 'Omhoog bij stilte']) {
    const switches = page.getByRole('group', { name: list }).getByRole('switch')
    await expect(switches).toHaveCount(6)
    const byColumn = new Map<number, number[]>()
    for (const toggle of await switches.all()) {
      const row = toggle.locator('..')
      const column = Math.round(await xOf(row))
      byColumn.set(column, [...(byColumn.get(column) ?? []), Math.round(await xOf(toggle))])
    }
    expect(byColumn.size).toBeGreaterThan(1)
    for (const xs of byColumn.values()) expect(new Set(xs).size).toBe(1)
  }
})
