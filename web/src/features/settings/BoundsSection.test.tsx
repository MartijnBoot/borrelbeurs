// @vitest-environment jsdom
// 🔒 Min/Max/Startprijs (Phase 6 T27: SD25; AC1, AC3, AC11): one row per active
// drink, each saving only its own dirty bounds.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore } from '../exchange'
import { BoundsSection } from './BoundsSection'

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
let writeAnswer: () => Response

beforeEach(() => {
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  writeAnswer = () => json(200, { revision: 4 })
  fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === '/api/runs/current') {
      return Promise.resolve(json(200, { run_id: 7, name: 'Vrijmibo', status: 'live' }))
    }
    if ((init?.method ?? 'GET') === 'GET') return Promise.resolve(json(200, CONFIG))
    return Promise.resolve(writeAnswer())
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

function writes(): [string, unknown][] {
  return (fetchMock.mock.calls as [string, RequestInit | undefined][])
    .filter(([, init]) => (init?.method ?? 'GET') !== 'GET')
    .map(([path, init]) => [path, JSON.parse(String(init?.body))])
}

const row = (name: string) => within(screen.getByRole('group', { name }))

async function open() {
  render(<BoundsSection />)
  await settle()
}

describe('BoundsSection', () => {
  it('lists the active drinks with their bounds in euros', async () => {
    await open()
    expect((row('Bier').getByLabelText('Min') as HTMLInputElement).value).toBe('1,50')
    expect((row('Bier').getByLabelText('Start') as HTMLInputElement).value).toBe('2,60')
    expect((row('Bier').getByLabelText('Max') as HTMLInputElement).value).toBe('5,00')
    expect(screen.queryByRole('group', { name: 'Oud' })).toBeNull()
  })

  it('an untouched save sends nothing (AC1)', async () => {
    await open()
    fireEvent.click(row('Bier').getByRole('button', { name: 'Opslaan' }))
    await settle()
    expect(writes()).toEqual([])
    expect(screen.getByRole('status').textContent).toBe('Niets te wijzigen')
  })

  it('one edited p_max sends one PATCH with only p_max_cents', async () => {
    await open()
    fireEvent.change(row('Wijn').getByLabelText('Max'), { target: { value: '4,75' } })
    fireEvent.click(row('Wijn').getByRole('button', { name: 'Opslaan' }))
    await settle()
    expect(writes()).toEqual([['/api/runs/7/drinks/12', { p_max_cents: 475 }]])
  })

  it('an order that breaks p_min < p0 < p_max blocks the save (AC11)', async () => {
    await open()
    fireEvent.change(row('Bier').getByLabelText('Min'), { target: { value: '3' } })
    fireEvent.click(row('Bier').getByRole('button', { name: 'Opslaan' }))
    await settle()
    expect(writes()).toEqual([])
    expect(row('Bier').getByRole('alert').textContent).toBe('Min < Start < Max')
  })

  it('a cleared bound blocks the save (AC3)', async () => {
    await open()
    fireEvent.change(row('Bier').getByLabelText('Start'), { target: { value: '' } })
    fireEvent.click(row('Bier').getByRole('button', { name: 'Opslaan' }))
    await settle()
    expect(writes()).toEqual([])
  })

  it("shows the server's 422", async () => {
    writeAnswer = () =>
      json(422, {
        error: {
          code: 'invalid_request',
          message: 'p0_cents must lie strictly between',
          faults: [{ loc: ['body', 'p_max_cents'], msg: 'p_min_cents < p0_cents < p_max_cents' }],
        },
      })
    await open()
    fireEvent.change(row('Bier').getByLabelText('Max'), { target: { value: '9' } })
    fireEvent.click(row('Bier').getByRole('button', { name: 'Opslaan' }))
    await settle()
    expect(row('Bier').getByText('p_min_cents < p0_cents < p_max_cents')).toBeTruthy()
  })
})
