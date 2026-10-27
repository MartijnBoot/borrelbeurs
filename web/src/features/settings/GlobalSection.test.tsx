// @vitest-environment jsdom
// Globale instellingen (Phase 6 T25: SD8, SD25, SD27; AC1, AC2, AC3, AC5, AC28).
// The D-03 gate: an untouched save sends nothing; an edit sends exactly its field.
// B-01 T5: the new names, and an (i) per field (E1-E10).
// B-03 T4: the six noise controls after Kaarsbreedte (SD4-SD6; AC10-AC14; E34-E39).
// B-06 T17: "Wallet verplicht" and "Rood staan tot" at the top level (SD1-SD3; AC2, AC3).
// B-07 T10: a Prijsstap that moves a bound asks first (SD3; AC10), and the
// server's `bounds_collision` shows under Prijsstap (AC8).
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { expectExplained } from '../../components/ui/infoTesting'
import { exchangeStore } from '../exchange'
import explanations from './explanations.json'
import { GlobalSection } from './GlobalSection'

const GLOBAL_KEYS = [
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
] as const

// B-03 SD4's order; Willekeurige ruis is a switch.
const NOISE_KEYS = [
  'bm_enabled',
  'bm_sigma_y',
  'bm_dt_minutes',
  'flow_vol_amp',
  'flow_beta',
  'y_clip',
] as const

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

