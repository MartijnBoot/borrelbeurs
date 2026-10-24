// @vitest-environment jsdom
// Idle (Phase 6 T34: SD11, SD20; AC1, AC2, AC7, AC22): v1's decay/rise minutes
// and strengths, and both target lists over active drinks, sent as a dirty-only
// `PATCH config` of `drink_id`s. B-01 T8: the new names and (i) (E21-E26), and AC18.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { expectExplained } from '../../components/ui/infoTesting'
import { applyMessage, exchangeStore, type ServerMessage, type SnapshotData } from '../exchange'
import explanations from './explanations.json'
import { IdleSection } from './IdleSection'

const RUN = {
  run_id: 1,
  tick_interval_ms: 1000,
  candle_interval_ms: 60000,
  quote_grace_versions: 2,
}

const DRINKS = [
  { drink_id: 1, name: 'Bier', active: true },
  { drink_id: 2, name: 'Wijn', active: true },
]

const SNAPSHOT: SnapshotData = {
  version: 5,
  run: RUN,
  drinks: DRINKS,
  params: {},
  prices: {
    1: { price_cents: 250, chart_price_cents: 250 },
    2: { price_cents: 300, chart_price_cents: 300 },
  },
  bars: {},
  news: [],
  earnings: {},
  market_events: [],
}

const PARAMS = {
  idle_decay_minutes: 5,
  idle_rise_minutes: 10,
  idle_strength: 1,
  idle_rise_strength: 0.5,
  idle_targets: [] as number[],
  idle_rise_targets: [2],
}

// hello and snapshot set the baseline seq; a broadcast applies only as the next one (AC18).
let seq = 0

function dispatch(type: ServerMessage['type'], data: unknown, version: number | null = 5) {
  if (type === 'hello') seq = 0
  else if (type !== 'snapshot') seq += 1
  const message = { v: 1, type, seq, ts_ms: 0, run_id: 1, version, data } as ServerMessage
  act(() => exchangeStore.setState((s) => applyMessage(s, message, performance.now()), true))
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  fetchMock = vi.fn((_path: string, init?: RequestInit) =>
    Promise.resolve(
      (init?.method ?? 'GET') === 'GET'
        ? json(200, { revision: 3, params: PARAMS })
        : json(200, { revision: 4 }),
    ),
  )
  vi.stubGlobal('fetch', fetchMock)
  dispatch('hello', {
    boot_id: 'B',
    run_id: 1,
    tick_interval_ms: 1000,
    protocol: 1,
    role: 'admin',
    theme: { preset: 'blauw', revision: 0, tokens: {}, font_family: 'sans-serif' },
  })
  dispatch('snapshot', SNAPSHOT)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const writes = () =>
  (fetchMock.mock.calls as [string, RequestInit | undefined][])
    .filter(([, init]) => (init?.method ?? 'GET') !== 'GET')
    .map(([path, init]) => [path, init?.method, init?.body])

async function open() {
  render(<IdleSection />)
  await act(async () => {})
  await act(async () => {})
}

const decayTargets = () => screen.getByRole('group', { name: 'Omlaag bij stilte' })
const riseTargets = () => screen.getByRole('group', { name: 'Omhoog bij stilte' })

describe('IdleSection', () => {
  it('shows the server values and the target lists over active drinks', async () => {
    await open()
    expect((screen.getByLabelText('Omlaag na stilte van (min)') as HTMLInputElement).value).toBe(
      '5',
    )
    const wijn = within(riseTargets()).getByLabelText('Wijn') as HTMLInputElement
    expect(wijn.checked).toBe(true)
    expect((within(decayTargets()).getByLabelText('Bier') as HTMLInputElement).checked).toBe(false)
  })

  it('ticking one drink sends {params:{idle_targets:[id]}} only', async () => {
    await open()
    fireEvent.click(within(decayTargets()).getByLabelText('Bier'))
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan idle' }))
    await act(async () => {})

    expect(writes()).toEqual([
      ['/api/runs/1/config', 'PATCH', JSON.stringify({ params: { idle_targets: [1] } })],
    ])
  })

  it('"Opslaan idle" is text only (B-02 SD4)', async () => {
    await open()
    const button = screen.getByRole('button', { name: 'Opslaan idle' })
    expect(button.textContent).toBe('Opslaan idle')
    expect(button.querySelector('svg')).toBeNull()
  })

  it('untouched sends nothing (AC2)', async () => {
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan idle' }))
    await act(async () => {})

    expect(writes()).toEqual([])
    expect(screen.getByText('Niets te wijzigen')).toBeTruthy()
  })

  it.each([
    'idle_decay_minutes',
    'idle_strength',
    'idle_rise_minutes',
    'idle_rise_strength',
    'idle_targets',
    'idle_rise_targets',
  ] as const)('%s has its B-01 name and (i) (B-01 AC1, AC7)', async (key) => {
    await open()
    expectExplained(document.body, explanations[key])
  })

  it('names each field and target group exactly (B-01 AC7)', async () => {
    await open()
    for (const name of [
      'Omlaag na stilte van (min)',
      'Kracht omlaag',
      'Omhoog na stilte van (min)',
      'Kracht omhoog',
    ]) {
      expect(screen.getByLabelText(name)).toBeTruthy()
    }
    expect(decayTargets().getAttribute('aria-label')).toBe('Omlaag bij stilte')
    expect(riseTargets().getAttribute('aria-label')).toBe('Omhoog bij stilte')
  })

  it("an (i) leaves the form clean: saving says 'Niets te wijzigen' (B-01 AC5)", async () => {
    await open()
    const info = screen.getByRole('button', { name: 'Uitleg: Omlaag bij stilte' })
    fireEvent.click(info)
    fireEvent.click(info)
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan idle' }))
    await act(async () => {})

    expect(writes()).toEqual([])
    expect(screen.getByText('Niets te wijzigen')).toBeTruthy()
  })

  it("on a first borrel's 0.1 idle minutes, saving only Kracht omlaag succeeds (B-01 AC18)", async () => {
    const first = { ...PARAMS, idle_decay_minutes: 0.1, idle_rise_minutes: 0.1 }
    fetchMock.mockImplementation((_path: string, init?: RequestInit) =>
      Promise.resolve(
        (init?.method ?? 'GET') === 'GET'
          ? json(200, { revision: 3, params: first })
          : json(200, { revision: 4 }),
      ),
    )
    await open()
    expect((screen.getByLabelText('Omlaag na stilte van (min)') as HTMLInputElement).value).toBe(
      '0,1',
    )
    fireEvent.change(screen.getByLabelText('Kracht omlaag'), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan idle' }))
    await act(async () => {})

    expect(writes()).toEqual([
      ['/api/runs/1/config', 'PATCH', JSON.stringify({ params: { idle_strength: 2 } })],
    ])
    expect(screen.getByText('Opgeslagen')).toBeTruthy()
  })

  it('a config message removing a drink drops its checkbox (AC22)', async () => {
    await open()
    expect(within(decayTargets()).getAllByRole('checkbox')).toHaveLength(2)

    dispatch('config', {
      revision: 4,
      run: { ...RUN, name: 'Vrijmibo' },
      drinks: [DRINKS[0], { ...DRINKS[1], active: false }],
      params: {},
    })
    await act(async () => {})

    expect(within(decayTargets()).queryByLabelText('Wijn')).toBeNull()
    expect(within(riseTargets()).queryByLabelText('Wijn')).toBeNull()
  })
})
