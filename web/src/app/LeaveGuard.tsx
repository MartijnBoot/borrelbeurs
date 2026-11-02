/**
 * The leave guard (B-12 SD9, PD3, PD6): leaving a settings screen while one
 * of its forms holds unsaved edits asks "Niet-opgeslagen wijzigingen
 * weggooien?" first. "Blijven" (and Escape) keeps the screen as it is,
 * "Weggooien" goes on.
 *
 * It blocks through the data router's `useBlocker` (PD1), so a link, a
 * `navigate()` and the back button all ask. Only on the three screens, and
 * only for a change of path: the section links (`#…`) pass, and so does a
 * navigation to `/login`, which a lost session makes after the fact -- asking
 * then would trap the user on a dead session. A reload or a closed tab gets
 * the browser's own prompt instead. `useConfirmLeave()(then)` (`confirmLeave.ts`)
 * asks the same question before an action that is not a navigation the router
 * sees (Uitloggen), and runs `then` at once when nothing is unsaved.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useBlocker, useLocation } from 'react-router'
import { ConfirmDialog } from '../components/ui/ConfirmDialog'
import { useHasUnsaved } from '../lib/unsavedEdits'
import { ConfirmLeaveContext, type ConfirmLeave } from './confirmLeave'

const GUARDED: ReadonlySet<string> = new Set([
  '/settings/spel',
  '/settings/wallets',
  '/settings/beheer',
])

export function LeaveGuard({ children }: { children: ReactNode }) {
  const hasUnsaved = useHasUnsaved()
  const { pathname } = useLocation()
  const guarding = hasUnsaved && GUARDED.has(pathname)
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      hasUnsaved &&
      GUARDED.has(currentLocation.pathname) &&
      nextLocation.pathname !== currentLocation.pathname &&
      nextLocation.pathname !== '/login',
  )
  const [pending, setPending] = useState<(() => void) | null>(null)

  useEffect(() => {
    if (!guarding) return
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [guarding])

  const confirmLeave = useCallback<ConfirmLeave>(
    (then) => (guarding ? setPending(() => then) : then()),
    [guarding],
  )

  return (
    <ConfirmLeaveContext.Provider value={confirmLeave}>
      {children}
      <ConfirmDialog
        open={blocker.state === 'blocked' || pending !== null}
        message="Niet-opgeslagen wijzigingen weggooien?"
        confirmLabel="Weggooien"
        cancelLabel="Blijven"
        onConfirm={() => {
          if (pending !== null) {
            setPending(null)
            pending()
          } else {
            blocker.proceed?.()
          }
        }}
        onCancel={() => {
          setPending(null)
          blocker.reset?.()
        }}
      />
    </ConfirmLeaveContext.Provider>
  )
}
