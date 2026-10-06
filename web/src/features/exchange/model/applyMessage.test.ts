// applyMessage against frames recorded from the real server (T12's fixture).
// `at` re-stamps a recorded frame with the seq a scenario needs.
import { describe, expect, it } from 'vitest'
import fixture from './__fixtures__/ws-messages.json'
import { applyMessage, applyPolledState, initialState, type ExchangeState } from './applyMessage'
import { ServerMessage } from './schemas'
import { pulseDirection } from './selectors'

type Of<K extends ServerMessage['type']> = Extract<ServerMessage, { type: K }>

function frame<K extends keyof typeof fixture>(name: K): ServerMessage {
  return ServerMessage.parse(structuredClone(fixture[name]))
}

function at<M extends ServerMessage>(message: M, seq: number, data?: Partial<M['data']>): M {
  return { ...message, seq, data: { ...message.data, ...data } } as M
}

const hello = frame('hello') as Of<'hello'>
const snapshot = frame('snapshot') as Of<'snapshot'>
const tick = frame('tick') as Of<'tick'>
const order = frame('order') as Of<'order'>
const news = frame('news') as Of<'news'>
const eventStart = frame('market_event_start') as Of<'market_event'>
const eventEnd = frame('market_event_end') as Of<'market_event'>
const theme = frame('theme') as Of<'theme'>
const S = snapshot.seq

/** The monotonic receipt time the older cases stamp every frame with (PD1). */
const AT = 1_000

function apply(state: ExchangeState, message: ServerMessage, receivedAt = AT): ExchangeState {
  return applyMessage(state, message, receivedAt)
}

function run(...messages: ServerMessage[]): ExchangeState {
  return messages.reduce((state, message) => apply(state, message), initialState)
}

/** A connected client holding the recorded snapshot at seq S. */
const live = run(at(hello, S), snapshot)

function tickWith(seq: number, drinkId: number, priceCents: number): Of<'tick'> {
  const drinks = structuredClone(tick.data.drinks)
  drinks[drinkId] = { ...drinks[drinkId], price_cents: priceCents }
  return at(tick, seq, { drinks })
}

describe('hello', () => {
  it('takes the boot, the seq and the theme on a first connect', () => {
    const state = run(hello)
    expect(state.bootId).toBe('BOOT')
    expect(state.seq).toBe(hello.seq)
    expect(state.theme?.preset).toBe('blauw')
    expect(state.empty).toBe(false)
  })

  it('with no live run sets the empty state', () => {
    expect(run(at(hello, 0, { run_id: null })).empty).toBe(true)
  })

  it('with a new boot_id discards all live state (AC19)', () => {
    const state = apply(live, at(hello, 2, { boot_id: 'OTHER' }))
    expect(state.bootId).toBe('OTHER')
    expect(state.drinks).toEqual([])
    expect(state.prices).toEqual({})
    expect(state.bars).toEqual({})
    expect(state.news).toEqual([])
    expect(state.marketEvents).toEqual([])
    expect(state.seq).toBe(2)
    expect(state.theme).toEqual(live.theme)
  })

  it('with the same boot_id keeps state and seq, so the replay applies', () => {
    const state = apply(live, at(hello, S + 3))
    expect(state.seq).toBe(S)
    expect(state.drinks).toBe(live.drinks)
    expect(apply(state, at(tick, S + 1)).seq).toBe(S + 1)
  })

  it('ends a pending resync: the reconnect replays or snapshots from the held seq', () => {
    const gapped = apply(live, at(tick, S + 2))
    expect(gapped.awaitingResync).toBe(true)
    expect(apply(gapped, at(hello, S + 2)).awaitingResync).toBe(false)
  })
})

describe('snapshot (AC17)', () => {
  it('replaces drinks, prices, bars, news and market events wholesale', () => {
    const state = live
    expect(state.drinks.map((d) => d.name)).toEqual(['Bier', 'Wijn', 'Fris'])
    expect(state.prices[1]).toEqual({ price_cents: 270, chart_price_cents: 265 })
    expect(state.bars[3]).toEqual(snapshot.data.bars[3])
    expect(state.news.map((n) => n.news_id)).toEqual([2, 1])
    expect(state.marketEvents.map((e) => e.event_id)).toEqual([1])
    expect(state.run?.candle_interval_ms).toBe(60_000)
    expect(state.seq).toBe(S)
    expect(state.empty).toBe(false)
  })

  it('drops what the previous snapshot held', () => {
    const emptier = at(snapshot, S + 4, { news: [], market_events: [], drinks: [] })
    const state = apply(apply(live, at(tick, S + 1)), emptier)
    expect(state.news).toEqual([])
    expect(state.marketEvents).toEqual([])
    expect(state.drinks).toEqual([])
  })

  it('bumps the snapshot generation each time', () => {
    expect(apply(live, at(snapshot, S + 1)).snapshotGen).toBe(live.snapshotGen + 1)
  })
})

