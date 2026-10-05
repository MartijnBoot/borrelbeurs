/**
 * WebSocket frames for the board's shape cases (PD14), built from T12's
 * recorded fixture -- the real server's own shapes, so they cannot drift
 * from what the server sends (SD26) -- and a mocked `/ws` that speaks the
 * handshake: the client's `hello` is answered with the frames the test chose
 * (a `hello` first), every `ping` with a `pong` on this process's clock --
 * this process plays the server, so its clock is the server's.
 *
 * Login, `/api/*` and `/theme.css` still come from the real app; only the
 * socket is the test's.
 */
import type { Page, WebSocketRoute } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import type {
  MarketEventInfo,
  NewsItem,
  ServerMessage,
} from '../src/features/exchange/model/schemas'

type Of<K extends ServerMessage['type']> = Extract<ServerMessage, { type: K }>

const FIXTURE = JSON.parse(
  readFileSync(
    join(import.meta.dirname, '../src/features/exchange/model/__fixtures__/ws-messages.json'),
    'utf-8',
  ),
) as Record<string, ServerMessage>

function recorded<K extends ServerMessage['type']>(name: string, type: K): Of<K> {
  const frame = structuredClone(FIXTURE[name])
  if (frame?.type !== type) throw new Error(`fixture ${name} is not a ${type}`)
  return frame as Of<K>
}

export const XSS = '<img src=x onerror=alert(1)>'

const NAMES = [
  'Bier',
  'Wijn',
  'Fris',
  'Shotje',
  'Cocktail',
  'Speciaalbier',
  'Cider',
  'Mix',
  'Water',
]

export interface Drink {
  drink_id: number
  name: string
}

/** `n` drinks, ids 1..n; `names` overrides the first few names. */
export function drinks(n: number, names: string[] = []): Drink[] {
  return Array.from({ length: n }, (_, i) => ({ drink_id: i + 1, name: names[i] ?? NAMES[i] }))
}

const CANDLE_MS = 60_000

export function hello(runId: number | null, tsMs = Date.now()): Of<'hello'> {
  const frame = recorded('hello', 'hello')
  return {
    ...frame,
    seq: 0,
    ts_ms: tsMs,
    run_id: runId,
    data: { ...frame.data, boot_id: `e2e-${tsMs}`, run_id: runId, role: 'display' },
  }
}

export interface SnapshotOptions {
  drinks: Drink[]
  news?: NewsItem[]
  marketEvents?: MarketEventInfo[]
  tsMs?: number
}

/** A snapshot of `drinks` at 2,60 each, with ten one-minute bars apiece. */
export function snapshot(options: SnapshotOptions): Of<'snapshot'> {
  const frame = recorded('snapshot', 'snapshot')
  const tsMs = options.tsMs ?? Date.now()
  const lastBucket = Math.floor(tsMs / CANDLE_MS) * CANDLE_MS
  const prices: Of<'snapshot'>['data']['prices'] = {}
  const bars: Of<'snapshot'>['data']['bars'] = {}
  for (const { drink_id } of options.drinks) {
    prices[drink_id] = { price_cents: 260, chart_price_cents: 260 }
    bars[drink_id] = Array.from({ length: 10 }, (_, i) => {
      const c = 250 + ((i * 7 + drink_id * 3) % 20)
      return { t_ms: lastBucket - (9 - i) * CANDLE_MS, o: c - 3, h: c + 4, l: c - 5, c }
    })
  }
  return {
    ...frame,
    seq: 0,
    ts_ms: tsMs,
    data: {
      ...frame.data,
      drinks: options.drinks,
      prices,
      bars,
      earnings: {},
      news: options.news ?? [],
      market_events: options.marketEvents ?? [],
    },
  }
}

/** The recorded order, next after `snapshot` (seq 1), moving `drinkId` to `priceCents`. */
export function order(drinkId: number, priceCents: number): Of<'order'> {
  const frame = recorded('order', 'order')
  const price = { price_cents: priceCents, chart_price_cents: priceCents }
  return {
    ...frame,
    seq: 1,
    ts_ms: Date.now(),
    data: { ...frame.data, prices: { [drinkId]: price } },
  }
}

export function newsItem(text: string, tsMs = Date.now()): NewsItem {
  return { news_id: 1, ts_ms: tsMs, level: 'danger', text }
}

export interface MockSocket {
  /** The socket the page has open now, once it has connected. */
  current(): WebSocketRoute | undefined
  send(frame: ServerMessage): void
}

/**
 * Route `/ws` to a mock that answers the client's `hello` with `frames()`,
 * evaluated then -- a `hello` first. Call before the page logs in.
 */
export async function mockSocket(page: Page, frames: () => ServerMessage[]): Promise<MockSocket> {
  let socket: WebSocketRoute | undefined
  await page.routeWebSocket('**/ws', (ws) => {
    socket = ws
    ws.onMessage((raw) => {
      const message = JSON.parse(String(raw)) as { type: string }
      if (message.type === 'hello') {
        for (const frame of frames()) ws.send(JSON.stringify(frame))
      } else if (message.type === 'ping') {
        const pong = recorded('pong', 'pong')
        const now = Date.now()
        ws.send(JSON.stringify({ ...pong, ts_ms: now, data: { server_ts_ms: now } }))
      }
    })
  })
  return {
    current: () => socket,
    send: (frame) => socket?.send(JSON.stringify(frame)),
  }
}
