/**
 * The (i) beside a market control and its explanation popup (B-01 SD1).
 *
 * Opens on a click or tap only -- no hover --, and closes on a second click, a
 * click outside or Escape. At most one is open at a time. Focus is never moved
 * into the popup (PD6), so after a keyboard close it is still on the (i). The
 * popup is portalled into `body` and placed by `placePopup`, so no ancestor's
 * `overflow` clips it and a narrow screen never scrolls sideways (AC6).
 */
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import styles from './InfoButton.module.css'
import { placePopup } from './placePopup'

export interface Explanation {
  name: string
  paragraphs: readonly string[]
}

/** Closes the open popup, if any (PD8): opening another one calls it first. */
let closeOpen: (() => void) | null = null

export function InfoButton({ explanation }: { explanation: Explanation }) {
  const [open, setOpen] = useState(false)
  const button = useRef<HTMLButtonElement>(null)
  const popup = useRef<HTMLDivElement>(null)
  const id = useId()
  const close = useCallback(() => setOpen(false), [])

  useEffect(() => {
    if (!open) return
    closeOpen = close
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onClick = (event: MouseEvent) => {
      const target = event.target as Node
      if (!button.current?.contains(target) && !popup.current?.contains(target)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('click', onClick)
    return () => {
      if (closeOpen === close) closeOpen = null
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('click', onClick)
    }
  }, [open, close])

  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const node = popup.current
      if (!button.current || !node) return
      const { left, top } = placePopup(
        button.current.getBoundingClientRect(),
        { width: node.offsetWidth, height: node.offsetHeight },
        { width: window.innerWidth, height: window.innerHeight },
      )
      node.style.left = `${left}px`
      node.style.top = `${top}px`
    }
    place()
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [open])

  return (
    <>
      <button
        ref={button}
        type="button"
        className={styles.button}
        aria-label={`Uitleg: ${explanation.name}`}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => {
          if (!open && closeOpen !== null) closeOpen()
          setOpen(!open)
        }}
      >
        <span aria-hidden="true">i</span>
      </button>
      {open &&
        createPortal(
          <div
            ref={popup}
            id={id}
            role="note"
            aria-labelledby={`${id}-title`}
            className={styles.popup}
          >
            <p id={`${id}-title`} className={styles.title}>
              {explanation.name}
            </p>
            {explanation.paragraphs.map((paragraph) => (
              <p key={paragraph} className={styles.paragraph}>
                {paragraph}
              </p>
            ))}
          </div>,
          document.body,
        )}
    </>
  )
}
