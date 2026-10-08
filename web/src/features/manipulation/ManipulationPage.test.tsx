// @vitest-environment jsdom
// `/manipulation` (Phase 6 T33: SD20-SD23; AC6, AC7, AC39): news, market events
// and the price jump, re-rendered from the store; Idle only for admin.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { applyMessage, exchangeStore, type ServerMessage, type SnapshotData } from '../exchange'
import { ManipulationPage } from './ManipulationPage'

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

const LONG = 'Happy hour bij de bar: alles halve prijs tot middernacht, echt waar!'

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
  news: [
    { news_id: 1, ts_ms: 1_000, level: 'info', text: 'Oud bericht' },
    { news_id: 2, ts_ms: 2_000, level: 'danger', text: LONG },
  ],
  earnings: {},
  market_events: [],
}

const CONFIG = {
  revision: 3,
  run: { run_id: 1, name: 'Vrijmibo', status: 'live', candle_interval_s: 60 },
  params: {},
  drinks: [
    { drink_id: 1, p_min_cents: 100, p0_cents: 250, p_max_cents: 500 },
    { drink_id: 2, p_min_cents: 150, p0_cents: 300, p_max_cents: 600 },
  ],
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
  fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if ((init?.method ?? 'GET') === 'GET') return Promise.resolve(json(200, CONFIG))
    if (path === '/api/market/jumps') return Promise.resolve(json(201, { version: 6 }))
    return Promise.resolve(json(201, {}))
  })
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

async function open(canEditIdle = true) {
  render(<ManipulationPage canEditIdle={canEditIdle} />)
  await act(async () => {})
  await act(async () => {})
}

const jumpSection = () => screen.getByRole('region', { name: '⚡ Price jump' })

describe('ManipulationPage', () => {
  it('shows the three sections, and Idle only when it may be edited (SD20, AC7)', async () => {
    await open(false)
    for (const name of ['📰 Nieuws', '💥 Market events', '⚡ Price jump']) {
      expect(screen.getByRole('heading', { level: 2, name })).toBeTruthy()
    }
    expect(screen.queryByRole('heading', { name: /Idle/ })).toBeNull()
    cleanup()

    await open(true)
    expect(screen.getByRole('heading', { level: 2, name: '⏳ Idle' })).toBeTruthy()
  })

  describe('📰 Nieuws', () => {
    it('lists the news newest first', async () => {
      await open()
      const items = within(screen.getByRole('list', { name: 'Nieuws' })).getAllByRole('listitem')
      expect(items[0].textContent).toContain(LONG)
      expect(items[1].textContent).toContain('Oud bericht')
    })

    it('"Toevoegen" sends the text and the level in lowercase', async () => {
      await open()
      fireEvent.change(screen.getByLabelText('Bericht'), { target: { value: 'Nieuw!' } })
      fireEvent.change(screen.getByLabelText('Niveau'), { target: { value: 'warning' } })
      fireEvent.click(screen.getByRole('button', { name: 'Toevoegen' }))
      await act(async () => {})

      expect(writes()).toEqual([
        ['/api/news', 'POST', JSON.stringify({ text: 'Nieuw!', level: 'warning' })],
      ])
    })

    it('delete asks with the first 40 characters; Cancel sends nothing (AC39)', async () => {
      await open()
      const first = within(screen.getByRole('list', { name: 'Nieuws' })).getAllByRole('listitem')[0]
      fireEvent.click(within(first).getByRole('button', { name: 'Verwijderen' }))
      expect(
        screen.getByRole('dialog', { name: `'${LONG.slice(0, 40)}' verwijderen?` }),
      ).toBeTruthy()
      fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
      expect(writes()).toEqual([])

      fireEvent.click(within(first).getByRole('button', { name: 'Verwijderen' }))
      fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
      await act(async () => {})
      expect(writes()).toEqual([['/api/news/2', 'DELETE', undefined]])
    })
  })

  describe('💥 Market events', () => {
    const EVENTS = [
      ['💥 Market Crash', 'Marktcrash starten?', 'crash', 'crash'],
      ['🔄 Terug naar start', 'Terug naar start?', 'correction', 'reset'],
      ['🚀 Price Bubble', 'Prijsbubbel starten?', 'bubble', 'bubble'],
    ] as const

    for (const [button, question, kind, word] of EVENTS) {
      it(`"${button}" asks "${question}"; Cancel sends nothing, Confirm starts it`, async () => {
        await open()
        fireEvent.click(screen.getByRole('button', { name: button }))
        expect(screen.getByRole('dialog', { name: question })).toBeTruthy()
        fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
        expect(writes()).toEqual([])

        fireEvent.click(screen.getByRole('button', { name: button }))
        fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
        await act(async () => {})
        expect(writes()).toEqual([
          ['/api/market/events', 'POST', JSON.stringify({ kind, duration_ms: 30_000 })],
        ])
        expect(screen.getByText(`${word} gestart!`)).toBeTruthy()
      })
    }

    it('a running event shows its remaining seconds, on the server clock', async () => {
      vi.spyOn(Date, 'now').mockReturnValue(100_000)
      act(() => exchangeStore.setState({ skewOffsetMs: 2_000 }))
      dispatch('market_event', {
        op: 'start',
        event_id: 9,
        kind: 'crash',
        drink_ids: [1, 2],
        t_start_ms: 100_000,
        t_end_ms: 130_000,
      })
      await open()
      expect(screen.getByText('crash: nog 28 s')).toBeTruthy()
    })
  })

  describe('⚡ Price jump', () => {
    it('an empty or "abc" target leaves "Start jump" disabled, with no request', async () => {
      await open()
      const start = within(jumpSection()).getByRole('button', { name: 'Start jump' })
      expect((start as HTMLButtonElement).disabled).toBe(true)

      fireEvent.change(within(jumpSection()).getByLabelText('Doelprijs (€)'), {
        target: { value: 'abc' },
      })
      expect((start as HTMLButtonElement).disabled).toBe(true)
      fireEvent.click(start)
      await act(async () => {})
      expect(writes()).toEqual([])
    })

    it('a parsed target starts the jump, and the hint shows the bounds', async () => {
      await open()
      expect(within(jumpSection()).getByText('€ 1,00 – € 5,00')).toBeTruthy()

      fireEvent.change(within(jumpSection()).getByLabelText('Doelprijs (€)'), {
        target: { value: '4,20' },
      })
      fireEvent.click(within(jumpSection()).getByRole('button', { name: 'Start jump' }))
      await act(async () => {})
      expect(writes()).toEqual([
        [
          '/api/market/jumps',
          'POST',
          JSON.stringify({ drink_id: 1, target_price_cents: 420, duration_ms: 5_000 }),
        ],
      ])
    })

    it('a bar session reads no config and shows no hint', async () => {
      await open(false)
      expect(fetchMock.mock.calls.filter(([path]) => String(path).includes('/config'))).toEqual([])
      expect(within(jumpSection()).queryByText(/–/)).toBeNull()
    })

    it('the drink select follows a config message removing a drink (SD20)', async () => {
      await open(false)
      const select = within(jumpSection()).getByLabelText('Drankje')
      expect(
        within(select)
          .getAllByRole('option')
          .map((o) => o.textContent),
      ).toEqual(['Bier', 'Wijn'])

      dispatch('config', {
        revision: 4,
        run: { ...RUN, name: 'Vrijmibo' },
        drinks: [DRINKS[0], { ...DRINKS[1], active: false }],
        params: {},
      })

      expect(
        within(select)
          .getAllByRole('option')
          .map((o) => o.textContent),
      ).toEqual(['Bier'])
    })
  })
})
