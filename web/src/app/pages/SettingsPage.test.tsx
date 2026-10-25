// @vitest-environment jsdom
// `/settings` (Phase 6 T24: SD25, PD13): eleven sections, in v1's sidebar order with
// B-04's Profielen after Globale instellingen (SD10) and B-05's Wallets last (SD16),
// each listed in the section
// navigation. B-01 T11: exactly the 21 settings
// explanations get an (i), section by section (AC8-AC10).
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { settingsExplanations as explanations } from '../../features/settings'
import { SettingsPage } from './SettingsPage'
import { settingNames } from './settingNames'

const SECTIONS = [
  'Borrel',
  'Systeemacties',
  'Globale instellingen',
  'Profielen',
  'Kleurenschema',
  'Afbeeldingen',
  'Drankjes beheren',
  'Min/Max/Startprijs',
  'Vraag/Aanbod',
  'Toegangssleutels',
  'Wallets',
]

/** The one decorative pixel icon before the name (B-02 SD4, AC7, AC8), or `null` without one. */
function leadingIcon(element: HTMLElement): SVGElement | null {
  const icons = element.querySelectorAll('svg')
  if (icons.length === 0) return null
  expect(icons).toHaveLength(1)
  expect(icons[0].getAttribute('aria-hidden')).toBe('true')
  expect(element.firstChild).toBe(icons[0])
  return icons[0]
}

beforeEach(() => {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { code: 'no_current_run', message: 'none' } }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('SettingsPage', () => {
  it('lists the eleven sections in the nav, each with its own heading', async () => {
    render(<SettingsPage />)
    await act(async () => {})

    const nav = screen.getByRole('navigation', { name: 'Secties' })
    expect(
      within(nav)
        .getAllByRole('link')
        .map((a) => a.textContent),
    ).toEqual(SECTIONS)
    for (const label of SECTIONS) {
      expect(screen.getByRole('heading', { level: 2, name: label })).toBeTruthy()
    }
  })

  it('puts one pixel icon before each name but Borrel, in the heading and the link (B-02)', async () => {
    render(<SettingsPage />)
    await act(async () => {})

    const nav = screen.getByRole('navigation', { name: 'Secties' })
    for (const label of SECTIONS) {
      const heading = screen.getByRole('heading', { level: 2, name: label })
      const link = within(nav).getByRole('link', { name: label })
      for (const element of [heading, link]) {
        expect(element.textContent).toBe(label)
        if (label === 'Borrel') expect(leadingIcon(element)).toBeNull()
        else expect(leadingIcon(element)).not.toBeNull()
      }
    }
  })

  it('the narrow-screen "Sectie" select holds the plain names, text only (SD4)', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: true,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }))
    render(<SettingsPage />)
    await act(async () => {})

    const select = screen.getByRole('combobox', { name: 'Sectie' }) as HTMLSelectElement
    expect([...select.options].map((o) => o.textContent)).toEqual(SECTIONS)
    expect(select.querySelectorAll('svg')).toHaveLength(0)
  })

  it('every section is built: none says "Nog niet beschikbaar"', async () => {
    render(<SettingsPage />)
    await act(async () => {})

    expect(screen.queryAllByText('Nog niet beschikbaar')).toHaveLength(0)
  })
})

const DRINK = {
  slot: 0,
  active: true,
  p_min_cents: 150,
  p0_cents: 260,
  p_max_cents: 500,
  bar_price_cents: 260,
  a: 10,
  d: 0.6,
  s0: 8,
  c: 0.4,
}

const CONFIG = {
  revision: 3,
  run: { run_id: 7, name: 'Vrijmibo', status: 'live', candle_interval_s: 60 },
  params: {
    step_quant: 0.1,
    eta: 0.8,
    K: 5,
    lambda_orders: 1.5,
    alpha_price: 0,
    phi_persist: 0.1,
    decay_rho: 0.98,
    history_window_minutes: 15,
    refresh_minutes: 0.2,
    idle_decay_minutes: 0.1,
    idle_rise_minutes: 0.1,
    idle_strength: 1.5,
    idle_rise_strength: 1.5,
    idle_targets: [],
    idle_rise_targets: [],
    demand_enabled: false,
    auto_calibrate_s0: false,
    bm_enabled: true,
    bm_sigma_y: 0.18,
    bm_dt_minutes: 1,
    flow_vol_amp: 0.7,
    flow_beta: 0.25,
    y_clip: 6,
  },
  drinks: [
    { ...DRINK, drink_id: 11, name: 'Bier' },
    { ...DRINK, drink_id: 12, slot: 1, name: 'Wijn' },
    { ...DRINK, drink_id: 13, slot: 2, name: 'Oud', active: false },
  ],
}

const KEY = {
  key_id: 1,
  label: 'Tap 1',
  role: 'bar',
  created_at: '2026-10-01T10:00:00Z',
  last_used_at: null,
  revoked: false,
}

