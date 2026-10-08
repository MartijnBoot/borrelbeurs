/**
 * 🧹 Systeemacties (Phase 6 SD26; AC39).
 *
 * - **"⛔ Sluit app"** asks "Applicatie nu afsluiten?" in `ConfirmDialog`, then
 *   posts `/api/admin/shutdown` and shows "App sluit nu af…" with every control
 *   disabled: the server is going away.
 * - **"📌 Zet huidige prijs als evenwicht"** is v1's anchor, with no
 *   confirmation, as in v1. It needs the live market, so it is disabled for a
 *   draft (the server says 409 `run_not_live` otherwise).
 *
 * No reset (Phase 7) and no earnings download (Phase 7's export).
 */
import { useState } from 'react'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Toast } from '../../components/ui/Toast'
import { request } from '../../lib/http'
import styles from './settings.module.css'
import { useCurrentRun } from './useCurrentRun'
import { Revision } from './useRunConfig'

export function SystemSection() {
  const { run } = useCurrentRun()
  const [asking, setAsking] = useState(false)
  const [closing, setClosing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const live = run?.status === 'live'

  async function shutdown() {
    setAsking(false)
    setBusy(true)
    try {
      await request('POST', '/api/admin/shutdown', { schema: z.unknown() })
      setClosing(true)
      setError(null)
    } catch {
      setError('Afsluiten mislukt. Probeer opnieuw.')
    } finally {
      setBusy(false)
    }
  }

  async function anchor(runId: number) {
    setBusy(true)
    try {
      await request('POST', `/api/runs/${runId}/anchor-s0`, { schema: Revision })
      setNotice('Evenwicht gezet op de huidige prijzen')
      setError(null)
    } catch {
      setError('Evenwicht zetten mislukt. Probeer opnieuw.')
    } finally {
      setBusy(false)
    }
  }

  const disabled = busy || closing
  return (
    <>
      <div className={styles.row}>
        <Button disabled={disabled || !live} onClick={() => run != null && void anchor(run.run_id)}>
          📌 Zet huidige prijs als evenwicht
        </Button>
        <Button disabled={disabled} onClick={() => setAsking(true)}>
          ⛔ Sluit app
        </Button>
      </div>
      {closing && <p className={styles.muted}>App sluit nu af…</p>}
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <ConfirmDialog
        open={asking}
        message="Applicatie nu afsluiten?"
        confirmLabel="Bevestigen"
        cancelLabel="Annuleren"
        onConfirm={() => void shutdown()}
        onCancel={() => setAsking(false)}
      />
      <Toast message={notice} onDone={() => setNotice(null)} />
    </>
  )
}