describe('seq (AC18)', () => {
  it('applies the next broadcast', () => {
    const state = apply(live, at(tick, S + 1))
    expect(state.seq).toBe(S + 1)
    expect(state.prices[2].chart_price_cents).toBe(264)
  })

  it('on a gap awaits a resync and applies nothing until a snapshot', () => {
    let state = apply(live, at(tick, S + 2))
    expect(state.awaitingResync).toBe(true)
    expect(state.prices).toBe(live.prices)
    expect(state.seq).toBe(S)

    state = apply(state, at(tick, S + 1))
    state = apply(state, at(news, S + 3))
    state = apply(state, at(theme, S + 4, { revision: 9, preset: 'rood' }))
    expect(state.prices).toBe(live.prices)
    expect(state.news).toBe(live.news)
    expect(state.seq).toBe(S)
    // Only a theme gets through, by revision: it never waits on a resync (AC5).
    expect(state.theme?.preset).toBe('rood')

    state = apply(state, at(snapshot, S + 5))
    expect(state.awaitingResync).toBe(false)
    expect(state.seq).toBe(S + 5)
    expect(apply(state, at(tick, S + 6)).seq).toBe(S + 6)
  })

  it('ignores a broadcast it already holds', () => {
    const once = apply(live, at(tick, S + 1))
    expect(apply(once, at(tickWith(S + 1, 1, 999), S + 1))).toBe(once)
  })

  it('accepts unicasts at the held seq', () => {
    const state = apply(live, at(theme, S, { revision: 1, preset: 'groen' }))
    expect(state.theme?.preset).toBe('groen')
    expect(state.seq).toBe(S)
    expect(apply(live, at(frame('pong'), S))).toBe(live)
    expect(apply(live, at(frame('error'), S))).toBe(live)
  })

  it('a resync frame awaits a resync', () => {
    expect(apply(live, at(frame('resync'), S)).awaitingResync).toBe(true)
  })

  it('ignores broadcasts before any baseline', () => {
    expect(run(tick)).toBe(initialState)
  })
})

describe('tick and order', () => {
  it('replaces the last bar when the bucket matches', () => {
    const state = apply(live, at(tick, S + 1))
    expect(state.bars[1]).toEqual([{ t_ms: tick.data.candle_t_ms, o: 260, h: 260, l: 260, c: 260 }])
  })

  it('appends a bar for a new bucket', () => {
    const next = tick.data.candle_t_ms + 60_000
    const state = apply(live, at(tick, S + 1, { candle_t_ms: next }))
    expect(state.bars[2]).toHaveLength(2)
    expect(state.bars[2][1]).toEqual({ t_ms: next, o: 260, h: 264, l: 260, c: 264 })
    expect(state.bars[2][0]).toEqual(snapshot.data.bars[2][0])
  })

  it('an order updates prices but never synthesises a bar (SD3)', () => {
    const state = apply(live, at(order, S + 1))
    expect(state.prices[3]).toEqual({ price_cents: 250, chart_price_cents: 253 })
    expect(state.bars).toBe(live.bars)
  })
})

describe('pulse direction (SD23)', () => {
  it('is rising when the displayed price goes up', () => {
    const state = apply(live, tickWith(S + 1, 2, 300))
    expect(pulseDirection(state, 2)).toBe('rising')
  })

  it('is falling when it goes down', () => {
    const state = apply(live, tickWith(S + 1, 2, 200))
    expect(pulseDirection(state, 2)).toBe('falling')
  })

  it('is none when it is unchanged', () => {
    const state = apply(live, tickWith(S + 1, 2, 260))
    expect(pulseDirection(state, 2)).toBeNull()
  })

  it('counts an order', () => {
    const state = apply(apply(live, tickWith(S + 1, 1, 260)), at(order, S + 2))
    expect(pulseDirection(state, 1)).toBe('rising')
  })

  it('is none after a snapshot, whatever the price did', () => {
    const risen = apply(live, tickWith(S + 1, 2, 300))
    const state = apply(risen, at(snapshot, S + 2))
    expect(pulseDirection(state, 2)).toBeNull()
    expect(pulseDirection(state, 1)).toBeNull()
  })
})

