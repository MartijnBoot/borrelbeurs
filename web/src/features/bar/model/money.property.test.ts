// SD20: the money property test (Phase 5 T8). D-05 dies here or nowhere.
//
// Each case runs a seeded random interleaving against the real wiring -- a
// real store, the real `applyMessage` / `applyPolledState`, the real hold
// buffer, intents and controller -- with a simulated server, a deterministic
// scheduler and a synchronous fake transport. Ticks, foreign orders, WS
// snapshots, polls, hellos (same and new boot), dropped frames, presses,
// releases, taps, "Ververs", clock advances, transport outcomes (201, 200
// replay, 409, 422, 503, network error, timeout, a commit whose answer is
// lost), confirms, cancels, "Opnieuw" and "Sluiten".
//
// Every request the transport sees is checked:
// - AC1: a tap's `(quote_version, unit_price_cents)` is the controller's
//   `displayed` quote at that tap, and that pair appears together in one
//   recorded server message; a confirm's is the head conflict's 409 record;
// - AC9, AC13: a new intent's key has never been seen;
// - AC10: any other request reuses a seen key with a byte-identical body.
//
// No `fast-check` (SD20): mulberry32, inline. `PROPERTY_CASES` sets the
// count (default 10 000); `PROPERTY_SEED` replays one case. The case count and
// base seed are printed; a failure names its case seed.
import { describe, expect, it } from 'vitest'
import { createStore } from 'zustand/vanilla'
import { HttpError } from '../../../lib/http'
import {
  applyMessage,
  applyPolledState,
  initialState,
  type ExchangeState,
  type Quote,
  type ServerMessage,
  type SnapshotData,
} from '../../exchange'
import type { OrderBody, OrderOutcome, Receipt } from '../api/orders'
import { createBarController, type BarController } from './barController'

const ENV = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env
const REPLAY = ENV?.PROPERTY_SEED
const CASES = REPLAY === undefined ? Number(ENV?.PROPERTY_CASES ?? 10_000) : 1
const BASE_SEED = REPLAY === undefined ? Date.now() >>> 0 : Number(REPLAY) >>> 0

