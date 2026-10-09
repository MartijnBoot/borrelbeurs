/**
 * A modal yes/no question (Phase 5 SD9; Phase 6 reuses it).
 *
 * A div overlay with a manual focus trap rather than `<dialog>`, whose
 * `showModal` jsdom supports only in part. Focus starts on confirm, Tab and
 * Shift+Tab cycle between the two buttons, Escape cancels, and on close focus
 * returns to whatever held it before the dialog opened. The keys are heard on
 * the document, so the trap holds after a click on the backdrop has moved
 * focus to `<body>`.
 *
 * With `confirmText` (Phase 7 PD18) the dialog also asks the user to type that
 * text: focus starts on the input, the trap cycles input, confirm, cancel, and
 * confirm stays disabled until the trimmed input equals it exactly.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { Button } from './Button'
import { Field } from './Field'
import styles from './ConfirmDialog.module.css'

export interface ConfirmDialogProps {
  open: boolean
  message: string
  confirmLabel: string
  cancelLabel: string
  /** When set, confirm is enabled only once this text has been typed. */
  confirmText?: string
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
  confirmText,
  onConfirm,
  onCancel,
}: Omit<ConfirmDialogProps, 'open'>) {
  const messageId = useId()
  const inputId = useId()
  const [typed, setTyped] = useState('')
  const dialogRef = useRef<HTMLDivElement>(null)
  // [input?, confirm, cancel], in DOM order: `Button` takes no ref, so they are
  // found. A disabled confirm is skipped, as the browser's Tab skips it.
  const focusables = () =>
    Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>('input, button:not(:disabled)') ?? [],
    )
  const cancel = useRef(onCancel)
  useEffect(() => {
    cancel.current = onCancel
  })

  useEffect(() => {
    const previous = document.activeElement
    focusables()[0]?.focus()

    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        cancel.current()
        return
      }
      if (event.key !== 'Tab') return
      const elements = focusables()
      const first = elements[0]
      const last = elements[elements.length - 1]
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

  const matches = confirmText === undefined || typed.trim() === confirmText

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
        {confirmText !== undefined && (
          <Field id={inputId} label={`Typ de naam '${confirmText}' om te bevestigen`}>
            <input
              id={inputId}
              className={styles.input}
              value={typed}
              autoComplete="off"
              onChange={(event) => setTyped(event.target.value)}
            />
          </Field>
        )}
        <div className={styles.actions}>
          <Button className={styles.confirm} disabled={!matches} onClick={onConfirm}>
            {confirmLabel}
          </Button>
          <Button onClick={onCancel}>{cancelLabel}</Button>
        </div>
      </div>
    </div>
  )
}
