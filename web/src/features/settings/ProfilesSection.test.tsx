// @vitest-environment jsdom
// The Profielen section (B-04 T8b: SD2, SD5, SD6, SD10, SD12, SD14; AC1-AC3, AC17,
// AC19-AC21, AC23): the list, "Opslaan als profiel" with its overwrite confirm, and
// "Verwijderen" behind a plain confirm. T9 (AC11-AC14, AC16, AC21): "Profiel laden" on a
// draft, and the other sections showing the loaded values.
import { act, cleanup, fireEvent, render, renderHook, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore } from '../exchange'
import { DemandSection } from './DemandSection'
import { GlobalSection } from './GlobalSection'
import { ProfilesSection } from './ProfilesSection'
import { useProfiles } from './useProfiles'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const noContent = () => new Response(null, { status: 204 })
const noRun = () => json(404, { error: { code: 'no_current_run', message: 'none' } })

const draft = { run_id: 7, name: 'Proef', status: 'draft' }
const live = { ...draft, status: 'live' }

// 12:05 UTC is 14:05 in Amsterdam (CEST); 08:30 UTC in December is 09:30 (CET).
const WILD = {
  profile_id: 2,
  name: 'Wilde beurs',
  saved_at: '2026-10-24T12:05:00Z',
  source_run_name: 'Proef',
}
const CALM = {
  profile_id: 1,
  name: 'rustig',
  saved_at: '2026-12-03T08:30:00Z',
  source_run_name: 'Vrijmibo',
}

const NAMES = { y_clip: 'Grens ruis', eta: 'Beweging per bestelling' }

let fetchMock: ReturnType<typeof vi.fn>
let current: () => Response
let profiles: () => Response
let writes: (() => Response)[]

/** `/api/runs/current` and `GET /api/profiles` answer from their own functions; every
 * other request from `writes`, in order. */
function serve() {
  fetchMock.mockImplementation((path: string, init?: RequestInit) => {
    if (path === '/api/runs/current') return Promise.resolve(current())
    if (path === '/api/profiles' && (init?.method ?? 'GET') === 'GET')
      return Promise.resolve(profiles())
    return Promise.resolve(writes.shift()?.())
  })
}

beforeEach(() => {
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  current = () => json(200, draft)
  profiles = () => json(200, [CALM, WILD])
  writes = []
  serve()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function settle() {
  for (let i = 0; i < 3; i += 1) await act(async () => {})
}

/** Every request but the two reads: `[path, method, body]`. */
function sent(): [string, string | undefined, unknown][] {
  return (fetchMock.mock.calls as [string, RequestInit | undefined][])
    .filter(
      ([path, init]) =>
        path !== '/api/runs/current' && !(path === '/api/profiles' && init?.method === 'GET'),
    )
    .map(([path, init]) => [
      path,
      init?.method,
      typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    ])
}

const rows = () => screen.getAllByRole('listitem').map((li) => li.textContent)

async function open() {
  render(<ProfilesSection names={NAMES} />)
  await settle()
}

function typeName(name: string) {
  fireEvent.change(screen.getByLabelText('Naam'), { target: { value: name } })
}

describe('the list (AC20, SD12)', () => {
  it('shows each profile as served, in Amsterdam time, with its delete button', async () => {
    await open()

    expect(screen.getAllByRole('listitem').map((li) => li.firstChild?.textContent)).toEqual([
      "rustig · opgeslagen 3 dec 09:30 · uit 'Vrijmibo'",
      "Wilde beurs · opgeslagen 24 okt 14:05 · uit 'Proef'",
    ])
    for (const item of screen.getAllByRole('listitem')) {
      expect(within(item).getByRole('button', { name: 'Verwijderen' })).toBeTruthy()
    }
  })

  it('says "Nog geen profielen" when there are none', async () => {
    profiles = () => json(200, [])
    await open()

    expect(screen.getByText('Nog geen profielen')).toBeTruthy()
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
  })

  it('shows the connection error when the list cannot be fetched', async () => {
    profiles = () => json(500, { error: { code: 'internal', message: 'boom' } })
    await open()

    expect(screen.getByText('Verbindingsfout. Probeer opnieuw.')).toBeTruthy()
  })

  it('shows no value of a profile', async () => {
    await open()

    expect(document.body.textContent).not.toMatch(/\d,\d|0\.\d/)
    expect(document.body.textContent).not.toContain('Grens ruis')
  })
})

describe('"Opslaan als profiel" (AC1, AC21)', () => {
  it.each([
    ['a draft', draft],
    ['a live run', live],
  ])('shows on %s', async (_, run) => {
    current = () => json(200, run)
    await open()

    expect(screen.getByRole('button', { name: 'Opslaan als profiel' })).toBeTruthy()
    expect((screen.getByLabelText('Naam') as HTMLInputElement).maxLength).toBe(100)
  })

  it('is absent with no run, while the list and its delete buttons still show', async () => {
    current = noRun
    await open()

    expect(screen.queryByRole('button', { name: 'Opslaan als profiel' })).toBeNull()
    expect(rows()).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'Verwijderen' })).toHaveLength(2)
  })

  it('saves the current run under the typed name, then clears it and refetches the list', async () => {
    writes = [() => json(201, { ...WILD, profile_id: 3, name: 'Nieuw' })]
    await open()
    profiles = () => json(200, [CALM, WILD, { ...WILD, profile_id: 3, name: 'Nieuw' }])

    typeName('Nieuw')
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan als profiel' }))
    await settle()

    expect(sent()).toEqual([['/api/profiles', 'POST', { name: 'Nieuw', run_id: 7 }]])
    expect((screen.getByLabelText('Naam') as HTMLInputElement).value).toBe('')
    expect(rows()).toHaveLength(3)
  })

  it('a save makes a second list refetch (PD13)', async () => {
    writes = [() => json(201, { ...WILD, profile_id: 3, name: 'Nieuw' })]
    await open()
    const other = renderHook(() => useProfiles())
    await settle()
    profiles = () => json(200, [WILD])

    typeName('Nieuw')
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan als profiel' }))
    await settle()

    expect(other.result.current.profiles).toEqual([WILD])
  })
})

