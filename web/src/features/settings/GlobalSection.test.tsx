// @vitest-environment jsdom
// ⚙️ Globale instellingen (Phase 6 T25: SD8, SD25, SD27; AC1, AC2, AC3, AC5, AC28).
// The D-03 gate: an untouched save sends nothing; an edit sends exactly its field.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore } from '../exchange'
import { GlobalSection } from './GlobalSection'

const PARAMS = {
  step_quant: 0.5,
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
}

function config(params: Record<string, unknown> = PARAMS, candle = 60, revision = 3) {
  return {
    revision,
    run: { run_id: 7, name: 'Vrijmibo', status: 'live', candle_interval_s: candle },
    params,
    drinks: [],
  }
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let fetchMock: ReturnType<typeof vi.fn>
let served: unknown

beforeEach(() => {
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  served = config()
  fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === '/api/runs/current') {
      return Promise.resolve(json(200, { run_id: 7, name: 'Vrijmibo', status: 'live' }))
    }
    if (path === '/api/runs/7/config' && (init?.method ?? 'GET') === 'GET') {
      return Promise.resolve(json(200, served))
    }
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

function patches(): unknown[] {
  return (fetchMock.mock.calls as [string, RequestInit | undefined][])
    .filter(([, init]) => init?.method === 'PATCH')
    .map(([, init]) => JSON.parse(String(init?.body)))
}

async function open() {
  render(<GlobalSection />)
  await settle()
}

const save = async () => {
  fireEvent.click(screen.getByRole('button', { name: '💾 Opslaan instellingen' }))
  await settle()
}

describe('GlobalSection', () => {
  it('shows every SD8 global field with its v1 label and the server value', async () => {
    await open()
    expect((screen.getByLabelText('⚡ Snelheid') as HTMLInputElement).value).toBe('0,6')
    expect((screen.getByLabelText('🕯️ Kaarseninterval (sec)') as HTMLInputElement).value).toBe('60')
    for (const label of [
      '🧱 Tickgrootte',
      '🎚️ Drempel',
      '⚔️ Rivaliteit',
      '🧭 Aantrekking naar gemiddelde',
      '📈 Na-ijlen',
      '🧠 Geheugen (ρ)',
      '🗂️ Historie (min)',
      '🔁 Update-interval (min)',
    ]) {
      expect(screen.getByLabelText(label)).toBeTruthy()
    }
  })

  it('an untouched save sends nothing and says "Niets te wijzigen" (AC2)', async () => {
    await open()
    await save()
    expect(patches()).toEqual([])
    expect(screen.getByRole('status').textContent).toBe('Niets te wijzigen')
  })

  it('editing eta sends {params: {eta}} only (AC1)', async () => {
    await open()
    fireEvent.change(screen.getByLabelText('⚡ Snelheid'), { target: { value: '0,9' } })
    await save()
    expect(patches()).toEqual([{ params: { eta: 0.9 } }])
  })

  it('the candle interval goes at the top level', async () => {
    await open()
    fireEvent.change(screen.getByLabelText('🕯️ Kaarseninterval (sec)'), {
      target: { value: '30' },
    })
    await save()
    expect(patches()).toEqual([{ candle_interval_s: 30 }])
  })

  it('a cleared field blocks the save (AC3)', async () => {
    await open()
    fireEvent.change(screen.getByLabelText('🎚️ Drempel'), { target: { value: '' } })
    await save()
    expect(patches()).toEqual([])
    expect(screen.getByText('Verplicht')).toBeTruthy()
  })

  it('a config while dirty keeps the input and offers the server values (AC5)', async () => {
    await open()
    fireEvent.change(screen.getByLabelText('⚡ Snelheid'), { target: { value: '0,9' } })
    served = config({ ...PARAMS, K: 20 }, 60, 4)

    act(() => exchangeStore.setState({ params: { ...PARAMS, K: 20 } }))
    await settle()

    expect(screen.getByText('Serverwaarden gewijzigd — overnemen?')).toBeTruthy()
    expect((screen.getByLabelText('⚡ Snelheid') as HTMLInputElement).value).toBe('0,9')
    fireEvent.click(screen.getByRole('button', { name: 'Overnemen' }))
    expect((screen.getByLabelText('⚡ Snelheid') as HTMLInputElement).value).toBe('0,6')
    expect((screen.getByLabelText('🎚️ Drempel') as HTMLInputElement).value).toBe('20')
  })

  it('a config while clean reloads silently', async () => {
    await open()
    served = config({ ...PARAMS, K: 20 }, 60, 4)
    act(() => exchangeStore.setState({ params: { ...PARAMS, K: 20 } }))
    await settle()
    expect((screen.getByLabelText('🎚️ Drempel') as HTMLInputElement).value).toBe('20')
    expect(screen.queryByText('Serverwaarden gewijzigd — overnemen?')).toBeNull()
  })

  it('a 422 on candle_interval_s shows under that field', async () => {
    fetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (init?.method === 'PATCH') {
        return Promise.resolve(
          json(422, {
            error: {
              code: 'invalid_request',
              message: 'the request is not valid',
              faults: [{ loc: ['body', 'candle_interval_s'], msg: 'multiple of 5' }],
            },
          }),
        )
      }
      if (path === '/api/runs/current') {
        return Promise.resolve(json(200, { run_id: 7, name: 'Vrijmibo', status: 'live' }))
      }
      return Promise.resolve(json(200, served))
    })
    await open()
    fireEvent.change(screen.getByLabelText('🕯️ Kaarseninterval (sec)'), {
      target: { value: '7' },
    })
    await save()

    const input = screen.getByLabelText('🕯️ Kaarseninterval (sec)')
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(screen.getByText('multiple of 5')).toBeTruthy()
  })
})
