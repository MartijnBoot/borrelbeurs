// @vitest-environment jsdom
// The leave guard's mechanism (B-12 T2: SD9, PD3, PD6; AC23, AC24), on a test
// page that reports its typed text as unsaved. The screens use it in T5.
import { act, cleanup, fireEvent, screen } from '@testing-library/react'
import { useState } from 'react'
import { Link, Route, Routes, useLocation } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { UnsavedEditsProvider, useReportUnsaved } from '../lib/unsavedEdits'
import { useConfirmLeave } from './confirmLeave'
import { LeaveGuard } from './LeaveGuard'
import { renderInDataRouter } from './testRouter'

afterEach(cleanup)

const QUESTION = 'Niet-opgeslagen wijzigingen weggooien?'

function TestPage({ onLogout }: { onLogout: () => void }) {
  const [text, setText] = useState('')
  useReportUnsaved(text !== '')
  const confirmLeave = useConfirmLeave()
  return (
    <>
      <label>
        Drukdrempel
        <input value={text} onChange={(event) => setText(event.target.value)} />
      </label>
      <Link to="/settings">← Instellingen</Link>
      <button type="button" onClick={() => confirmLeave(onLogout)}>
        Uitloggen
      </button>
    </>
  )
}

function Where() {
  const location = useLocation()
  return <output data-testid="where">{location.pathname + location.hash}</output>
}

function open(path: string, onLogout = vi.fn()) {
  const router = renderInDataRouter(
    <UnsavedEditsProvider>
      <LeaveGuard>
        <Routes>
          <Route path="/settings" element={<p>Landing</p>} />
          <Route path="/login" element={<p>Login</p>} />
          <Route path="*" element={<TestPage onLogout={onLogout} />} />
        </Routes>
        <Where />
      </LeaveGuard>
    </UnsavedEditsProvider>,
    ['/settings', path],
  )
  return { router, onLogout }
}

const where = () => screen.getByTestId('where').textContent
const field = () => screen.getByLabelText<HTMLInputElement>('Drukdrempel')
const type = (value: string) => fireEvent.change(field(), { target: { value } })
const dialog = () => screen.queryByRole('dialog', { name: QUESTION })

describe('LeaveGuard (B-12 SD9)', () => {
  it('asks before a link leaves a dirty screen; "Blijven" keeps the screen and its value', () => {
    open('/settings/beheer')
    type('7')
    fireEvent.click(screen.getByRole('link', { name: '← Instellingen' }))

    expect(dialog()).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Blijven' }))

    expect(dialog()).toBeNull()
    expect(where()).toBe('/settings/beheer')
    expect(field().value).toBe('7')
  })

  it('"Weggooien" leaves', async () => {
    open('/settings/beheer')
    type('7')
    fireEvent.click(screen.getByRole('link', { name: '← Instellingen' }))
    fireEvent.click(screen.getByRole('button', { name: 'Weggooien' }))
    await act(async () => {})

    expect(where()).toBe('/settings')
    expect(screen.getByText('Landing')).toBeTruthy()
  })

  it('Escape is "Blijven"', () => {
    open('/settings/beheer')
    type('7')
    fireEvent.click(screen.getByRole('link', { name: '← Instellingen' }))
    fireEvent.keyDown(document, { key: 'Escape' })

    expect(dialog()).toBeNull()
    expect(where()).toBe('/settings/beheer')
  })

  it('asks on the back button too', async () => {
    const { router } = open('/settings/wallets')
    type('7')
    await act(() => router.navigate(-1))

    expect(dialog()).toBeTruthy()
    expect(where()).toBe('/settings/wallets')
  })

  it('lets a #section link pass', async () => {
    const { router } = open('/settings/spel')
    type('7')
    await act(() => router.navigate('/settings/spel#borrel'))

    expect(dialog()).toBeNull()
    expect(where()).toBe('/settings/spel#borrel')
  })

  it('lets a lost session go to /login', async () => {
    const { router } = open('/settings/beheer')
    type('7')
    await act(() => router.navigate('/login?next=%2Fsettings%2Fbeheer', { replace: true }))

    expect(dialog()).toBeNull()
    expect(where()).toBe('/login')
  })

  it('a clean screen leaves without a dialog', async () => {
    open('/settings/beheer')
    fireEvent.click(screen.getByRole('link', { name: '← Instellingen' }))
    await act(async () => {})

    expect(dialog()).toBeNull()
    expect(where()).toBe('/settings')
  })

  it('a dirty screen saved (or typed back) leaves without a dialog', async () => {
    open('/settings/beheer')
    type('7')
    type('')
    fireEvent.click(screen.getByRole('link', { name: '← Instellingen' }))
    await act(async () => {})

    expect(dialog()).toBeNull()
    expect(where()).toBe('/settings')
  })

  it('guards only the three screens: a dirty /manipulation leaves (PD6)', async () => {
    open('/manipulation')
    type('7')
    fireEvent.click(screen.getByRole('link', { name: '← Instellingen' }))
    await act(async () => {})

    expect(dialog()).toBeNull()
    expect(where()).toBe('/settings')
  })

  it('Uitloggen asks while dirty, and logs out on "Weggooien"', () => {
    const { onLogout } = open('/settings/beheer')
    type('7')
    fireEvent.click(screen.getByRole('button', { name: 'Uitloggen' }))

    expect(dialog()).toBeTruthy()
    expect(onLogout).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Blijven' }))
    expect(onLogout).not.toHaveBeenCalled()
    expect(field().value).toBe('7')

    fireEvent.click(screen.getByRole('button', { name: 'Uitloggen' }))
    fireEvent.click(screen.getByRole('button', { name: 'Weggooien' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it('Uitloggen logs out at once while clean', () => {
    const { onLogout } = open('/settings/beheer')
    fireEvent.click(screen.getByRole('button', { name: 'Uitloggen' }))

    expect(dialog()).toBeNull()
    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['dirty on a screen', '/settings/beheer', '7', true],
    ['clean on a screen', '/settings/beheer', '', false],
    ['dirty off the screens', '/manipulation', '7', false],
  ])('requests the browser prompt on unload only while %s', (_case, path, text, prompted) => {
    open(path)
    type(text)
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)

    expect(event.defaultPrevented).toBe(prompted)
  })
})
