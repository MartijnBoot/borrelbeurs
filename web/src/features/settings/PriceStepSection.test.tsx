// @vitest-environment jsdom
// Prijsstap on Spelopzet's Prijzen (B-12 T7: SD4, PD9; AC15). B-07 T10's cases,
// moved verbatim from Globale instellingen: a Prijsstap that moves a bound asks
// first (B-07 SD3; AC10), and the server's `bounds_collision` shows under
// Prijsstap (AC8). Its own form: a clean save sends nothing.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { expectExplained } from '../../components/ui/infoTesting'
import { exchangeStore } from '../exchange'
import explanations from './explanations.json'
import { PriceStepSection } from './PriceStepSection'

const PARAMS = {
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
  bm_enabled: true,
  bm_sigma_y: 0.18,
  bm_dt_minutes: 1,
  flow_vol_amp: 0.7,
  flow_beta: 0.25,
  y_clip: 6,
}

const drink = (drink_id: number, slot: number, name: string, low: number, high: number) => ({
  drink_id,
  slot,
  name,
  active: true,
  p_min_cents: low,
  p0_cents: 200,
  p_max_cents: high,
  bar_price_cents: 200,
  a: 10,
  d: 0.6,
  s0: 8,
  c: 0.4,
})

function config(params: Record<string, unknown> = PARAMS, revision = 3) {
  return {
    revision,
    run: {
      run_id: 7,
      name: 'Vrijmibo',
      status: 'live',
      candle_interval_s: 60,
      wallet_required: true,
      credit_limit_cents: 0,
    },
    params,
    drinks: [drink(11, 0, 'Bier', 150, 310), drink(12, 1, 'Wijn', 150, 300)],
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
  render(<PriceStepSection />)
  await settle()
}

const save = async () => {
  fireEvent.click(screen.getByRole('button', { name: 'Opslaan prijsstap' }))
  await settle()
}

const input = (label: string) => screen.getByLabelText(label) as HTMLInputElement
const prijsstap = (value: string) => fireEvent.change(input('Prijsstap (€)'), { target: { value } })

describe('PriceStepSection (B-12 PD9)', () => {
  it('shows the server value under its B-01 name, with its (i)', async () => {
    const { container } = render(<PriceStepSection />)
    await settle()
    expect(input('Prijsstap (€)').value).toBe('0,1')
    expectExplained(container, explanations.step_quant)
  })

  it('a clean save sends nothing and says "Niets te wijzigen"', async () => {
    await open()
    await save()
    expect(patches()).toEqual([])
    expect(screen.getByText('Niets te wijzigen')).toBeTruthy()
  })

  it('an emptied Prijsstap blocks the save', async () => {
    await open()
    prijsstap('')
    await save()
    expect(patches()).toEqual([])
    expect(screen.getByText('Verplicht')).toBeTruthy()
  })

  it('a server change while dirty keeps the input and offers "Overnemen" once', async () => {
    await open()
    prijsstap('0,05')
    served = config({ ...PARAMS, step_quant: 0.2 }, 4)
    act(() => exchangeStore.setState({ params: { ...PARAMS, step_quant: 0.2 } }))
    await settle()

    expect(screen.getAllByText('Serverwaarden gewijzigd — overnemen?')).toHaveLength(1)
    expect(input('Prijsstap (€)').value).toBe('0,05')
    fireEvent.click(screen.getByRole('button', { name: 'Overnemen' }))
    expect(input('Prijsstap (€)').value).toBe('0,2')
  })
})

describe('PriceStepSection: a Prijsstap that moves bounds (B-07)', () => {
  it('0,10 to 0,25 lists the moving bound before sending (AC10)', async () => {
    await open()
    prijsstap('0,25')
    await save()
    expect(patches()).toEqual([])
    const dialog = screen.getByRole('dialog')
    expect(dialog.textContent).toContain('Prijsstap 0,25 opslaan? Deze grenzen schuiven mee:')
    const items = Array.from(dialog.querySelectorAll('li')).map((li) => li.textContent)
    expect(items).toEqual(['Bier: Maximumprijs 3,10 → 3,00'])
  })

  it('"Annuleren" sends nothing and keeps the typed step', async () => {
    await open()
    prijsstap('0,25')
    await save()
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    await settle()
    expect(patches()).toEqual([])
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(input('Prijsstap (€)').value).toBe('0,25')
  })

  it('"Opslaan" sends one PATCH', async () => {
    await open()
    prijsstap('0,25')
    await save()
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await settle()
    expect(patches()).toEqual([{ params: { step_quant: 0.25 } }])
  })

  it('a step that moves no bound sends without a dialog', async () => {
    await open()
    prijsstap('0,05')
    await save()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(patches()).toEqual([{ params: { step_quant: 0.05 } }])
  })

  it("the server's bounds_collision shows under Prijsstap, every drink named (AC8)", async () => {
    const msg =
      'Past niet bij Bier: de grenzen worden 2,00–2,00. ' +
      'Past niet bij Wijn: de grenzen worden 2,00–2,00.'
    fetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (init?.method === 'PATCH') {
        return Promise.resolve(
          json(422, {
            error: {
              code: 'bounds_collision',
              message: msg,
              faults: [{ loc: ['body', 'params', 'step_quant'], msg }],
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
    prijsstap('2')
    await save()
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await settle()
    expect(input('Prijsstap (€)').getAttribute('aria-invalid')).toBe('true')
    expect(screen.getByText(msg)).toBeTruthy()
  })
})
