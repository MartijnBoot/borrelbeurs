// @vitest-environment jsdom
// SD19's banner follows the connection status (AC16, banner half).
import { act, cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { exchangeStore } from '../features/exchange'
import { AppShell } from './AppShell'

const BANNER = 'Verbinding verbroken — opnieuw verbinden…'

beforeEach(() => {
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  render(
    <MemoryRouter>
      <AppShell routes={['/koers']} onLogout={() => {}}>
        page
      </AppShell>
    </MemoryRouter>,
  )
})

afterEach(cleanup)

it('shows the banner only while offline', () => {
  expect(screen.queryByText(BANNER)).toBeNull()
  act(() => exchangeStore.setState({ status: 'offline' }))
  expect(screen.getByRole('status').textContent).toBe(BANNER)
  act(() => exchangeStore.setState({ status: 'open' }))
  expect(screen.queryByText(BANNER)).toBeNull()
})
