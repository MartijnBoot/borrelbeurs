// The auth feature's public surface: the session, SD12's way to login, the
// role gate and the login page.
export { LoginPage } from './LoginPage'
export { RequireRole } from './RequireRole'
export { SessionProvider, useGoToLogin, useSession, type SessionState } from './useSession'
