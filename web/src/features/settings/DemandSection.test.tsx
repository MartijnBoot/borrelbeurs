// @vitest-environment jsdom
// 📈 Vraag/Aanbod (Phase 6 T28: SD25, SD27; AC1, AC2, AC3, AC5) -- the D-03 gate.
// v1 sent every coefficient of every drink on save, and an empty field became 0
// (D-03). Here the real `useEditableRecord` runs: an untouched save sends nothing;
// one edited `a` sends exactly `{a}` to that drink's PATCH.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore } from '../exchange'
import { DemandSection } from './DemandSection'

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
    eta: 0.6,
    K: 12,
    lambda_orders: 0.8,
    alpha_price: 0,
    phi_persist: 0.03,
    decay_rho: 0.98,
    history_window_minutes: 15,
    refresh_minutes: 1,
    idle_decay_minutes: 1,
    idle_rise_minutes: 1,
    idle_strength: 0.5,
    idle_rise_strength: 0.5,
    idle_targets: [],
    idle_rise_targets: [],
    demand_enabled: true,
    auto_calibrate_s0: false,
  },
  drinks: [
    { ...DRINK, drink_id: 11, name: 'Bier' },
    { ...DRINK, drink_id: 12, slot: 1, name: 'Wijn' },
    { ...DRINK, drink_id: 13, slot: 2, name: 'Oud', active: false },
  ],
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === '/api/runs/current') {
      return Promise.resolve(json(200, { run_id: 7, name: 'Vrijmibo', status: 'live' }))
    }
    if ((init?.method ?? 'GET') === 'GET') return Promise.resolve(json(200, CONFIG))
    return Promise.resolve(json(200, { revision: 4 }))
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function settle() {
  await act(async () => {})
  await act(async () => {})
}

function writes(): [string, string, unknown][] {
  return (fetchMock.mock.calls as [string, RequestInit | undefined][])
    .filter(([, init]) => (init?.method ?? 'GET') !== 'GET')
    .map(([path, init]) => [path, String(init?.method), JSON.parse(String(init?.body))])
}

async function open() {
  render(<DemandSection />)
  await settle()
}

const table = () => within(screen.getByRole('table', { name: 'Coëfficiënten' }))
const saveTable = async () => {
  fireEvent.click(screen.getByRole('button', { name: '💾 Opslaan coëfficiënten' }))
  await settle()
}

describe('DemandSection: the D-03 gate', () => {
  it('saving without an edit sends no request and says "Niets te wijzigen" (AC2)', async () => {
    await open()
    await saveTable()
    expect(writes()).toEqual([])
    expect(screen.getByRole('status').textContent).toBe('Niets te wijzigen')
  })

  it("one edited a sends exactly {a} to that drink's PATCH (AC1)", async () => {
    await open()
    fireEvent.change(table().getByLabelText('Wijn a'), { target: { value: '7,5' } })
    await saveTable()
    expect(writes()).toEqual([['/api/runs/7/drinks/12', 'PATCH', { a: 7.5 }]])
  })
})

describe('DemandSection', () => {
  it('lists every active drink and its four coefficients', async () => {
    await open()
    expect((table().getByLabelText('Bier d') as HTMLInputElement).value).toBe('0,6')
    expect(table().queryByLabelText('Oud a')).toBeNull()
  })

  it('a cleared coefficient blocks the save and is never sent as 0 (AC3)', async () => {
    await open()
    fireEvent.change(table().getByLabelText('Bier s0'), { target: { value: '' } })
    await saveTable()
    expect(writes()).toEqual([])
  })

  it('a toggle sends PATCH config with only that param', async () => {
    await open()
    fireEvent.click(screen.getByRole('switch', { name: 'Vraag/aanbod actief' }))
    fireEvent.click(screen.getByRole('button', { name: '💾 Opslaan schakelaars' }))
    await settle()
    expect(writes()).toEqual([
      ['/api/runs/7/config', 'PATCH', { params: { demand_enabled: false } }],
    ])
  })

  it('untouched switches send nothing', async () => {
    await open()
    fireEvent.click(screen.getByRole('button', { name: '💾 Opslaan schakelaars' }))
    await settle()
    expect(writes()).toEqual([])
  })

  it('a config while a row is dirty offers the server values (AC5)', async () => {
    await open()
    fireEvent.change(table().getByLabelText('Bier a'), { target: { value: '3' } })
    const changed = {
      ...CONFIG,
      revision: 4,
      drinks: CONFIG.drinks.map((d) => (d.drink_id === 11 ? { ...d, c: 0.9 } : d)),
    }
    fetchMock.mockImplementation((path: string) =>
      Promise.resolve(
        path === '/api/runs/current'
          ? json(200, { run_id: 7, name: 'Vrijmibo', status: 'live' })
          : json(200, changed),
      ),
    )
    act(() => exchangeStore.setState({ params: { ...CONFIG.params } }))
    await settle()

    expect(screen.getByText('Serverwaarden gewijzigd — overnemen?')).toBeTruthy()
    expect((table().getByLabelText('Bier a') as HTMLInputElement).value).toBe('3')
    fireEvent.click(screen.getByRole('button', { name: 'Overnemen' }))
    expect((table().getByLabelText('Bier c') as HTMLInputElement).value).toBe('0,9')
    expect((table().getByLabelText('Bier a') as HTMLInputElement).value).toBe('10')
  })
})
