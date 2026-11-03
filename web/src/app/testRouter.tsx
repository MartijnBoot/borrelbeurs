/**
 * Test helper (B-12 PD1): renders `ui` the way `main.tsx` mounts the app, as
 * the one splat route of a data router -- here a memory one -- so `useBlocker`
 * works, which it does not under a plain `MemoryRouter`. Returns the router,
 * so a test can `router.navigate(-1)` (the back button) or read
 * `router.state.location`.
 */
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'

export function renderInDataRouter(ui: ReactNode, initialEntries: string[] = ['/']) {
  const router = createMemoryRouter([{ path: '*', element: ui }], { initialEntries })
  render(<RouterProvider router={router} />)
  return router
}
