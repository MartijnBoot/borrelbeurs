// The WebSocket state machine on fake timers with a fake socket (T14).
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'
import { createStore, type StoreApi } from 'zustand/vanilla'
import fixture from './__fixtures__/ws-messages.json'
import { initialState, type ExchangeState } from './applyMessage'
import { createExchangeClient, type ExchangeClient, type SocketLike } from './client'

class FakeSocket implements SocketLike {
  sent: unknown[] = []
  closedWith: number | undefined | null = null
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null

  readonly url: string

  constructor(url: string) {
    this.url = url
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data))
  }

  close(code?: number): void {
    this.closedWith = code
  }

  // --- driven by the test ---
  open(): void {
    this.onopen?.()
  }

  receive(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }

  drop(code = 1006): void {
    this.onclose?.({ code })
  }

  types(): string[] {
    return this.sent.map((m) => (m as { type: string }).type)
  }
}

let sockets: FakeSocket[]
let store: StoreApi<ExchangeState>
let fetchState: Mock<() => Promise<{ status: number; body: unknown }>>
let onSessionLost: Mock<() => void>
let random: () => number
let client: ExchangeClient

const latest = () => sockets[sockets.length - 1]
const at = <T extends { seq: number }>(frame: T, seq: number): T => ({ ...frame, seq })

beforeEach(() => {
  vi.useFakeTimers({ now: 1_000_000 })
  sockets = []
  store = createStore<ExchangeState>(() => initialState)
  fetchState = vi.fn<() => Promise<{ status: number; body: unknown }>>()
  fetchState.mockResolvedValue({ status: 200, body: fixture.snapshot.data })
  onSessionLost = vi.fn<() => void>()
  random = () => 0.5
  client = createExchangeClient({
    url: 'wss://example.test/ws',
    createSocket: (url) => {
      const socket = new FakeSocket(url)
      sockets.push(socket)
      return socket
    },
    fetchState: () => fetchState(),
    onSessionLost: () => onSessionLost(),
    random: () => random(),
    now: () => Date.now(),
    store,
  })
})

afterEach(() => {
  client.stop()
  vi.useRealTimers()
})

function connect(): FakeSocket {
  client.start()
  latest().open()
  latest().receive(fixture.hello)
  return latest()
}

describe('on open', () => {
  it('sends hello with nothing held, then with the held boot and seq', async () => {
    fetchState.mockRejectedValue(new TypeError('network')) // no poll lands meanwhile
    const first = connect()
    expect(first.sent[0]).toEqual({ type: 'hello', boot_id: '', last_seq: 0 })
    first.receive(at(fixture.snapshot, 5))
    first.drop()
    await vi.advanceTimersByTimeAsync(500)
    latest().open()
    expect(latest().sent[0]).toEqual({ type: 'hello', boot_id: 'BOOT', last_seq: 5 })
  })

  it('after a polled state lands, asks for a snapshot, not a replay', async () => {
    // The poll is newer than the held seq; a replay from it would tick the board
    // backwards (and pulse) until it caught up (SD17, SD23).
    const first = connect()
    first.receive(at(fixture.snapshot, 5))
    first.drop()
    await vi.advanceTimersByTimeAsync(500)
    latest().open()
    expect(latest().sent[0]).toEqual({ type: 'hello', boot_id: '', last_seq: 5 })

    fetchState.mockRejectedValue(new TypeError('network'))
    latest().drop() // nothing polled since that open: replay again
    await vi.advanceTimersByTimeAsync(1000)
    latest().open()
    expect(latest().sent[0]).toEqual({ type: 'hello', boot_id: 'BOOT', last_seq: 5 })
  })

  it('marks the store open', () => {
    connect()
    expect(store.getState().status).toBe('open')
  })
})

describe('liveness (AC13, AC14)', () => {
  it('pings at 15, 30 and 45 s', async () => {
    const socket = connect()
    for (const t of [15_000, 30_000, 45_000]) {
      await vi.advanceTimersByTimeAsync(15_000)
      expect(socket.types().filter((x) => x === 'ping')).toHaveLength(t / 15_000)
      socket.receive(at(fixture.pong, 0)) // any frame resets the deadline
    }
    expect(socket.closedWith).toBeNull()
  })

  it('closes and reconnects after 45 s with no frame', async () => {
    const socket = connect()
    await vi.advanceTimersByTimeAsync(44_999)
    expect(socket.closedWith).toBeNull()
    await vi.advanceTimersByTimeAsync(1)
    expect(socket.closedWith).not.toBeNull()
    expect(store.getState().status).toBe('offline')
    await vi.advanceTimersByTimeAsync(500)
    expect(sockets).toHaveLength(2)
  })

  it('a frame at 44 s keeps the socket', async () => {
    const socket = connect()
    await vi.advanceTimersByTimeAsync(44_000)
    socket.receive(at(fixture.pong, 0))
    await vi.advanceTimersByTimeAsync(44_000)
    expect(socket.closedWith).toBeNull()
  })
})

