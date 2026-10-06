/**
 * A modal yes/no question (Phase 5 SD9; Phase 6 reuses it).
 *
 * A div overlay with a manual focus trap rather than `<dialog>`, whose
 * `showModal` jsdom supports only in part. Focus starts on confirm, Tab and
 * Shift+Tab cycle between the two buttons, Escape cancels, and on close focus
 * returns to whatever held it before the dialog opened. The keys are heard on
 * the document, so the trap holds after a click on the backdrop has moved
 * focus to `<body>`.
 */
import { useEffect, useId, useRef } from 'react'
import { Button } from './Button'
import styles from './ConfirmDialog.module.css'

export interface ConfirmDialogProps {
  open: boolean
  message: string
  confirmLabel: string
  cancelLabel: string
  onConfirm(): void
  onCancel(): void
}

export function ConfirmDialog({ open, ...props }: ConfirmDialogProps) {
  return open ? <OpenDialog {...props} /> : null
}

function OpenDialog({
  message,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
}: Omit<ConfirmDialogProps, 'open'>) {
  const messageId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  // [confirm, cancel], in DOM order: `Button` takes no ref, so they are found.
  const buttons = () => dialogRef.current?.querySelectorAll('button') ?? []
  const cancel = useRef(onCancel)
  useEffect(() => {
    cancel.current = onCancel
  })

  useEffect(() => {
    const previous = document.activeElement
    buttons()[0]?.focus()

    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        cancel.current()
        return
      }
      if (event.key !== 'Tab') return
      const [first, last] = buttons()
      const active = document.activeElement
      if (!dialogRef.current?.contains(active)) {
        // Focus has left the dialog (a backdrop click): bring it back in.
        event.preventDefault()
        ;(event.shiftKey ? last : first)?.focus()
      } else if (event.shiftKey && active === first) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first?.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      if (previous instanceof HTMLElement) previous.focus()
    }
  }, [])

  return (
    <div className={styles.backdrop}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={messageId}
        className={styles.dialog}
      >
        <p id={messageId} className={styles.message}>
          {message}
        </p>
        <div className={styles.actions}>
          <Button className={styles.confirm} onClick={onConfirm}>
            {confirmLabel}
          </Button>
          <Button onClick={onCancel}>{cancelLabel}</Button>
        </div>
      </div>
    </div>
  )
}