const DRINKS = [1, 2, 3]
const THEME = {
  preset: 'blauw' as const,
  revision: 0,
  tokens: {},
  font_family: 'sans-serif',
  images: { bg: null, header: null, logo: null, promo: null },
}
const RUN = {
  run_id: 1,
  tick_interval_ms: 1000,
  candle_interval_ms: 60000,
  quote_grace_versions: 2,
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** A deterministic scheduler: `advance` fires due timers in time order. */
function scheduler() {
  let now = 0
  let nextId = 1
  const timers = new Map<number, { at: number; fn: () => void }>()
  return {
    now: () => now,
    setTimeout(fn: () => void, ms: number): number {
      timers.set(nextId, { at: now + ms, fn })
      return nextId++
    },
    clearTimeout: (id: number) => void timers.delete(id),
    advance(ms: number) {
      const end = now + ms
      for (;;) {
        let due: [number, { at: number; fn: () => void }] | undefined
        for (const entry of timers)
          if (entry[1].at <= end && (!due || entry[1].at < due[1].at)) due = entry
        if (due === undefined) break
        timers.delete(due[0])
        now = due[1].at
        due[1].fn()
      }
      now = end
    },
  }
}

class PropertyFailure extends Error {}

function fail(message: string): never {
  throw new PropertyFailure(message)
}

interface Request {
  key: string
  body: OrderBody
  text: string
  settled: boolean
  ok(outcome: OrderOutcome): void
  err(error: unknown): void
}

type Context =
  | { kind: 'tap'; expected: Quote | null }
  | { kind: 'confirm'; expected: Quote }
  | { kind: 'resend' }

function runCase(seed: number): void {
  const rand = mulberry32(seed)
  const pick = <T>(items: readonly T[]): T => items[Math.floor(rand() * items.length)]
  const clock = scheduler()
  const store = createStore<ExchangeState>(() => initialState)

  // --- the simulated server ---------------------------------------------------
  let bootN = 0
  let seq = 0
  let version = 1
  let orderId = 0
  const prices: Record<number, number> = { 1: 250, 2: 300, 3: 180 }
  const committed = new Map<string, { text: string; receipt: Receipt }>()

  // --- what the test has seen -------------------------------------------------
  const quoted = new Set<string>() // `${version}:${drink}:${cents}` from messages
  const conflicted = new Set<string>() // the same, from 409 bodies
  const sent = new Map<string, string>() // key -> body text
  const requests: Request[] = []
  let context: Context = { kind: 'resend' }
  let posted = 0

  const pairs = (v: number, p: Record<number, number>) =>
    Object.entries(p).map(([d, c]) => `${v}:${d}:${c}`)

  function deliver(message: ServerMessage, drop = false) {
    if (message.version !== null && (message.type === 'tick' || message.type === 'order')) {
      for (const pair of pairs(message.version, prices)) quoted.add(pair)
    }
    if (message.type === 'snapshot') for (const pair of pairs(version, prices)) quoted.add(pair)
    if (!drop) store.setState((s) => applyMessage(s, message, clock.now()), true)
  }

  function envelope(type: ServerMessage['type'], data: unknown, v: number | null = version) {
    return { v: 1, type, seq, ts_ms: clock.now(), run_id: 1, version: v, data } as ServerMessage
  }

  function snapshotData(): SnapshotData {
    const record = (f: (c: number) => object) =>
      Object.fromEntries(DRINKS.map((d) => [d, f(prices[d])]))
    return {
      version,
      run: RUN,
      drinks: DRINKS.map((d) => ({ drink_id: d, name: `D${d}`, active: true })),
      params: {},
      prices: record((c) => ({ price_cents: c, chart_price_cents: c })),
      bars: {},
      news: [],
      earnings: {},
      market_events: [],
    } as SnapshotData
  }

  function move() {
    version += 1
    for (const d of DRINKS) prices[d] = Math.max(50, prices[d] + Math.floor(rand() * 41) - 20)
  }

  function broadcastTick() {
    move()
    seq += 1
    const drinks = Object.fromEntries(
      DRINKS.map((d) => {
        const c = prices[d]
        return [d, { price_cents: c, chart_price_cents: c, candle: [c, c, c, c] }]
      }),
    )
    deliver(envelope('tick', { candle_t_ms: 0, drinks }), rand() < 0.05)
  }

  function broadcastOrder(lines: Receipt['lines']) {
    move()
    seq += 1
    const delta = Object.fromEntries(
      lines.map((l) => [l.drink_id, { qty: l.qty, revenue_cents: l.line_total_cents }]),
    )
    const total = lines.reduce((sum, l) => sum + l.line_total_cents, 0)
    const data = {
      order_id: ++orderId,
      lines,
      total_cents: total,
      earnings_delta: delta,
      prices: Object.fromEntries(
        DRINKS.map((d) => [d, { price_cents: prices[d], chart_price_cents: prices[d] }]),
      ),
    }
    deliver(envelope('order', data), rand() < 0.05)
  }

  function hello(boot: string) {
    deliver(
      envelope(
        'hello',
        {
          boot_id: boot,
          run_id: 1,
          tick_interval_ms: 1000,
          protocol: 1,
          role: 'bar',
          theme: THEME,
        },
        null,
      ),
    )
  }

  /** The server's answer to a commit-shaped request: a replay or a new order. */
  function commit(request: Request): Receipt {
    const stored = committed.get(request.key)
    if (stored !== undefined) {
      if (stored.text !== request.text) fail(`key ${request.key} reused with another body`)
      return stored.receipt
    }
    const line = request.body.lines[0]
    const receipt: Receipt = {
      order_id: orderId + 1,
      version: version + 1,
      wall_ts_ms: clock.now(),
      quote_version: request.body.quote_version,
      lines: [{ ...line, line_total_cents: line.unit_price_cents }],
      total_cents: line.unit_price_cents,
    }
    committed.set(request.key, { text: request.text, receipt })
    broadcastOrder(receipt.lines)
    return receipt
  }

  // --- the transport: synchronous, checks every request ----------------------
  function post({ key, body }: { key: string; body: OrderBody }): Promise<OrderOutcome> {
    const text = JSON.stringify(body)
    posted += 1
    const known = sent.get(key)
    if (context.kind === 'resend') {
      if (known === undefined) fail(`an unseen key ${key} was sent outside a tap or confirm`)
      if (known !== text) fail(`AC10: key ${key} resent with ${text}, first ${known}`)
    } else {
      if (known !== undefined) fail(`AC9/AC13: a new intent reused key ${key}`)
      const expected = context.expected
      if (expected === null) fail('a tap with no displayed quote posted')
      const line = body.lines[0]
      const want = expected.prices[line.drink_id]
      if (body.quote_version !== expected.version || line.unit_price_cents !== want) {
        fail(
          `AC1: ${context.kind} posted ${body.quote_version}/${line.unit_price_cents}, ` +
            `the ${context.kind === 'tap' ? 'displayed quote' : '409 record'} is ` +
            `${expected.version}/${want}`,
        )
      }
      const pair = `${body.quote_version}:${line.drink_id}:${line.unit_price_cents}`
      const seen = context.kind === 'tap' ? quoted : conflicted
      if (!seen.has(pair)) fail(`AC2: ${pair} is not one recorded message's pair`)
      sent.set(key, text)
    }
    const request: Request = { key, body, text, settled: false, ok: () => {}, err: () => {} }
    requests.push(request)
    return {
      then(ok: (o: OrderOutcome) => void, err: (e: unknown) => void) {
        request.ok = ok
        request.err = err
      },
    } as unknown as Promise<OrderOutcome>
  }

  let keyN = 0
  const controller: BarController = createBarController({
    store,
    now: clock.now,
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    post,
    uuid: () => `case-${seed}-key-${++keyN}`,
  })

  function respond(request: Request) {
    request.settled = true
    const roll = rand()
    if (roll < 0.25) {
      request.ok({ kind: 'accepted', receipt: commit(request) })
    } else if (roll < 0.4 && !committed.has(request.key)) {
      move()
      const body = { version, prices: DRINKS.map((d) => ({ drink_id: d, price_cents: prices[d] })) }
      for (const pair of pairs(version, prices)) conflicted.add(pair)
      request.ok({ kind: 'price_changed', body })
    } else if (roll < 0.45 && !committed.has(request.key)) {
      request.err(new HttpError(422, 'invalid_order', 'no'))
    } else if (roll < 0.6) {
      request.err(new HttpError(503, 'persistence_unavailable', 'down'))
    } else if (roll < 0.7) {
      request.err(new TypeError('Failed to fetch'))
    } else if (roll < 0.8) {
      request.err(new DOMException('signal timed out', 'TimeoutError'))
    } else {
      commit(request) // committed, but the answer is lost: the retry must replay
      request.err(new TypeError('Failed to fetch'))
    }
  }

  // --- the interleaving ---------------------------------------------------------
  hello(`boot-${bootN}`)
  deliver(envelope('snapshot', snapshotData()))

  const events = 20 + Math.floor(rand() * 41)
  for (let i = 0; i < events; i++) {
    const roll = rand() * 100
    context = { kind: 'resend' }
    if (roll < 18) broadcastTick()
    else if (roll < 22)
      broadcastOrder([{ drink_id: pick(DRINKS), qty: 1, unit_price_cents: 1, line_total_cents: 1 }])
    else if (roll < 25) deliver(envelope('snapshot', snapshotData()))
    else if (roll < 28) {
      store.setState((s) => applyPolledState(s, snapshotData(), clock.now()), true)
      for (const pair of pairs(version, prices)) quoted.add(pair)
    } else if (roll < 30) hello(`boot-${bootN}`)
    else if (roll < 31) {
      bootN += 1
      seq = 0
      hello(`boot-${bootN}`)
      if (rand() < 0.8) deliver(envelope('snapshot', snapshotData()))
    } else if (roll < 39) controller.press()
    else if (roll < 47) controller.release()
    else if (roll < 62) {
      const expected = controller.view.displayed
      context = { kind: 'tap', expected }
      const before = posted
      const id = controller.tap(pick(DRINKS))
      if ((id === null) !== (posted === before))
        fail('a tap posted without an intent, or vice versa')
    } else if (roll < 65) controller.refresh()
    else if (roll < 78) clock.advance(Math.floor(rand() * 3000))
    else if (roll < 92) {
      const open = requests.filter((r) => !r.settled)
      if (open.length > 0) respond(pick(open))
    } else if (roll < 96) {
      const head = controller.view.headConflict
      if (head !== null) {
        if (rand() < 0.7) {
          context = { kind: 'confirm', expected: head.quote }
          controller.confirm()
        } else controller.cancel()
      }
    } else {
      const unknown = controller.view.entries.filter((e) => e.state === 'unknown')
      if (unknown.length > 0) {
        const entry = pick(unknown)
        if (rand() < 0.75) controller.retry(entry.id)
        else controller.dismiss(entry.id)
      }
    }
    context = { kind: 'resend' }
  }
  controller.dispose()
}

describe('the money property (SD20)', () => {
  it(`holds for ${CASES} random interleavings`, { timeout: 60_000 }, () => {
    console.log(`money property: ${CASES} cases, base seed ${BASE_SEED}`)
    for (let i = 0; i < CASES; i++) {
      const seed = (BASE_SEED + i) >>> 0
      try {
        runCase(seed)
      } catch (error) {
        const reason = error instanceof PropertyFailure ? error.message : String(error)
        expect.fail(`case seed ${seed} (replay: PROPERTY_SEED=${seed}): ${reason}`)
      }
    }
  })
})