describe('the overwrite confirm (AC3, SD5)', () => {
  const exists = () =>
    json(409, { error: { code: 'profile_exists', message: 'exists', profile_id: 2 } })

  it('asks with the listed spelling, and on confirm resends with overwrite', async () => {
    writes = [exists, () => json(200, WILD)]
    await open()

    typeName('  WILDE beurs ')
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan als profiel' }))
    await settle()

    expect(screen.getByText("Profiel 'Wilde beurs' overschrijven?")).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Overschrijven' }))
    await settle()

    expect(sent()).toEqual([
      ['/api/profiles', 'POST', { name: '  WILDE beurs ', run_id: 7 }],
      ['/api/profiles', 'POST', { name: '  WILDE beurs ', run_id: 7, overwrite: true }],
    ])
    expect(screen.queryByText("Profiel 'Wilde beurs' overschrijven?")).toBeNull()
  })

  it('uses the typed name when the existing profile is not in the list', async () => {
    profiles = () => json(200, [])
    writes = [exists]
    await open()

    typeName('Elders')
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan als profiel' }))
    await settle()

    expect(screen.getByText("Profiel 'Elders' overschrijven?")).toBeTruthy()
  })

  it('sends nothing on cancel', async () => {
    writes = [exists]
    await open()

    typeName('Wilde beurs')
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan als profiel' }))
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    await settle()

    expect(sent()).toHaveLength(1)
    expect(screen.queryByText("Profiel 'Wilde beurs' overschrijven?")).toBeNull()
  })
})

describe('the save failures (AC23, PD12)', () => {
  it('names a run value outside the rules by its setting name, not its wire name', async () => {
    writes = [
      () =>
        json(422, {
          error: {
            code: 'invalid_request',
            message: 'y_clip: too big',
            faults: [{ loc: ['run', 'params', 'y_clip'], msg: 'too big' }],
          },
        }),
    ]
    await open()

    typeName('Te wild')
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan als profiel' }))
    await settle()

    expect(screen.getByRole('alert').textContent).toBe(
      "Niet opgeslagen: 'Grens ruis' valt buiten de toegestane waarden.",
    )
    expect(document.body.textContent).not.toContain('y_clip')
  })

  it('a bad name is the name text', async () => {
    writes = [
      () =>
        json(422, {
          error: {
            code: 'invalid_request',
            message: 'bad',
            faults: [{ loc: ['body', 'name'], msg: 'too long' }],
          },
        }),
    ]
    await open()

    typeName('x')
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan als profiel' }))
    await settle()

    expect(screen.getByRole('alert').textContent).toBe('Vul een naam in (1–100 tekens).')
  })
})

