// @vitest-environment jsdom
// The three settings screens (B-12 T5: SD1, SD3, SD8, SD12; AC8, AC9, AC22, AC23):
// each screen's sections in order with their B-02 icons, the section navigation
// (links, or the narrow select), the (i) per section (B-01), "← Instellingen",
// and the leave guard at screen level. Carried over from the old one-page test
// (Phase 6 T24, B-01 T11, B-04, B-05), per screen.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Route, Routes, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PixelIcon, type PixelIconName } from '../../components/ui/PixelIcon'
import { SessionProvider } from '../../features/auth'
import { settingsExplanations as explanations, SettingsLayout } from '../../features/settings'
import { UnsavedEditsProvider } from '../../lib/unsavedEdits'
import { LeaveGuard } from '../LeaveGuard'
import { renderInDataRouter } from '../testRouter'
import { SERVED, stubNarrow, stubServer } from './settingsFixture'
import { settingNames } from './settingNames'
import { BeheerPage, SettingsScreen, SpelopzetPage, WalletsScreenPage } from './SettingsScreens'

interface Screen {
  path: string
  page: React.JSX.Element
  /** Each section's name and B-02 icon (`null`: none), in order (SD12). */
  sections: readonly (readonly [string, PixelIconName | null])[]
}

const SCREENS: Readonly<Record<string, Screen>> = {
  Spelopzet: {
    path: '/settings/spel',
    page: <SpelopzetPage />,
    sections: [
      ['Borrel', null],
      ['Profielen', 'floppy'],
      ['Drankjes beheren', 'cup'],
      ['Prijzen', 'padlock'],
      ['Vraag/Aanbod', 'chart'],
      ['Kleurenschema', 'palette'],
      ['Afbeeldingen', 'picture'],
    ],
  },
  'Mensen en wallets': {
    path: '/settings/wallets',
    page: <WalletsScreenPage />,
    sections: [
      ['Betalen', null],
      ['Wallets', 'wallet'],
    ],
  },
  Beheer: {
    path: '/settings/beheer',
    page: <BeheerPage />,
    sections: [
      ['Globale instellingen', 'gear'],
      ['Vraag/Aanbod', 'chart'],
      ['Toegangssleutels', 'key'],
      ['Systeemacties', 'broom'],
    ],
  },
}

/** The (i) per section with the fixture's two active drinks (B-01 AC10). */
const INFO_COUNTS: Readonly<Record<string, number>> = {
  Borrel: 0,
  Profielen: 0,
  'Drankjes beheren': 8 + 1 * 2,
  Prijzen: 1 + 3 * 2,
  'Vraag/Aanbod': 4, // Spelopzet: the table's four column headers (Beheer's two below)
  Kleurenschema: 0,
  Afbeeldingen: 0,
  Betalen: 2,
  Wallets: 0,
  'Globale instellingen': 9 + 6,
  Toegangssleutels: 0,
  Systeemacties: 1,
}

const NAMES = new Set(Object.values(explanations).map((entry) => entry.name))
const info = (scope: HTMLElement) => within(scope).queryAllByRole('button', { name: /^Uitleg: / })
const names = (screenName: string) => SCREENS[screenName].sections.map(([name]) => name)

function Where() {
  const location = useLocation()
  return <output data-testid="where">{location.pathname}</output>
}

const where = () => screen.getByTestId('where').textContent

// B-13: the session the screens read, as `GET /api/auth/me` answers it.
const ROUTES: Readonly<Record<string, string[]>> = {
  admin: ['/settings', '/settings/spel', '/settings/wallets', '/settings/beheer'],
  organiser: ['/settings', '/settings/spel', '/settings/wallets'],
  kassa: ['/kassa', '/settings', '/settings/wallets'],
}

/** The fixture's server, answering `/api/auth/me` for `role`. */
function serveAs(role: string, served: Readonly<Record<string, unknown>> = SERVED) {
  const me = { role, label: `${role} key`, allowed_routes: ROUTES[role] }
  stubServer({ ...served, '/api/auth/me': me })
}

/** A screen inside the shell's guard (PD2, PD3), with the landing beside it. */
async function open(screenName: string) {
  const { path, page } = SCREENS[screenName]
  renderInDataRouter(
    <SessionProvider>
      <UnsavedEditsProvider>
        <LeaveGuard>
          <Routes>
            <Route path={path} element={page} />
            <Route path="/settings" element={<p>Landing</p>} />
          </Routes>
          <Where />
        </LeaveGuard>
      </UnsavedEditsProvider>
    </SessionProvider>,
    [path],
  )
  for (let i = 0; i < 4; i += 1) await act(async () => {})
}

