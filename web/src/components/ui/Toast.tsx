/**
 * A short notice (Phase 6 SD27; AC2's "Niets te wijzigen"): a polite live region
 * that calls `onDone` after `durationMs`, so its owner clears the message. Never
 * a native `alert` (AC39).
 */
import { useEffect } from 'react'
import styles from './Toast.module.css'

export const TOAST_MS = 3_000

export interface ToastProps {
  message: string | null
  onDone: () => void
  durationMs?: number
}

export function Toast({ message, onDone, durationMs = TOAST_MS }: ToastProps) {
  useEffect(() => {
    if (message === null) return
    const timer = setTimeout(onDone, durationMs)
    return () => clearTimeout(timer)
  }, [message, onDone, durationMs])
  if (message === null) return null
  return (
    <div role="status" aria-live="polite" className={styles.toast}>
      {message}
    </div>
  )
}
