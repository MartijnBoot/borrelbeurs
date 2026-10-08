/**
 * 💥 Market events (Phase 6 SD22; AC39): v1's three buttons, each behind its
 * confirmation -- they move every price in the room. "Duur (seconden)" is
 * 1–600, default 30. After a start the status reads "{crash|reset|bubble}
 * gestart!", v1's words; a running event from the store shows its remaining
 * seconds on the server's clock.
 */
import { useEffect, useState } from 'react'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { NumberField } from '../../components/ui/NumberField'
import type { FieldValue } from '../../lib/format'
import { request } from '../../lib/http'
import {
  eventSecondsLeft,
  type MarketEventInfo,
  selectMarketEvents,
  useExchange,
} from '../exchange'
import { seconds } from './duration'
import styles from './ManipulationPage.module.css'

type Kind = MarketEventInfo['kind']

const EVENTS: readonly { kind: Kind; button: string; question: string; word: string }[] = [
  { kind: 'crash', button: '💥 Market Crash', question: 'Marktcrash starten?', word: 'crash' },
  {
    kind: 'correction',
    button: '🔄 Terug naar start',
    question: 'Terug naar start?',
    word: 'reset',
  },
  { kind: 'bubble', button: '🚀 Price Bubble', question: 'Prijsbubbel starten?', word: 'bubble' },
]

const WORD: Readonly<Record<Kind, string>> = Object.fromEntries(
  EVENTS.map((event) => [event.kind, event.word]),
) as Record<Kind, string>

export function MarketEventsSection() {
  const [duration, setDuration] = useState<FieldValue>(30)
  const [asking, setAsking] = useState<(typeof EVENTS)[number] | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const durationS = seconds(duration, 1, 600)

  async function start(kind: Kind) {
    setAsking(null)
    if (durationS === null) return
    setBusy(true)
    try {
      await request('POST', '/api/market/events', {
        body: { kind, duration_ms: durationS * 1000 },
        schema: z.unknown(),
      })
      setStatus(`${WORD[kind]} gestart!`)
    } catch {
      setStatus('Starten mislukt. Probeer opnieuw.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className={styles.row}>
        <NumberField
          label="Duur (seconden)"
          value={duration}
          onChange={setDuration}
          error={durationS === null ? 'Kies 1 tot 600 seconden.' : undefined}
        />
        {status !== null && <span className={styles.muted}>{status}</span>}
      </div>
      <div className={styles.row}>
        {EVENTS.map((event) => (
          <Button
            key={event.kind}
            disabled={busy || durationS === null}
            onClick={() => setAsking(event)}
          >
            {event.button}
          </Button>
        ))}
      </div>
      <RunningEvents />
      <ConfirmDialog
        open={asking !== null}
        message={asking?.question ?? ''}
        confirmLabel="Bevestigen"
        cancelLabel="Annuleren"
        onConfirm={() => asking !== null && void start(asking.kind)}
        onCancel={() => setAsking(null)}
      />
    </>
  )
}

function RunningEvents() {
  const events = useExchange(selectMarketEvents)
  const skewOffsetMs = useExchange((s) => s.skewOffsetMs)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(timer)
  }, [])

  const running = events
    .map((event) => ({ event, left: eventSecondsLeft(event, now + skewOffsetMs) }))
    .filter(({ left }) => left > 0)
  if (running.length === 0) return null
  return (
    <ul className={styles.list}>
      {running.map(({ event, left }) => (
        <li key={event.event_id} className={styles.muted}>
          {`${WORD[event.kind]}: nog ${left} s`}
        </li>
      ))}
    </ul>
  )
}