function config(params: Record<string, unknown> = PARAMS, candle = 60, revision = 3) {
  return {
    revision,
    run: {
      run_id: 7,
      name: 'Vrijmibo',
      status: 'live',
      candle_interval_s: candle,
      wallet_required: true,
      credit_limit_cents: 0,
    },
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
  fireEvent.click(screen.getByRole('button', { name: 'Opslaan instellingen' }))
  await settle()
}

/** Every PATCH is a 422 naming `loc`. */
function refuse(loc: string[], msg: string) {
  fetchMock.mockImplementation((path: string, init?: RequestInit) => {
    if (init?.method === 'PATCH') {
      return Promise.resolve(
        json(422, {
          error: {
            code: 'invalid_request',
            message: 'the request is not valid',
            faults: [{ loc, msg }],
          },
        }),
      )
    }
    if (path === '/api/runs/current') {
      return Promise.resolve(json(200, { run_id: 7, name: 'Vrijmibo', status: 'live' }))
    }
    return Promise.resolve(json(200, served))
  })
}

const input = (label: string) => screen.getByLabelText(label) as HTMLInputElement
const noiseSwitch = () => screen.getByRole('switch', { name: 'Willekeurige ruis' })
const NOISE_NUMBERS = [
  'Sterkte ruis',
  'Ritme ruis (min)',
  'Extra ruis bij drukte',
  'Reactiesnelheid drukte',
  'Grens ruis',
]

describe('GlobalSection', () => {
  it('shows every SD8 global field with its B-01 name and the server value', async () => {
    await open()
    expect((screen.getByLabelText('Beweging per bestelling') as HTMLInputElement).value).toBe('0,6')
    expect((screen.getByLabelText('Kaarsbreedte (sec)') as HTMLInputElement).value).toBe('60')
    for (const label of [
      'Prijsstap (€)',
      'Drukdrempel',
      'Concurrentie tussen drankjes',
      'Trek naar gemiddelde prijs',
      'Nawerking van bestellingen',
      'Geheugen van bestellingen',
      'Grafiekgeschiedenis (min)',
      'Ritme stille drankjes (min)',
    ]) {
      expect(screen.getByLabelText(label)).toBeTruthy()
    }
  })

  it.each(GLOBAL_KEYS)('%s has an (i) with its explanation (B-01 AC1, AC7)', async (key) => {
    const { container } = render(<GlobalSection />)
    await settle()
    expect(screen.getByLabelText(explanations[key].name)).toBeTruthy()
    expectExplained(container, explanations[key])
  })

  it('opening every (i) leaves the form clean: saving sends nothing (B-01 AC5)', async () => {
    await open()
    for (const button of screen.getAllByRole('button', { name: /^Uitleg: / })) {
      fireEvent.click(button)
      fireEvent.click(button)
    }
    await save()
    expect(patches()).toEqual([])
    expect(screen.getByRole('status').textContent).toBe('Niets te wijzigen')
  })

  it('"Opslaan instellingen" is text only (B-02 SD4)', async () => {
    await open()
    const button = screen.getByRole('button', { name: 'Opslaan instellingen' })
    expect(button.textContent).toBe('Opslaan instellingen')
    expect(button.querySelector('svg')).toBeNull()
  })

  it('an untouched save sends nothing and says "Niets te wijzigen" (AC2)', async () => {
    await open()
    await save()
    expect(patches()).toEqual([])
    expect(screen.getByRole('status').textContent).toBe('Niets te wijzigen')
  })

  it('editing eta sends {params: {eta}} only (AC1)', async () => {
    await open()
    fireEvent.change(screen.getByLabelText('Beweging per bestelling'), { target: { value: '0,9' } })
    await save()
    expect(patches()).toEqual([{ params: { eta: 0.9 } }])
  })

  it('the candle interval goes at the top level', async () => {
    await open()
    fireEvent.change(screen.getByLabelText('Kaarsbreedte (sec)'), {
      target: { value: '30' },
    })
    await save()
    expect(patches()).toEqual([{ candle_interval_s: 30 }])
  })

  it('a cleared field blocks the save (AC3)', async () => {
    await open()
    fireEvent.change(screen.getByLabelText('Drukdrempel'), { target: { value: '' } })
    await save()
    expect(patches()).toEqual([])
    expect(screen.getByText('Verplicht')).toBeTruthy()
  })

  it('a config while dirty keeps the input and offers the server values (AC5)', async () => {
    await open()
    fireEvent.change(screen.getByLabelText('Beweging per bestelling'), { target: { value: '0,9' } })
    served = config({ ...PARAMS, K: 20 }, 60, 4)

    act(() => exchangeStore.setState({ params: { ...PARAMS, K: 20 } }))
    await settle()

    expect(screen.getByText('Serverwaarden gewijzigd — overnemen?')).toBeTruthy()
    expect((screen.getByLabelText('Beweging per bestelling') as HTMLInputElement).value).toBe('0,9')
    fireEvent.click(screen.getByRole('button', { name: 'Overnemen' }))
    expect((screen.getByLabelText('Beweging per bestelling') as HTMLInputElement).value).toBe('0,6')
    expect((screen.getByLabelText('Drukdrempel') as HTMLInputElement).value).toBe('20')
  })

  it('a config while clean reloads silently', async () => {
    await open()
    served = config({ ...PARAMS, K: 20 }, 60, 4)
    act(() => exchangeStore.setState({ params: { ...PARAMS, K: 20 } }))
    await settle()
    expect((screen.getByLabelText('Drukdrempel') as HTMLInputElement).value).toBe('20')
    expect(screen.queryByText('Serverwaarden gewijzigd — overnemen?')).toBeNull()
  })

  it('a 422 on candle_interval_s shows under that field', async () => {
    refuse(['body', 'candle_interval_s'], 'multiple of 5')
    await open()
    fireEvent.change(screen.getByLabelText('Kaarsbreedte (sec)'), {
      target: { value: '7' },
    })
    await save()

    const input = screen.getByLabelText('Kaarsbreedte (sec)')
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(screen.getByText('multiple of 5')).toBeTruthy()
  })

  describe('the noise (B-03)', () => {
    it('shows the six after Kaarsbreedte, in SD4 order, with the server values (AC10)', async () => {
      await open()
      const controls = [input('Kaarsbreedte (sec)'), noiseSwitch(), ...NOISE_NUMBERS.map(input)]
      for (let i = 1; i < controls.length; i++) {
        const order = controls[i - 1].compareDocumentPosition(controls[i])
        expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
      }
      expect(noiseSwitch().getAttribute('aria-checked')).toBe('true')
      expect(NOISE_NUMBERS.map((label) => input(label).value)).toEqual([
        '0,18',
        '1',
        '0,7',
        '0,25',
        '6',
      ])
    })

    it('the switch shows the server off as off (AC10)', async () => {
      served = config({ ...PARAMS, bm_enabled: false })
      await open()
      expect(noiseSwitch().getAttribute('aria-checked')).toBe('false')
    })

    it.each(NOISE_KEYS)('%s has an (i) with its explanation (AC14)', async (key) => {
      const { container } = render(<GlobalSection />)
      await settle()
      expectExplained(container, explanations[key])
    })

    it('editing Sterkte ruis sends {params: {bm_sigma_y}} only (AC11)', async () => {
      await open()
      fireEvent.change(input('Sterkte ruis'), { target: { value: '0,5' } })
      await save()
      expect(patches()).toEqual([{ params: { bm_sigma_y: 0.5 } }])
    })

    it('toggling Willekeurige ruis sends {params: {bm_enabled: false}} only (AC11)', async () => {
      await open()
      fireEvent.click(noiseSwitch())
      await save()
      expect(patches()).toEqual([{ params: { bm_enabled: false } }])
    })

    it('a 422 on y_clip shows under Grens ruis (AC11)', async () => {
      refuse(['body', 'params', 'y_clip'], 'Input should be less than or equal to 20')
      await open()
      fireEvent.change(input('Grens ruis'), { target: { value: '25' } })
      await save()
      expect(input('Grens ruis').getAttribute('aria-invalid')).toBe('true')
      expect(screen.getByText('Input should be less than or equal to 20')).toBeTruthy()
    })

    it('a 422 on bm_enabled shows beside the switch (PD5)', async () => {
      refuse(['body', 'params', 'bm_enabled'], 'Input should be a valid boolean')
      await open()
      fireEvent.click(noiseSwitch())
      await save()
      expect(screen.getByText('Input should be a valid boolean')).toBeTruthy()
    })

    it('with the switch off the five stay editable and save (AC12)', async () => {
      await open()
      fireEvent.click(noiseSwitch())
      for (const label of NOISE_NUMBERS) expect(input(label).disabled).toBe(false)
      fireEvent.change(input('Ritme ruis (min)'), { target: { value: '0,5' } })
      await save()
      expect(patches()).toEqual([{ params: { bm_enabled: false, bm_dt_minutes: 0.5 } }])
    })

    it('a server change of y_clip while Sterkte ruis is dirty offers "Overnemen" (AC13)', async () => {
      await open()
      fireEvent.change(input('Sterkte ruis'), { target: { value: '0,5' } })
      served = config({ ...PARAMS, y_clip: 3 }, 60, 4)

      act(() => exchangeStore.setState({ params: { ...PARAMS, y_clip: 3 } }))
      await settle()

      expect(screen.getByText('Serverwaarden gewijzigd — overnemen?')).toBeTruthy()
      expect(input('Sterkte ruis').value).toBe('0,5')
      fireEvent.click(screen.getByRole('button', { name: 'Overnemen' }))
      expect(input('Sterkte ruis').value).toBe('0,18')
      expect(input('Grens ruis').value).toBe('3')
    })
  })

  describe('the wallet settings (B-06)', () => {
    const walletSwitch = () => screen.getByRole('switch', { name: 'Wallet verplicht' })

    it('show the server values: the switch on, the limit in euros (SD1, SD2)', async () => {
      served = { ...config(), run: { ...config().run, credit_limit_cents: 250 } }
      await open()
      expect(walletSwitch().getAttribute('aria-checked')).toBe('true')
      expect(input('Rood staan tot (€)').value).toBe('2,50')
    })

    it.each(['wallet_required', 'credit_limit_cents'] as const)(
      '%s has an (i) with its explanation (AC3)',
      async (key) => {
        const { container } = render(<GlobalSection />)
        await settle()
        expectExplained(container, explanations[key])
      },
    )

    it('toggling "Wallet verplicht" sends {wallet_required: false} at the top level (AC2)', async () => {
      await open()
      fireEvent.click(walletSwitch())
      await save()
      expect(patches()).toEqual([{ wallet_required: false }])
    })

    it('a limit of 2,50 sends {credit_limit_cents: 250} at the top level (AC2)', async () => {
      await open()
      fireEvent.change(input('Rood staan tot (€)'), { target: { value: '2,50' } })
      await save()
      expect(patches()).toEqual([{ credit_limit_cents: 250 }])
    })

    it('a 422 on credit_limit_cents shows under that field (AC2)', async () => {
      refuse(['body', 'credit_limit_cents'], 'Input should be a multiple of 50')
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
  })
})

describe('GlobalSection: a Prijsstap that moves bounds (B-07)', () => {
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

  beforeEach(() => {
    served = {
      ...config({ ...PARAMS, step_quant: 0.1 }),
      drinks: [drink(11, 0, 'Bier', 150, 310), drink(12, 1, 'Wijn', 150, 300)],
    }
  })

  const prijsstap = (value: string) =>
    fireEvent.change(input('Prijsstap (€)'), { target: { value } })

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
      'Past niet bij Bier: de grenzen worden 2,00\u20132,00. ' +
      'Past niet bij Wijn: de grenzen worden 2,00\u20132,00.'
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
