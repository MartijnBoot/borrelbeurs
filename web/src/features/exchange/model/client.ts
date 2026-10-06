/**
 * The one WebSocket client: `connecting -> open -> offline`, and back
 * (frontend-architecture.md, "One WebSocket client owns reconnect").
 *
 * Everything with a side effect is injected -- the socket factory,
 * `random()`, `now()`, `monotonicNow()`, `fetchState()`, the store -- and
 * timers are the
 * globals, so the tests drive it on fake timers with a fake socket.
 *
 * - **Open:** send `hello {boot_id, last_seq}` (SD16), ping every 15 s (SD14),
 *   arm a 45 s deadline that any inbound frame resets, stop polling, reset
 *   the backoff. After a polled state landed the `boot_id` is empty: the held
 *   seq is older than what the board shows, so a replay from it would tick the
 *   board backwards, and the server sends a snapshot instead.
 * - **Deadline:** force-close and handle it as a lost connection (AC13).
 * - **Close:** 4401 or 1008 is a lost session (SD12). Anything else goes
 *   `offline`: poll `GET /api/state` at once and every 5 s (SD17), and
 *   schedule a reconnect per SD15. A browser reports a pre-accept handshake
 *   rejection as 1006, so that path reaches login through the poll's 401
 *   (PD10).
 * - **Frames:** validated with `ServerMessage`, then `applyMessage`. A gap
 *   (`awaitingResync`) sends one `resync_request` until a snapshot ends it.
 */
import type { StoreApi } from 'zustand/vanilla'
import { applyMessage, applyNoLiveRun, applyPolledState, type ExchangeState } from './applyMessage'
import { reconnectDelayMs } from './backoff'
import { type ClientMessage, ServerMessage, SnapshotData } from './schemas'
import { SkewEstimator } from './skew'

export const PING_MS = 15_000
export const DEADLINE_MS = 45_000
export const POLL_MS = 5_000
const SESSION_LOST_CODES: ReadonlySet<number> = new Set([4401, 1008])

/** The part of the browser's `WebSocket` the client uses. */
export interface SocketLike {
  onopen: (() => void) | null
  onmessage: ((event: { data: unknown }) => void) | null
  onclose: ((event: { code: number }) => void) | null
  send(data: string): void
  close(code?: number): void
}

export interface ExchangeClientDeps {
  url: string
  createSocket(url: string): SocketLike
  /** `GET /api/state`: the status and the parsed JSON body, if any. Rejects on a network error. */
  fetchState(): Promise<{ status: number; body: unknown }>
  onSessionLost(): void
  random(): number
  /** The wall clock, for skew (SD18). */
  now(): number
  /** The monotonic clock (`performance.now`): each quote's `receivedAt` (Phase 5 PD1). */
  monotonicNow(): number
  store: StoreApi<ExchangeState>
}

export interface ExchangeClient {
  start(): void
  stop(): void
}

type Timer = ReturnType<typeof setTimeout>