const SERVED: Readonly<Record<string, unknown>> = {
  '/api/runs/current': { run_id: 7, name: 'Vrijmibo', status: 'live' },
  '/api/runs/7/config': CONFIG,
  '/api/keys': [KEY],
  '/api/analytics/runs': [],
  '/api/profiles': [],
  '/api/admin/wallets': { outstanding_cents: 0, per_borrel: [], wallets: [] },
  '/api/admin/wallet-settings': { signup_code: null, unfunded_days: 30, inactive_months: 12 },
}

const NAMES = new Set(Object.values(explanations).map((entry) => entry.name))
const info = (scope: HTMLElement) => within(scope).queryAllByRole('button', { name: /^Uitleg: / })

async function openWithLiveRun() {
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(SERVED[path] ?? { error: { code: 'not_found', message: path } }),
          {
            status: path in SERVED ? 200 : 404,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      ),
    ),
  )
  render(<SettingsPage />)
  for (let i = 0; i < 4; i += 1) await act(async () => {})
}

describe('SettingsPage: the explanations (B-01)', () => {
  it('every (i) names one of E1-E20, E33 or E34-E39 (AC10)', async () => {
    await openWithLiveRun()
    const names = info(document.body).map((b) => b.getAttribute('aria-label')!.slice(8))
    expect(names.length).toBeGreaterThan(0)
    expect(names.filter((name) => !NAMES.has(name))).toEqual([])
  })

  it.each([
    ['Globale instellingen', 10 + 6],
    ['Vraag/Aanbod', 6],
    ['Min/Max/Startprijs', 3 * 2],
    ['Drankjes beheren', 8 + 1 * 2],
    ['Systeemacties', 1],
    ['Borrel', 0],
    ['Profielen', 0],
    ['Kleurenschema', 0],
    ['Afbeeldingen', 0],
    ['Toegangssleutels', 0],
    ['Wallets', 0],
  ])('%s has %i (i) with two drinks (AC10)', async (section, count) => {
    await openWithLiveRun()
    expect(info(screen.getByRole('region', { name: section }))).toHaveLength(count)
  })

  it('a field shown in several places opens the same explanation everywhere (AC9)', async () => {
    await openWithLiveRun()
    for (const key of ['a', 'd', 's0', 'c', 'p_min_cents', 'p0_cents', 'p_max_cents'] as const) {
      expectSameEverywhere(explanations[key], 2)
    }
    expectSameEverywhere(explanations.bar_price_cents, 3)
  })
})

function expectSameEverywhere(entry: { name: string; paragraphs: string[] }, places: number) {
  const buttons = screen.getAllByRole('button', { name: `Uitleg: ${entry.name}` })
  expect(buttons.length).toBeGreaterThanOrEqual(places)
  for (const button of buttons) {
    fireEvent.click(button)
    const popup = screen.getByRole('note', { name: entry.name })
    expect([...popup.querySelectorAll('p')].map((p) => p.textContent)).toEqual([
      entry.name,
      ...entry.paragraphs,
    ])
    fireEvent.keyDown(document, { key: 'Escape' })
  }
}

// B-04 SD1's 22 under their wire names.
const PROFILE_FIELDS = [
  'step_quant',
  'eta',
  'K',
  'lambda_orders',
  'alpha_price',
  'phi_persist',
  'decay_rho',
  'history_window_minutes',
  'refresh_minutes',
  'candle_interval_s',
  'bm_enabled',
  'bm_sigma_y',
  'bm_dt_minutes',
  'flow_vol_amp',
  'flow_beta',
  'y_clip',
  'demand_enabled',
  'auto_calibrate_s0',
  'idle_decay_minutes',
  'idle_strength',
  'idle_rise_minutes',
  'idle_rise_strength',
]

describe('SettingsPage: Profielen (B-04)', () => {
  it('has the floppy icon in its heading, after Globale instellingen (AC19)', async () => {
    render(<SettingsPage />)
    await act(async () => {})

    const heading = screen.getByRole('heading', { level: 2, name: 'Profielen' })
    expect(leadingIcon(heading)).not.toBeNull()
    expect(document.getElementById('profielen')).not.toBeNull()
  })

  it.each(PROFILE_FIELDS)('names %s for a 422 by its setting name (AC23)', (field) => {
    expect(settingNames[field]?.trim()).toBeTruthy()
    expect(settingNames[field]).not.toBe(field)
  })
})

describe('SettingsPage: Wallets (B-05 SD16, AC34)', () => {
  it('is the last section, anchored #wallets, with the wallet icon in heading and link', async () => {
    await openWithLiveRun()
    const nav = screen.getByRole('navigation', { name: 'Secties' })
    const links = within(nav).getAllByRole('link')
    const last = links[links.length - 1]
    expect(last.textContent).toBe('Wallets')
    expect(last.getAttribute('href')).toBe('#wallets')
    const heading = screen.getByRole('heading', { level: 2, name: 'Wallets' })
    expect(leadingIcon(heading)).not.toBeNull()
    expect(leadingIcon(last)).not.toBeNull()
    const region = screen.getByRole('region', { name: 'Wallets' })
    expect(within(region).getByText('Aanmelden is gesloten.')).toBeTruthy()
    expect(within(region).getByText('Nog geen wallets')).toBeTruthy()
  })
})
