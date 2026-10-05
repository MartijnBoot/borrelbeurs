/**
 * The session: `GET /api/auth/me`, held once for the app (SD13). Its
 * `allowed_routes` is the only role information the client has -- there is
 * no role -> route table here, and `NavMenu` and `RequireRole` both read this.
 *
 * `useGoToLogin()` is SD12's one way out: `/login?next=<current route>`. The
 * HTTP wrapper's 401 hook and the WebSocket client's `onSessionLost` both
 * call it. It also ends the held session, so the next login is a new one and
 * everything keyed on it -- the live client above all -- starts again.
 */
import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useLocation, useNavigate } from 'react-router'
import { z } from 'zod'
import type { components } from '../../api/generated/schema'
import { request } from '../../lib/http'

type MeData = components['schemas']['Me']

export const Me: z.ZodType<MeData> = z.object({
  role: z.enum(['display', 'bar', 'admin']),
  label: z.string(),
  allowed_routes: z.array(z.string()),
})

export type SessionState =
  { status: 'loading' } | { status: 'anonymous' } | { status: 'ready'; me: MeData }

interface SessionApi {
  session: SessionState
  signedIn(me: MeData): void
  /** The server no longer knows this session (SD12); nothing to log out. */
  lost(): void
  logout(): Promise<void>
}

const SessionContext = createContext<SessionApi | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionState>({ status: 'loading' })
  const { pathname } = useLocation()
  const onLoginPage = pathname === '/login'

  useEffect(() => {
    if (onLoginPage || session.status !== 'loading') return
    let cancelled = false
    request('GET', '/api/auth/me', { schema: Me }).then(
      (me) => !cancelled && setSession({ status: 'ready', me }),
      () => !cancelled && setSession({ status: 'anonymous' }),
    )
    return () => {
      cancelled = true
    }
  }, [onLoginPage, session.status])

  const signedIn = useCallback((me: MeData) => setSession({ status: 'ready', me }), [])
  const lost = useCallback(
    () => setSession((held) => (held.status === 'anonymous' ? held : { status: 'anonymous' })),
    [],
  )
  const logout = useCallback(async () => {
    try {
      await request('POST', '/api/auth/logout', { schema: z.unknown() })
    } finally {
      setSession({ status: 'anonymous' })
    }
  }, [])

  const api = useMemo(
    () => ({ session, signedIn, lost, logout }),
    [session, signedIn, lost, logout],
  )
  return createElement(SessionContext.Provider, { value: api }, children)
}

export function useSession(): SessionApi {
  const api = useContext(SessionContext)
  if (api === null) throw new Error('useSession needs a SessionProvider')
  return api
}

/** SD12: to `/login?next=<the current route>`. */
export function useGoToLogin(): () => void {
  const navigate = useNavigate()
  const location = useLocation()
  const { lost } = useSession()
  return useCallback(() => {
    if (location.pathname === '/login') return
    const next = encodeURIComponent(location.pathname + location.search)
    navigate(`/login?next=${next}`, { replace: true })
    lost()
  }, [navigate, lost, location.pathname, location.search])
}
