/**
 * The route table. `/login` stands alone; every other route renders inside
 * the `AppShell` behind the session, gated by `RequireRole` on the session's
 * `allowed_routes` (SD13). The list below is which pages the client can
 * render -- not who may see them, which only the server decides.
 *
 * Phase 4 builds `/koers` (T20) and the theme section of `/settings` (T18);
 * every other route is SD4's placeholder until Phases 5–6. An unknown path is
 * "Geen toegang" inside the shell.
 */
import { useEffect, type ReactNode } from 'react'
import { Outlet, Route, Routes, useNavigate } from 'react-router'
import { LoginPage, RequireRole, SessionProvider, useGoToLogin, useSession } from '../features/auth'
import { setOnUnauthenticated } from '../lib/http'
import { AppShell } from './AppShell'
import { NoAccess } from './pages/NoAccess'
import { Placeholder } from './pages/Placeholder'
import { SettingsPage } from './pages/SettingsPage'
import { Providers } from './providers'

const PAGES: readonly (readonly [string, ReactNode])[] = [
  ['/', <Placeholder />],
  ['/koers', <Placeholder />],
  ['/bar', <Placeholder />],
  ['/manipulation', <Placeholder />],
  ['/settings', <SettingsPage />],
]

function ShellLayout() {
  const { session, logout } = useSession()
  const goToLogin = useGoToLogin()
  const navigate = useNavigate()

  useEffect(() => {
    if (session.status === 'anonymous') goToLogin()
  }, [session.status, goToLogin])

  if (session.status !== 'ready') return null
  return (
    <AppShell
      routes={session.me.allowed_routes}
      onLogout={() => {
        navigate('/login', { replace: true })
        void logout()
      }}
    >
      <Outlet />
    </AppShell>
  )
}

/** SD12: any request's 401 goes to login. */
function UnauthenticatedHook() {
  const goToLogin = useGoToLogin()
  useEffect(() => {
    setOnUnauthenticated(goToLogin)
    return () => setOnUnauthenticated(null)
  }, [goToLogin])
  return null
}

export function AppRoutes() {
  return (
    <SessionProvider>
      <UnauthenticatedHook />
      <Providers />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ShellLayout />}>
          {PAGES.map(([path, page]) => (
            <Route
              key={path}
              path={path}
              element={
                <RequireRole route={path} fallback={<NoAccess />}>
                  {page}
                </RequireRole>
              }
            />
          ))}
          <Route path="*" element={<NoAccess />} />
        </Route>
      </Routes>
    </SessionProvider>
  )
}
