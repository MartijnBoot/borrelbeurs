// @vitest-environment jsdom
// ConfirmDialog (Phase 5 T9, SD9): a modal with a focus trap; Escape cancels.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ConfirmDialog } from './ConfirmDialog'

afterEach(cleanup)

function renderDialog(open = true) {
  const onConfirm = vi.fn()
  const onCancel = vi.fn()
  const view = render(
    <ConfirmDialog
      open={open}
      message="Bier: prijs is nu € 2,70 — bevestigen?"
      confirmLabel="Bevestigen"
      cancelLabel="Annuleren"
      onConfirm={onConfirm}
      onCancel={onCancel}
    />,
  )
  return { onConfirm, onCancel, ...view }
}

const confirmButton = () => screen.getByRole('button', { name: 'Bevestigen' })
const cancelButton = () => screen.getByRole('button', { name: 'Annuleren' })

describe('ConfirmDialog', () => {
  it('is a labelled modal dialog', () => {
    renderDialog()
    const dialog = screen.getByRole('dialog', { name: 'Bier: prijs is nu € 2,70 — bevestigen?' })
    expect(dialog.getAttribute('aria-modal')).toBe('true')
  })

  it('puts focus on confirm first', () => {
    renderDialog()
    expect(document.activeElement).toBe(confirmButton())
  })

  it('Tab from the last button wraps to the first, and Shift+Tab wraps back', () => {
    renderDialog()
    // Confirm is first in focus order (initial focus); cancel is last.
    cancelButton().focus()
    fireEvent.keyDown(cancelButton(), { key: 'Tab' })
    expect(document.activeElement).toBe(confirmButton())
    fireEvent.keyDown(confirmButton(), { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(cancelButton())
  })

  it('Tab between the buttons is left to the browser', () => {
    renderDialog()
    const event = fireEvent.keyDown(confirmButton(), { key: 'Tab' })
    expect(event).toBe(true) // not prevented
  })

  it('Escape calls onCancel once', () => {
    const { onCancel, onConfirm } = renderDialog()
    fireEvent.keyDown(confirmButton(), { key: 'Escape' })
    expect(onCancel).toHaveBeenCalledOnce()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('Escape still cancels after focus has left the dialog (a backdrop click)', () => {
    const { onCancel } = renderDialog()
    ;(document.activeElement as HTMLElement).blur()
    expect(document.activeElement).toBe(document.body)
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('Tab after focus has left the dialog brings it back in; Shift+Tab to the last button', () => {
    renderDialog()
    ;(document.activeElement as HTMLElement).blur()
    fireEvent.keyDown(document.body, { key: 'Tab' })
    expect(document.activeElement).toBe(confirmButton())
    ;(document.activeElement as HTMLElement).blur()
    fireEvent.keyDown(document.body, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(cancelButton())
  })

  it('stops listening to the document when it closes', () => {
    const { onCancel, rerender } = renderDialog()
    rerender(
      <ConfirmDialog
        open={false}
        message="x"
        confirmLabel="Bevestigen"
        cancelLabel="Annuleren"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    )
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('each button calls its own handler', () => {
    const { onCancel, onConfirm } = renderDialog()
    fireEvent.click(confirmButton())
    expect(onConfirm).toHaveBeenCalledOnce()
    fireEvent.click(cancelButton())
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('renders nothing when closed', () => {
    renderDialog(false)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('has no text input without confirmText', () => {
    renderDialog()
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(confirmButton()).toHaveProperty('disabled', false)
  })

  it('returns focus to the previously focused element on close', () => {
    function Harness() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button onClick={() => setOpen(true)}>Open</button>
          <ConfirmDialog
            open={open}
            message="Zeker?"
            confirmLabel="Ja"
            cancelLabel="Nee"
            onConfirm={() => setOpen(false)}
            onCancel={() => setOpen(false)}
          />
        </>
      )
    }
    render(<Harness />)
    const opener = screen.getByRole('button', { name: 'Open' })
    opener.focus()
    fireEvent.click(opener)
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Ja' }))
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(opener)
  })
})

// Phase 7 T16 (AC32, PD18): a destructive action asks for the run's name.
describe('ConfirmDialog with confirmText', () => {
  function renderTyped() {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(
      <ConfirmDialog
        open
        message="Borrel afsluiten?"
        confirmLabel="Afsluiten"
        cancelLabel="Annuleren"
        confirmText="Vrijdag"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )
    return { onConfirm, onCancel }
  }

  const input = () =>
    screen.getByRole('textbox', { name: "Typ de naam 'Vrijdag' om te bevestigen" })
  const confirm = () => screen.getByRole('button', { name: 'Afsluiten' })
  const cancel = () => screen.getByRole('button', { name: 'Annuleren' })
  const type = (value: string) => fireEvent.change(input(), { target: { value } })

  it('labels the input with the exact text', () => {
    renderTyped()
    expect(screen.getByText("Typ de naam 'Vrijdag' om te bevestigen")).toBeTruthy()
    expect(input()).toBeTruthy()
  })

  it('keeps confirm disabled until the typed name matches, case-sensitively', () => {
    const { onConfirm } = renderTyped()
    expect(confirm()).toHaveProperty('disabled', true)
    type('vrijdag')
    expect(confirm()).toHaveProperty('disabled', true)
    fireEvent.click(confirm())
    expect(onConfirm).not.toHaveBeenCalled()
    type(' Vrijdag ')
    expect(confirm()).toHaveProperty('disabled', false)
    fireEvent.click(confirm())
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('puts focus on the input first', () => {
    renderTyped()
    expect(document.activeElement).toBe(input())
  })

  it('Tab cycles input → confirm → cancel and wraps; Shift+Tab wraps back', () => {
    renderTyped()
    type('Vrijdag')
    // Input → confirm → cancel is left to the browser (DOM order).
    expect(fireEvent.keyDown(input(), { key: 'Tab' })).toBe(true)
    expect(fireEvent.keyDown(confirm(), { key: 'Tab' })).toBe(true)
    cancel().focus()
    fireEvent.keyDown(cancel(), { key: 'Tab' })
    expect(document.activeElement).toBe(input())
    fireEvent.keyDown(input(), { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(cancel())
  })

  it('Escape cancels from the input', () => {
    const { onCancel, onConfirm } = renderTyped()
    fireEvent.keyDown(input(), { key: 'Escape' })
    expect(onCancel).toHaveBeenCalledOnce()
    expect(onConfirm).not.toHaveBeenCalled()
  })
})
