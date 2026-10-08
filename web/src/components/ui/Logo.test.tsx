// @vitest-environment jsdom
// The logo (Phase 6 PD9): one element the shell and the login page share, painted
// from `--img-logo` with the bundled logo as the fallback.
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { Logo } from './Logo'

afterEach(cleanup)

it('is an image named by its alt text, with the caller’s class', () => {
  render(<Logo alt="Bier Beurs" className="extra" />)
  const logo = screen.getByRole('img', { name: 'Bier Beurs' })
  expect(logo.classList.contains('extra')).toBe(true)
})
