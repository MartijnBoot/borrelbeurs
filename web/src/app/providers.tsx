/**
 * App-wide live wiring, rendered inside the session (R14): while a session
 * exists, one WebSocket client runs for every page -- so a theme change
 * reaches `/bar` and `/settings`, not just the board -- and `ThemeProvider`
 * applies what it delivers.
 *
 * The client is created and stopped in one effect, so StrictMode's
 * mount-unmount-mount leaves exactly one running. Logging out ends the
 * session, which stops it. A lost session (4401, 1008, a poll's 401) goes to
 * login (SD12).
 */
import { useEffect, useRef } from 'react'
import { useGoToLogin, useSession } from '../features/auth'
import { createExchangeClient, exchangeStore, type SocketLike } from '../features/exchange'
import { ThemeProvider } from '../features/theme'

function wsUrl(): string {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${scheme}//${window.location.host}/ws`
}

/** The browser's WebSocket, narrowed to what the client uses. */
function openSocket(url: string): SocketLike {
  const ws = new WebSocket(url)
  const socket: SocketLike = {
    onopen: null,
    onmessage: null,
    onclose: null,
    send: (data) => ws.send(data),
    close: (code) => ws.close(code),
  }
  ws.onopen = () => socket.onopen?.()
  ws.onmessage = (event) => socket.onmessage?.({ data: event.data })
  ws.onclose = (event) => socket.onclose?.({ code: event.code })
  return socket
}

async function fetchState(): Promise<{ status: number; body: unknown }> {
  const response = await fetch('/api/state')
  let body: unknown
  try {
    body = await response.json()
  } catch {
    body = undefined
  }
  return { status: response.status, body }
}

export function Providers() {
  const { session } = useSession()
  const goToLogin = useGoToLogin()
  const ready = session.status === 'ready'
  // The latest one, so `next` is the route the session was lost on; the client
  // itself must not restart on every navigation.
  const goToLoginRef = useRef(goToLogin)
  useEffect(() => {
    goToLoginRef.current = goToLogin
  }, [goToLogin])

  useEffect(() => {
    if (!ready) return
    const client = createExchangeClient({
      url: wsUrl(),
      createSocket: openSocket,
      fetchState,
      onSessionLost: () => goToLoginRef.current(),
      random: Math.random,
      now: Date.now,
      monotonicNow: () => performance.now(),
      store: exchangeStore,
    })
    client.start()
    return () => client.stop()
  }, [ready])

  return <ThemeProvider />
}