describe('"Verwijderen" (AC17, SD6)', () => {
  it('asks a plain confirm, then deletes and refetches', async () => {
    writes = [noContent]
    await open()
    profiles = () => json(200, [CALM])

    const row = screen.getAllByRole('listitem')[1]
    fireEvent.click(within(row).getByRole('button', { name: 'Verwijderen' }))
    expect(screen.getByText("Profiel 'Wilde beurs' verwijderen?")).toBeTruthy()
    expect(screen.queryByRole('textbox', { name: /bevestig/i })).toBeNull()
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Verwijderen' }))
    await settle()

    expect(sent()).toEqual([['/api/profiles/2', 'DELETE', undefined]])
    expect(rows()).toHaveLength(1)
  })

  it('sends nothing on cancel', async () => {
    await open()

    fireEvent.click(screen.getAllByRole('button', { name: 'Verwijderen' })[0])
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    await settle()

    expect(sent()).toEqual([])
  })

  it('a profile already gone says so and reloads the list', async () => {
    writes = [() => json(404, { error: { code: 'profile_not_found', message: 'gone' } })]
    await open()
    profiles = () => json(200, [CALM])

    fireEvent.click(screen.getAllByRole('button', { name: 'Verwijderen' })[1])
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Verwijderen' }))
    await settle()

    expect(screen.getByRole('alert').textContent).toBe('Dit profiel bestaat niet meer.')
    expect(rows()).toHaveLength(1)
  })

  it('a delete makes a second list refetch (PD13)', async () => {
    writes = [noContent]
    await open()
    const other = renderHook(() => useProfiles())
    await settle()
    profiles = () => json(200, [CALM])

    fireEvent.click(screen.getAllByRole('button', { name: 'Verwijderen' })[1])
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Verwijderen' }))
    await settle()

    expect(other.result.current.profiles).toEqual([CALM])
  })
})

// --- T9: "Profiel laden" on a draft (AC11-AC14, AC16, AC21; SD3, SD13) ----------

const LOAD = '/api/runs/7/profile'
const loadConfirm =
  "Profiel 'Wilde beurs' laden op 'Proef'? Dit vervangt de instellingen van deze borrel."

function pick(name: string) {
  const select = screen.getByLabelText('Profiel laden') as HTMLSelectElement
  const option = [...select.options].find((o) => o.textContent === name)
  fireEvent.change(select, { target: { value: option?.value } })
}

