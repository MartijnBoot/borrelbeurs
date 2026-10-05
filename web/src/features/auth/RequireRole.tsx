import type { ReactNode } from 'react'
import { useSession } from './useSession'

/**
 * SD13: `children` when the session's `allowed_routes` holds `route`,
 * `fallback` ("Geen toegang") otherwise -- shown in place, never a redirect.
 */
export function RequireRole({
  route,
  fallback,
  children,
}: {
  route: string
  fallback: ReactNode
  children: ReactNode
}) {
  const { session } = useSession()
  if (session.status !== 'ready') return null
  return session.me.allowed_routes.includes(route) ? children : fallback
}
