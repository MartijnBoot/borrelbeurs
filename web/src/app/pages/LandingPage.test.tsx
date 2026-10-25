// @vitest-environment jsdom
// The landing choice (B-05 SD20, AC1).
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it } from 'vitest'
import { LandingPage } from './LandingPage'

afterEach(cleanup)

describe('LandingPage (AC1)', () => {
  it('offers "Speler" to /speler and "Crew" to /login, and nothing else', () => {
    render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>,
    )
    const links = screen.getAllByRole('link')
    expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['Speler', '/speler'],
      ['Crew', '/login'],
    ])
    expect(screen.getByRole('img', { name: 'Beurs Borrel' })).toBeTruthy()
  })
})