export function createExchangeClient(deps: ExchangeClientDeps): ExchangeClient {
  const { store } = deps
  let started = false
  let socket: SocketLike | null = null
  let attempt = 0
  let pingTimer: Timer | null = null
  let deadline: Timer | null = null
  let reconnectTimer: Timer | null = null
  let pollTimer: Timer | null = null
  let polling = 0 // a generation: a poll answered after polling stopped is dropped
  let resyncSent = false
  let polledSinceOpen = false // the held seq is older than the polled state shown
  let pingsInFlight: number[] = []
  const skew = new SkewEstimator()

  const update = (next: (state: ExchangeState) => ExchangeState) =>
    store.setState((state) => next(state), true)

  function send(message: ClientMessage): void {
    socket?.send(JSON.stringify(message))
  }

  function connect(): void {
    reconnectTimer = null
    const ws = deps.createSocket(deps.url)
    socket = ws
    ws.onopen = () => onOpen()
    ws.onmessage = (event) => onFrame(event.data)
    ws.onclose = (event) => {
      if (socket === ws) onClosed(event.code)
    }
  }

  function onOpen(): void {
    attempt = 0
    stopPolling()
    store.setState({ status: 'open' })
    const { bootId, seq } = store.getState()
    send({ type: 'hello', boot_id: polledSinceOpen ? '' : (bootId ?? ''), last_seq: seq ?? 0 })
    polledSinceOpen = false
    pingTimer = setInterval(() => {
      pingsInFlight.push(deps.now())
      send({ type: 'ping' })
    }, PING_MS)
    armDeadline()
  }

  function armDeadline(): void {
    if (deadline !== null) clearTimeout(deadline)
    deadline = setTimeout(() => {
      const ws = socket
      detach()
      ws?.close()
      onClosed(1006)
    }, DEADLINE_MS)
  }

  function onFrame(raw: unknown): void {
    armDeadline()
    const received = deps.now()
    const receivedAt = deps.monotonicNow()
    let json: unknown
    try {
      json = JSON.parse(String(raw))
    } catch {
      return
    }
    const parsed = ServerMessage.safeParse(json)
    if (!parsed.success) return
    const message = parsed.data

    if (message.type === 'pong') {
      const sent = pingsInFlight.shift()
      if (sent !== undefined) skew.sample(sent, received, message.data.server_ts_ms)
    } else if (message.type === 'hello') {
      skew.fallback(message.ts_ms, received)
    }
    const offset = skew.offsetMs()
    update((state) => {
      const next = applyMessage(state, message, receivedAt)
      return offset === null || offset === next.skewOffsetMs
        ? next
        : { ...next, skewOffsetMs: offset }
    })

    const { awaitingResync } = store.getState()
    if (awaitingResync && !resyncSent) {
      resyncSent = true
      send({ type: 'resync_request' })
    } else if (!awaitingResync) {
      resyncSent = false
    }
  }

  function onClosed(code: number): void {
    detach()
    if (SESSION_LOST_CODES.has(code)) {
      sessionLost()
      return
    }
    store.setState({ status: 'offline' })
    startPolling()
    const delay = reconnectDelayMs(attempt, deps.random)
    attempt += 1
    reconnectTimer = setTimeout(connect, Math.round(delay))
  }

  /** Drop the current socket and its timers, without scheduling anything. */
  function detach(): void {
    if (socket !== null) {
      socket.onopen = socket.onmessage = socket.onclose = null
      socket = null
    }
    if (pingTimer !== null) clearInterval(pingTimer)
    if (deadline !== null) clearTimeout(deadline)
    pingTimer = deadline = null
    pingsInFlight = []
    resyncSent = false
  }

  function startPolling(): void {
    if (pollTimer !== null) return
    const generation = ++polling
    void poll(generation)
    pollTimer = setInterval(() => void poll(generation), POLL_MS)
  }

  function stopPolling(): void {
    if (pollTimer !== null) clearInterval(pollTimer)
    pollTimer = null
    polling += 1
  }

  async function poll(generation: number): Promise<void> {
    let result: { status: number; body: unknown }
    try {
      result = await deps.fetchState()
    } catch {
      return // offline: the next poll, or the reconnect, tries again
    }
    if (generation !== polling) return
    if (result.status === 401) {
      sessionLost()
    } else if (result.status === 409) {
      update(applyNoLiveRun)
    } else if (result.status === 200) {
      const data = SnapshotData.safeParse(result.body)
      if (data.success) {
        const receivedAt = deps.monotonicNow()
        update((state) => applyPolledState(state, data.data, receivedAt))
        polledSinceOpen = true
      }
    }
  }

  function sessionLost(): void {
    stop()
    deps.onSessionLost()
  }

  function stop(): void {
    started = false
    const ws = socket
    detach()
    ws?.close()
    stopPolling()
    if (reconnectTimer !== null) clearTimeout(reconnectTimer)
    reconnectTimer = null
  }

  return {
    start() {
      if (started) return
      started = true
      connect()
    },
    stop,
  }
}