/** The one decorative pixel icon before the name (B-02 SD4, AC7, AC8), or `null` without one. */
function leadingIcon(element: HTMLElement): string | null {
  const icons = element.querySelectorAll('svg')
  if (icons.length === 0) return null
  expect(icons).toHaveLength(1)
  expect(icons[0].getAttribute('aria-hidden')).toBe('true')
  expect(element.firstChild).toBe(icons[0])
  return icons[0].outerHTML
}

const iconMarkup = (name: PixelIconName) => renderToStaticMarkup(<PixelIcon name={name} />)

beforeEach(() => {
  stubNarrow(false)
  serveAs('admin')
})

afterEach(cleanup)

describe.each(Object.keys(SCREENS))('%s', (screenName) => {
  const { sections } = SCREENS[screenName]
  const multi = sections.length > 1

  it('shows its sections in order, each under its own heading, and nothing else (AC8, AC9)', async () => {
    await open(screenName)
    expect(
      screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent),
    ).toEqual(names(screenName))
    expect(screen.queryAllByText('Nog niet beschikbaar')).toHaveLength(0)
  })

  it('puts its icon before each name in the heading, none on Borrel (B-02, SD12)', async () => {
    await open(screenName)
    for (const [name, icon] of sections) {
      const heading = screen.getByRole('heading', { level: 2, name })
      expect(heading.textContent).toBe(name)
      expect(leadingIcon(heading)).toBe(icon === null ? null : iconMarkup(icon))
    }
  })

  it.runIf(multi)('lists its sections in the navigation, with the same icons (AC22)', async () => {
    await open(screenName)
    const nav = screen.getByRole('navigation', { name: 'Secties' })
    const links = within(nav).getAllByRole('link')
    expect(links.map((a) => a.textContent)).toEqual(names(screenName))
    for (const [i, [, icon]] of sections.entries()) {
      expect(leadingIcon(links[i])).toBe(icon === null ? null : iconMarkup(icon))
      const region = screen.getByRole('region', { name: sections[i][0] })
      expect(links[i].getAttribute('href')).toBe(`#${region.id}`)
    }
  })

  it.runIf(multi)(
    'on a narrow screen, the "Sectie" select holds the plain names (AC22)',
    async () => {
      stubNarrow(true)
      await open(screenName)
      const select = screen.getByRole<HTMLSelectElement>('combobox', { name: 'Sectie' })
      expect([...select.options].map((o) => o.textContent)).toEqual(names(screenName))
      expect(select.querySelectorAll('svg')).toHaveLength(0)
    },
  )

  it.runIf(!multi)('with one section, shows no section navigation (SD8)', async () => {
    await open(screenName)
    expect(screen.queryByRole('navigation', { name: 'Secties' })).toBeNull()
    stubNarrow(true)
    cleanup()
    await open(screenName)
    expect(screen.queryByRole('combobox', { name: 'Sectie' })).toBeNull()
  })

  it('has its (i) per section, each naming a setting explanation (B-01 AC10)', async () => {
    await open(screenName)
    for (const name of names(screenName)) {
      const buttons = info(screen.getByRole('region', { name }))
      const count = screenName === 'Beheer' && name === 'Vraag/Aanbod' ? 2 : INFO_COUNTS[name]
      expect([name, buttons.length]).toEqual([name, count])
      for (const button of buttons) {
        expect(NAMES.has(button.getAttribute('aria-label')!.slice('Uitleg: '.length))).toBe(true)
      }
    }
  })

  it('"← Instellingen" at the top goes to the landing (AC22)', async () => {
    await open(screenName)
    const back = screen.getByRole('link', { name: '← Instellingen' })
    expect(back.getAttribute('href')).toBe('/settings')
    expect(back.compareDocumentPosition(screen.getAllByRole('region')[0])).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
    fireEvent.click(back)
    await act(async () => {})
    expect(where()).toBe('/settings')
  })
})

describe('Spelopzet', () => {
  it('a field in several places opens the same explanation everywhere (B-01 AC9)', async () => {
    await open('Spelopzet')
    for (const key of ['a', 'd', 's0', 'c', 'p_min_cents', 'p0_cents', 'p_max_cents'] as const) {
      expectSameEverywhere(explanations[key], 2)
    }
    expectSameEverywhere(explanations.bar_price_cents, 3)
  })

  it('Profielen is anchored #profielen (B-04 AC19)', async () => {
    await open('Spelopzet')
    expect(screen.getByRole('region', { name: 'Profielen' }).id).toBe('profielen')
  })
})

describe('Mensen en wallets', () => {
  it('shows the Wallets section, anchored #wallets (B-05 SD16, AC34)', async () => {
    await open('Mensen en wallets')
    const region = screen.getByRole('region', { name: 'Wallets' })
    expect(region.id).toBe('wallets')
    expect(within(region).getByText('Aanmelden is gesloten.')).toBeTruthy()
    expect(within(region).getByText('Nog geen wallets')).toBeTruthy()
  })
})

