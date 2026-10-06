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