describe('market events and news', () => {
  it('starts an event once', () => {
    const cleared = at(snapshot, S, { market_events: [] })
    const base = run(at(hello, S), cleared)
    const state = apply(apply(base, at(eventStart, S + 1)), at(eventStart, S + 2))
    expect(state.marketEvents).toHaveLength(1)
    expect(state.marketEvents[0]).toEqual({
      event_id: 1,
      kind: 'correction',
      drink_ids: [1, 2, 3],
      t_start_ms: eventStart.data.t_start_ms,
      t_end_ms: eventStart.data.t_end_ms,
    })
  })

  it('ends an event, and a late end is a no-op', () => {
    const ended = apply(live, at(eventEnd, S + 1))
    expect(ended.marketEvents).toEqual([])
    const again = apply(ended, at(eventEnd, S + 2))
    expect(again.marketEvents).toBe(ended.marketEvents)
    expect(again.seq).toBe(S + 2)
  })

  it('adds news newest first and deletes by id', () => {
    const item = { ...news.data.item, news_id: 7 }
    const added = apply(live, at(news, S + 1, { item }))
    expect(added.news.map((n) => n.news_id)).toEqual([7, 2, 1])
    const deleted = apply(added, at(news, S + 2, { op: 'delete', item }))
    expect(deleted.news.map((n) => n.news_id)).toEqual([2, 1])
  })

  it('keeps at most the snapshot cap of 50 items', () => {
    let state = live
    for (let k = 0; k < 60; k++) {
      state = apply(state, at(news, S + 1 + k, { item: { ...news.data.item, news_id: 100 + k } }))
    }
    expect(state.news).toHaveLength(50)
    expect(state.news[0].news_id).toBe(159)
  })
})

describe('theme (AC7)', () => {
  const held = run(at(hello, S), at(theme, S, { revision: 3, preset: 'paars' }))

  it.each([
    ['equal', 3, 'paars'],
    ['lower', 2, 'paars'],
    ['higher', 4, 'rood'],
  ] as const)('a %s revision leaves %s', (_case, revision, preset) => {
    const state = apply(held, at(theme, S + 1, { revision, preset: 'rood' }))
    expect(state.theme?.preset).toBe(preset)
    expect(state.seq).toBe(S + 1)
  })

  it('hello applies its theme only when the revision is higher', () => {
    const lower = apply(held, at(hello, S, { theme: { ...hello.data.theme, revision: 1 } }))
    expect(lower.theme?.preset).toBe('paars')
  })

  it('a theme past a gap applies by revision and starts no resync', () => {
    const state = apply(live, at(theme, S + 2, { revision: 7, preset: 'rood' }))
    expect(state.theme?.preset).toBe('rood')
    expect(state.awaitingResync).toBe(false)
    expect(state.seq).toBe(S)
    // The gap is still there: the next priced broadcast finds it and resyncs.
    expect(apply(state, at(tick, S + 3)).awaitingResync).toBe(true)
  })

  it('with no live run, a reconnect the server cannot replay still re-themes', () => {
    // Same boot, held seq 4; the missed frames aged out, so no snapshot follows.
    const held = run(at(hello, 4, { run_id: null }))
    let state = apply(held, at(hello, 9, { run_id: null }))
    state = apply(state, at(theme, 9, { revision: 1, preset: 'groen' }))
    state = apply(state, at(theme, 10, { revision: 2, preset: 'paars' }))
    expect(state.awaitingResync).toBe(false)
    expect(state.theme?.preset).toBe('paars')
  })

  it('with no live run, theme broadcasts still apply (AC5)', () => {
    const empty = run(at(hello, 4, { run_id: null }))
    const state = apply(empty, at(theme, 5, { revision: 1, preset: 'groen' }))
    expect(state.theme?.preset).toBe('groen')
    expect(state.seq).toBe(5)
  })

  it('with no live run, a resync no snapshot can end still re-themes (AC5)', () => {
    // A hub overflow sends `resync`; the server answers the request with only
    // the theme catch-up, because there is no snapshot to send.
    const empty = run(at(hello, 4, { run_id: null }), at(frame('resync'), 4))
    let state = apply(empty, at(theme, 4, { revision: 1, preset: 'groen' }))
    state = apply(state, at(theme, 6, { revision: 2, preset: 'paars' }))
    expect(state.theme?.preset).toBe('paars')
    expect(state.seq).toBe(4)
  })
})