describe('reconnect backoff (AC15)', () => {
  it.each([
    [0, 350],
    [0.5, 500],
    [1, 650],
  ])('with random() = %d the first retry waits %i ms', async (r, delay) => {
    random = () => r
    connect().drop()
    await vi.advanceTimersByTimeAsync(delay - 1)
    expect(sockets).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(sockets).toHaveLength(2)
  })

  it('grows by 1.7 per failed attempt and resets after an open', async () => {
    connect().drop()
    for (const delay of [500, 850, 1_445]) {
      const before = sockets.length
      await vi.advanceTimersByTimeAsync(delay)
      expect(sockets).toHaveLength(before + 1)
      latest().drop()
    }
    await vi.advanceTimersByTimeAsync(2_457) // 500 * 1.7^3 = 2456.5, rounded
    latest().open()
    latest().drop()
    const before = sockets.length
    await vi.advanceTimersByTimeAsync(500)
    expect(sockets).toHaveLength(before + 1)
  })
})

describe('polling (AC16, SD17)', () => {
  it('polls at once on close, every 5 s while offline, and stops on open', async () => {
    random = () => 1 // retries at 650, 1105, ... -- each one fails until opened below
    connect().drop()
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchState).toHaveBeenCalledTimes(1)
    for (let k = 0; k < 4; k++) {
      await vi.advanceTimersByTimeAsync(650)
      latest().drop()
    }
    // 650 * 4 = 2.6 s: no second poll yet
    expect(fetchState).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2_400)
    expect(fetchState).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(5_000)
    expect(fetchState).toHaveBeenCalledTimes(3)

    await vi.advanceTimersByTimeAsync(20_000)
    latest().open()
    const calls = fetchState.mock.calls.length
    await vi.advanceTimersByTimeAsync(20_000)
    expect(fetchState).toHaveBeenCalledTimes(calls)
  })

  it('applies a polled state as a snapshot', async () => {
    connect().drop()
    await vi.advanceTimersByTimeAsync(0)
    expect(store.getState().drinks.map((d) => d.name)).toEqual(['Bier', 'Wijn', 'Fris'])
    expect(store.getState().status).toBe('offline')
  })

  it('a poll 409 is the empty state', async () => {
    fetchState.mockResolvedValue({
      status: 409,
      body: { error: { code: 'no_live_run', message: 'x' } },
    })
    connect().drop()
    await vi.advanceTimersByTimeAsync(0)
    expect(store.getState().empty).toBe(true)
  })

  it('a failed poll is ignored', async () => {
    fetchState.mockRejectedValue(new TypeError('network'))
    connect().drop()
    await vi.advanceTimersByTimeAsync(0)
    expect(store.getState().status).toBe('offline')
    expect(onSessionLost).not.toHaveBeenCalled()
  })
})

describe('resync (AC18)', () => {
  it('a gap sends exactly one resync_request until the snapshot', () => {
    const socket = connect()
    socket.receive(at(fixture.snapshot, 5))
    socket.receive(at(fixture.tick, 7))
    socket.receive(at(fixture.tick, 8))
    expect(socket.types().filter((x) => x === 'resync_request')).toHaveLength(1)
    socket.receive(at(fixture.snapshot, 8))
    socket.receive(at(fixture.tick, 10))
    expect(socket.types().filter((x) => x === 'resync_request')).toHaveLength(2)
  })
})

describe('session loss (AC20, PD10)', () => {
  it.each([4401, 1008])('close %i calls onSessionLost and does not reconnect', async (code) => {
    connect().drop(code)
    expect(onSessionLost).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(sockets).toHaveLength(1)
    expect(fetchState).not.toHaveBeenCalled()
  })

  it('a poll 401 calls onSessionLost and stops', async () => {
    fetchState.mockResolvedValue({
      status: 401,
      body: { error: { code: 'unauthenticated', message: 'x' } },
    })
    connect().drop()
    await vi.advanceTimersByTimeAsync(0)
    expect(onSessionLost).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(sockets).toHaveLength(1)
    expect(fetchState).toHaveBeenCalledTimes(1)
  })
})

describe('skew', () => {
  it('uses hello before the first pong, then the pong sample', async () => {
    client.start()
    latest().open()
    latest().receive({ ...fixture.hello, ts_ms: Date.now() + 700 })
    expect(store.getState().skewOffsetMs).toBe(700)

    await vi.advanceTimersByTimeAsync(15_000) // ping sent at t
    const sent = Date.now()
    await vi.advanceTimersByTimeAsync(100)
    latest().receive({ ...fixture.pong, data: { server_ts_ms: sent + 50 + 1_200 } })
    expect(store.getState().skewOffsetMs).toBe(1_200)
  })
})

describe('frames', () => {
  it('ignores a frame that is not a valid server message', () => {
    const socket = connect()
    const before = store.getState()
    socket.onmessage?.({ data: '{"type":"tick"}' })
    socket.onmessage?.({ data: 'not json' })
    expect(store.getState()).toBe(before)
  })

  it('start is idempotent and stop closes for good', async () => {
    client.start()
    client.start()
    expect(sockets).toHaveLength(1)
    client.stop()
    expect(sockets[0].closedWith).not.toBeNull()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(sockets).toHaveLength(1)
  })
})
