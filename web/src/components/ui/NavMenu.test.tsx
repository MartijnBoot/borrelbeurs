// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NavMenu } from './NavMenu'

afterEach(cleanup)

// Phase 3 SD2's allowed_routes, as GET /api/auth/me returns them.
const ALLOWED: Record<string, string[]> = {
  display: ['/koers'],
  bar: ['/bar', '/manipulation'],
  admin: ['/', '/koers', '/bar', '/manipulation', '/settings'],
}

function renderMenu(routes: string[], onLogout = vi.fn()) {
  render(
    <MemoryRouter>
      <NavMenu routes={routes} onLogout={onLogout} />
    </MemoryRouter>,
  )
  fireEvent.click(screen.getByRole('button', { name: /Menu/ }))
  return within(screen.getByRole('menu'))
}

const hrefs = (menu: ReturnType<typeof within>) =>
  menu
    .queryAllByRole('menuitem', { name: (name: string) => name !== 'Uitloggen' })
    .map((a: HTMLElement) => a.getAttribute('href'))

describe('NavMenu (AC22, SD13)', () => {
  it.each(Object.entries(ALLOWED))('for %s lists exactly its allowed routes', (_role, routes) => {
    expect(hrefs(renderMenu(routes))).toEqual(routes)
  })

  it('labels routes with v1 labels', () => {
    const menu = renderMenu(ALLOWED.admin)
    for (const label of ['Home', 'Live koersbord', 'Bar', 'Spel mechanica', 'Instellingen']) {
      expect(menu.getByRole('menuitem', { name: label })).toBeTruthy()
    }
  })

  it('renders a route without a label as its path, never dropping it', () => {
    const menu = renderMenu(['/koers', '/nieuw'])
    expect(menu.getByRole('menuitem', { name: '/nieuw' }).getAttribute('href')).toBe('/nieuw')
  })

  it('calls the logout handler', () => {
    const onLogout = vi.fn()
    const menu = renderMenu(ALLOWED.display, onLogout)
    fireEvent.click(menu.getByRole('menuitem', { name: 'Uitloggen' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it('is closed until the button is pressed, and Escape closes it', () => {
    render(
      <MemoryRouter>
        <NavMenu routes={ALLOWED.bar} onLogout={vi.fn()} />
      </MemoryRouter>,
    )
    const button = screen.getByRole('button', { name: /Menu/ })
    expect(screen.queryByRole('menu')).toBeNull()
    expect(button.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(button)
    expect(button.getAttribute('aria-expanded')).toBe('true')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).toBeNull()
  })
})