describe('quote (Phase 5 T4: AC2, SD2, PD1, PD4)', () => {
  const connected = apply(initialState, at(hello, S))

  it('is null before any snapshot', () => {
    expect(initialState.quote).toBeNull()
    expect(connected.quote).toBeNull()
  })

  it("a snapshot's quote is its data.version and price_cents, stamped with receivedAt", () => {
    const state = apply(connected, snapshot, 42)
    expect(state.quote?.version).toBe(snapshot.data.version)
    expect(state.quote?.prices).toEqual({ 1: 270, 2: 260, 3: 250 })
    expect(state.quote?.receivedAt).toBe(42)
    expect(Object.isFrozen(state.quote)).toBe(true)
  })

  it("an in-sequence tick's quote is the envelope version and the tick's price_cents", () => {
    const state = apply(live, tickWith(S + 1, 2, 300), 77)
    expect(state.quote?.version).toBe(tick.version)
    expect(state.quote?.prices).toEqual({ 1: 260, 2: 300, 3: 260 })
    expect(state.quote?.receivedAt).toBe(77)
  })

  it("an in-sequence order's quote is the envelope version and the order's prices", () => {
    const state = apply(live, at({ ...order, version: 6 }, S + 1), 88)
    expect(state.quote?.version).toBe(6)
    expect(state.quote?.prices).toEqual({ 1: 270, 2: 260, 3: 250 })
    expect(state.quote?.receivedAt).toBe(88)
  })

  it('a quote never mixes messages: each one replaces it whole', () => {
    const afterTick = apply(live, at({ ...tickWith(S + 1, 1, 300), version: 6 }, S + 1), 1)
    const afterOrder = apply(afterTick, at({ ...order, version: 7 }, S + 2), 2)
    expect(afterTick.quote).toMatchObject({ version: 6, prices: { 1: 300 }, receivedAt: 1 })
    expect(afterOrder.quote).toMatchObject({ version: 7, prices: { 1: 270 }, receivedAt: 2 })
  })

  it('a dropped frame leaves the quote as it was: gap, stale seq, awaiting resync', () => {
    const gapped = apply(live, at(tick, S + 2), 5)
    expect(gapped.quote).toBe(live.quote)
    expect(apply(gapped, at(tick, S + 1), 6).quote).toBe(live.quote) // awaiting resync
    const once = apply(live, at(tick, S + 1), 7)
    expect(apply(once, at(order, S + 1), 8).quote).toBe(once.quote) // already held
    expect(apply(once, at(order, S), 9).quote).toBe(once.quote) // older
  })

  it('a tick or order without a version keeps the latest quote (PD4)', () => {
    expect(apply(live, at({ ...tick, version: null }, S + 1)).quote).toBe(live.quote)
    expect(apply(live, at({ ...order, version: null }, S + 1)).quote).toBe(live.quote)
  })

  it('a new boot_id clears it, and the next snapshot rebuilds it (AC26)', () => {
    const rebooted = apply(live, at(hello, 2, { boot_id: 'OTHER' }))
    expect(rebooted.quote).toBeNull()
    const rebuilt = apply(rebooted, at(snapshot, 2), 99)
    expect(rebuilt.quote).toMatchObject({ version: snapshot.data.version, receivedAt: 99 })
  })

  it('the same boot_id keeps it', () => {
    expect(apply(live, at(hello, S)).quote).toBe(live.quote)
  })

  it('a polled snapshot sets it with the given receivedAt (AC25)', () => {
    const polled = applyPolledState(live, { ...snapshot.data, version: 12 }, 123)
    expect(polled.quote).toMatchObject({ version: 12, receivedAt: 123 })
  })

  it('other broadcasts leave it alone', () => {
    expect(apply(live, at(news, S + 1)).quote).toBe(live.quote)
    expect(apply(live, at(eventStart, S + 1)).quote).toBe(live.quote)
  })
})