// B-13 SD4, SD14; AC8: Betalen only for a session holding Spelopzet.
describe('Mensen en wallets per role (B-13)', () => {
  const asked = (path: string) =>
    vi.mocked(fetch).mock.calls.filter(([p]) => String(p) === path).length

  it('the kassa sees Wallets, not Betalen, and asks for no run or config', async () => {
    serveAs('kassa')
    await open('Mensen en wallets')
    expect(screen.getByRole('region', { name: 'Wallets' })).toBeTruthy()
    expect(screen.queryByRole('region', { name: 'Betalen' })).toBeNull()
    expect(asked('/api/runs/current')).toBe(0)
    expect(asked('/api/runs/7/config')).toBe(0)
  })

  it.each(['organiser', 'admin'])('%s sees Betalen and Wallets', async (role) => {
    serveAs(role)
    await open('Mensen en wallets')
    expect(
      screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent),
    ).toEqual(['Betalen', 'Wallets'])
  })
})

// B-13 SD6 (OQ1 = B): on a draft the organiser loads a profile, and neither saves nor
// deletes one; admin keeps both.
describe('Profielen per role (B-13)', () => {
  const PROFILE = {
    profile_id: 1,
    name: 'Wilde beurs',
    saved_at: '2026-10-24T12:05:00Z',
    source_run_name: 'Proef',
  }
  const onADraft = {
    ...SERVED,
    '/api/runs/current': { run_id: 7, name: 'Vrijmibo', status: 'draft' },
    '/api/profiles': [PROFILE],
  }
  const profielen = () => screen.getByRole('region', { name: 'Profielen' })

  it('the organiser has "Laden", and no save form or "Verwijderen"', async () => {
    serveAs('organiser', onADraft)
    await open('Spelopzet')
    expect(within(profielen()).getByRole('button', { name: 'Laden' })).toBeTruthy()
    expect(within(profielen()).queryByRole('button', { name: 'Opslaan als profiel' })).toBeNull()
    expect(within(profielen()).queryByRole('button', { name: 'Verwijderen' })).toBeNull()
  })

  it('admin has all three', async () => {
    serveAs('admin', onADraft)
    await open('Spelopzet')
    for (const name of ['Laden', 'Opslaan als profiel', 'Verwijderen']) {
      expect(within(profielen()).getByRole('button', { name })).toBeTruthy()
    }
  })
})

describe('Beheer: leaving (SD9; AC23, AC24)', () => {
  const drukdrempel = () => screen.getByRole<HTMLInputElement>('textbox', { name: 'Drukdrempel' })

  it('a dirty Drukdrempel asks; "Blijven" keeps the 7, "Weggooien" goes to the landing', async () => {
    await open('Beheer')
    fireEvent.change(drukdrempel(), { target: { value: '7' } })
    await act(async () => {})
    fireEvent.click(screen.getByRole('link', { name: '← Instellingen' }))

    expect(
      screen.getByRole('dialog', { name: 'Niet-opgeslagen wijzigingen weggooien?' }),
    ).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Blijven' }))
    expect(where()).toBe('/settings/beheer')
    expect(drukdrempel().value).toBe('7')

    fireEvent.click(screen.getByRole('link', { name: '← Instellingen' }))
    fireEvent.click(screen.getByRole('button', { name: 'Weggooien' }))
    await act(async () => {})
    expect(where()).toBe('/settings')
  })

  it('a clean Beheer leaves without a dialog', async () => {
    await open('Beheer')
    fireEvent.click(screen.getByRole('link', { name: '← Instellingen' }))
    await act(async () => {})

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(where()).toBe('/settings')
  })
})

describe('SettingsScreen', () => {
  it('a screen with one section shows no section navigation (SD8)', () => {
    renderInDataRouter(
      <SettingsScreen sections={[{ id: 'een', label: 'Een', content: <p>inhoud</p> }]} />,
    )
    expect(screen.getByRole('region', { name: 'Een' })).toBeTruthy()
    expect(screen.queryByRole('navigation', { name: 'Secties' })).toBeNull()
  })

  it('SettingsLayout with two sections keeps its navigation', () => {
    render(
      <SettingsLayout
        sections={[
          { id: 'een', label: 'Een', content: null },
          { id: 'twee', label: 'Twee', content: null },
        ]}
      />,
    )
    expect(screen.getByRole('navigation', { name: 'Secties' })).toBeTruthy()
  })
})

// B-04 SD1's 22 under their wire names; Profielen names them in a 422 (AC23).
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

describe('settingNames (B-04 AC23)', () => {
  it.each(PROFILE_FIELDS)('names %s by its setting name', (field) => {
    expect(settingNames[field]?.trim()).toBeTruthy()
    expect(settingNames[field]).not.toBe(field)
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
