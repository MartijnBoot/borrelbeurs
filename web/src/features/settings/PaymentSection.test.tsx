// @vitest-environment jsdom
// Betalen on Mensen en wallets (B-12 T8: SD3, SD13, PD10; AC16): B-06's two run
// columns, moved from Globale instellingen with their cases (B-06 T17: SD1-SD3;
// AC2, AC3). They go at the top level of `PATCH config`, never under `params`.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { expectExplained } from '../../components/ui/infoTesting'
import { exchangeStore } from '../exchange'
import explanations from './explanations.json'
import { PaymentSection } from './PaymentSection'

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
  bm_enabled: true,
  bm_sigma_y: 0.18,
  bm_dt_minutes: 1,
  flow_vol_amp: 0.7,
  flow_beta: 0.25,
  y_clip: 6,
}

function config(run: Record<string, unknown> = {}, revision = 3) {
  return {
    revision,
    run: {
      run_id: 7,
      name: 'Vrijmibo',
      status: 'live',
      candle_interval_s: 60,
      wallet_required: true,
      credit_limit_cents: 0,
      ...run,
    },
    params: PARAMS,
    drinks: [],
  }
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let fetchMock: ReturnType<typeof vi.fn>
let served: unknown

function answer(patch: () => Response = () => json(200, { revision: 4 })) {
  fetchMock.mockImplementation((path: string, init?: RequestInit) => {
    if (init?.method === 'PATCH') return Promise.resolve(patch())
    if (path === '/api/runs/current') {
      return Promise.resolve(json(200, { run_id: 7, name: 'Vrijmibo', status: 'live' }))
    }
    return Promise.resolve(json(200, served))
  })
}

beforeEach(() => {
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  served = config()
  fetchMock = vi.fn()
  answer()
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
  render(<PaymentSection />)
  await settle()
}

const save = async () => {
  fireEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
  await settle()
}

const input = (label: string) => screen.getByLabelText(label) as HTMLInputElement
const walletSwitch = () => screen.getByRole('switch', { name: 'Wallet verplicht' })

describe('PaymentSection (B-12 PD10)', () => {
  it('shows the server values: the switch on, the limit in euros (B-06 SD1, SD2)', async () => {
    served = config({ credit_limit_cents: 250 })
    await open()
    expect(walletSwitch().getAttribute('aria-checked')).toBe('true')
    expect(input('Rood staan tot (€)').value).toBe('2,50')
  })

  it.each(['wallet_required', 'credit_limit_cents'] as const)(
    '%s has an (i) with its explanation (B-06 AC3)',
    async (key) => {
      const { container } = render(<PaymentSection />)
      await settle()
      expectExplained(container, explanations[key])
    },
  )

  it('toggling "Wallet verplicht" sends {wallet_required: false} at the top level (AC16)', async () => {
    await open()
    fireEvent.click(walletSwitch())
    await save()
    expect(patches()).toEqual([{ wallet_required: false }])
  })

  it('a limit of 2,50 sends {credit_limit_cents: 250} at the top level (AC16)', async () => {
    await open()
    fireEvent.change(input('Rood staan tot (€)'), { target: { value: '2,50' } })
    await save()
    expect(patches()).toEqual([{ credit_limit_cents: 250 }])
  })

  it('a clean save sends nothing and says "Niets te wijzigen" (AC16)', async () => {
    await open()
    await save()
    expect(patches()).toEqual([])
    expect(screen.getByText('Niets te wijzigen')).toBeTruthy()
  })

  it('a 422 on credit_limit_cents shows under that field (AC16)', async () => {
    answer(() =>
      json(422, {
        error: {
          code: 'invalid_request',
          message: 'the request is not valid',
          faults: [
            { loc: ['body', 'credit_limit_cents'], msg: 'Input should be a multiple of 50' },
          ],
        },
      }),
    )
    await open()
    fireEvent.change(input('Rood staan tot (€)'), { target: { value: '0,25' } })
    await save()
    expect(input('Rood staan tot (€)').getAttribute('aria-invalid')).toBe('true')
    expect(screen.getByText('Input should be a multiple of 50')).toBeTruthy()
  })

  it('an emptied limit blocks the save', async () => {
    await open()
    fireEvent.change(input('Rood staan tot (€)'), { target: { value: '' } })
    await save()
    expect(patches()).toEqual([])
  })

  it('a server change while dirty keeps the input and offers "Overnemen"', async () => {
    await open()
    fireEvent.change(input('Rood staan tot (€)'), { target: { value: '2,50' } })
    served = config({ wallet_required: false }, 4)
    act(() => exchangeStore.setState({ params: { ...PARAMS } }))
    await settle()

    expect(screen.getAllByText('Serverwaarden gewijzigd — overnemen?')).toHaveLength(1)
    expect(input('Rood staan tot (€)').value).toBe('2,50')
    fireEvent.click(screen.getByRole('button', { name: 'Overnemen' }))
    expect(input('Rood staan tot (€)').value).toBe('0,00')
    expect(walletSwitch().getAttribute('aria-checked')).toBe('false')
  })
})