describe('"Profiel laden" (AC12, AC13, AC21)', () => {
  it('shows on a draft, with every profile by name', async () => {
    await open()

    const select = screen.getByLabelText('Profiel laden') as HTMLSelectElement
    expect([...select.options].map((o) => o.textContent)).toEqual(['rustig', 'Wilde beurs'])
    expect(screen.getByRole('button', { name: 'Laden' })).toBeTruthy()
  })

  it.each([
    ['a live run', () => json(200, live)],
    ['no run', noRun],
  ])('is absent on %s', async (_, answer) => {
    current = answer
    await open()

    expect(screen.queryByLabelText('Profiel laden')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Laden' })).toBeNull()
  })

  it('asks first, then sends the profile and reloads the run', async () => {
    writes = [() => json(200, { revision: 4 })]
    await open()
    const runReads = () =>
      fetchMock.mock.calls.filter(([path]) => path === '/api/runs/current').length
    const before = runReads()

    pick('Wilde beurs')
    fireEvent.click(screen.getByRole('button', { name: 'Laden' }))
    expect(screen.getByText(loadConfirm)).toBeTruthy()
    expect(sent()).toEqual([])
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Laden' }))
    await settle()

    expect(sent()).toEqual([[LOAD, 'POST', { profile_id: 2 }]])
    expect(runReads()).toBeGreaterThan(before)
    expect(screen.queryByText(loadConfirm)).toBeNull()
  })

  it('sends nothing on cancel', async () => {
    await open()

    pick('Wilde beurs')
    fireEvent.click(screen.getByRole('button', { name: 'Laden' }))
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    await settle()

    expect(sent()).toEqual([])
  })
})

describe('the load failures (AC13, AC14, AC23; PD12)', () => {
  async function load() {
    await open()
    pick('Wilde beurs')
    fireEvent.click(screen.getByRole('button', { name: 'Laden' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Laden' }))
    await settle()
  }

  it('a profile gone meanwhile says so and reloads the list', async () => {
    writes = [() => json(404, { error: { code: 'profile_not_found', message: 'gone' } })]
    profiles = () => json(200, [CALM, WILD])
    await open()
    profiles = () => json(200, [CALM])
    pick('Wilde beurs')
    fireEvent.click(screen.getByRole('button', { name: 'Laden' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Laden' }))
    await settle()

    expect(screen.getByRole('alert').textContent).toBe('Dit profiel bestaat niet meer.')
    expect(rows()).toHaveLength(1)
  })

  it('a stored value outside the rules is named by its setting name', async () => {
    writes = [
      () =>
        json(422, {
          error: {
            code: 'invalid_request',
            message: 'y_clip: too big',
            faults: [{ loc: ['profile', 'params', 'y_clip'], msg: 'too big' }],
          },
        }),
    ]
    await load()

    expect(screen.getByRole('alert').textContent).toBe(
      "Profiel niet toegepast: 'Grens ruis' valt buiten de toegestane waarden.",
    )
    expect(sent()).toHaveLength(1)
  })

  it('a run that is no longer a draft says so and reloads the run', async () => {
    writes = [() => json(409, { error: { code: 'run_not_draft', message: 'live' } })]
    await open()
    current = () => json(200, live)
    pick('Wilde beurs')
    fireEvent.click(screen.getByRole('button', { name: 'Laden' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Laden' }))
    await settle()

    expect(screen.getByRole('alert').textContent).toBe('Deze borrel is geen concept meer.')
    expect(screen.queryByLabelText('Profiel laden')).toBeNull()
  })
})

// --- AC16: the other sections show the loaded values without a remount -----------

const PARAMS = {
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
}

const document_ = (params: object, candle: number, revision: number) => ({
  revision,
  run: { ...draft, candle_interval_s: candle },
  params,
  drinks: [],
})

describe('after a load, the other sections show the loaded values (AC16)', () => {
  let served: unknown

  beforeEach(() => {
    served = document_(PARAMS, 60, 3)
    fetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      if (path === '/api/runs/current') return Promise.resolve(json(200, draft))
      if (path === '/api/profiles') return Promise.resolve(json(200, [WILD]))
      if (path === '/api/runs/7/config' && method === 'GET')
        return Promise.resolve(json(200, served))
      if (path === LOAD) {
        served = document_({ ...PARAMS, bm_sigma_y: 0.5, demand_enabled: true }, 30, 4)
        return Promise.resolve(json(200, { revision: 4 }))
      }
      return Promise.resolve(json(404, { error: { code: 'not_found', message: path } }))
    })
  })

  async function renderTogether() {
    render(
      <>
        <ProfilesSection names={NAMES} />
        <GlobalSection />
        <DemandSection />
      </>,
    )
    await settle()
  }

  async function loadWild() {
    pick('Wilde beurs')
    fireEvent.click(screen.getByRole('button', { name: 'Laden' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Laden' }))
    await settle()
  }

  const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement
  const demand = () => screen.getByRole('switch', { name: 'Verwachte verkoop meetellen' })

  it('Globale instellingen and Vraag/Aanbod refetch', async () => {
    await renderTogether()
    expect(field('Sterkte ruis').value).toBe('0,18')
    expect(demand().getAttribute('aria-checked')).toBe('false')

    await loadWild()

    expect(field('Sterkte ruis').value).toBe('0,5')
    expect(field('Kaarsbreedte (sec)').value).toBe('30')
    expect(demand().getAttribute('aria-checked')).toBe('true')
  })

  it('a section with an unsaved edit keeps it and offers "Overnemen"', async () => {
    await renderTogether()
    fireEvent.change(field('Sterkte ruis'), { target: { value: '0,3' } })

    await loadWild()

    expect(field('Sterkte ruis').value).toBe('0,3')
    expect(screen.getByText('Serverwaarden gewijzigd — overnemen?')).toBeTruthy()
    fireEvent.click(screen.getAllByRole('button', { name: 'Overnemen' })[0])
    expect(field('Sterkte ruis').value).toBe('0,5')
    expect(field('Kaarsbreedte (sec)').value).toBe('30')
  })
})
