/**
 * The "Thema" section of `/settings` (SD10): the five presets, the current
 * one marked. The key -> label pairs are UI strings, not theme data -- the
 * tokens stay on the server (SD6) -- so these are labelled buttons, not
 * colour swatches (Risks R3, option a).
 *
 * Selecting one calls `PUT /api/theme` and changes nothing here: the mark
 * moves when the `theme` broadcast reaches the store, because the WebSocket
 * is the only writer of live state. A failure shows an error and leaves the
 * mark where it was.
 */
import { useState } from 'react'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { HttpError, request } from '../../lib/http'
import { selectTheme, useExchange } from '../exchange'
import styles from './ThemeSection.module.css'

const PRESETS = [
  ['oudgeld', 'Oud Geld'],
  ['blauw', 'Blauw'],
  ['groen', 'Groen'],
  ['paars', 'Paars'],
  ['rood', 'Rood'],
] as const

type PresetKey = (typeof PRESETS)[number][0]

// The strings already in the app: SD13's for a 403, PD17's for the rest.
function failureText(error: unknown): string {
  return error instanceof HttpError && error.status === 403
    ? 'Geen toegang'
    : 'Verbindingsfout. Probeer opnieuw.'
}

export function ThemeSection() {
  const current = useExchange(selectTheme)?.preset
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function choose(preset: PresetKey) {
    setBusy(true)
    try {
      await request('PUT', '/api/theme', { body: { preset }, schema: z.unknown() })
      setError(null)
    } catch (failure) {
      setError(failureText(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className={styles.section}>
      <h2>Thema</h2>
      <div className={styles.presets}>
        {PRESETS.map(([key, label]) => (
          <Button
            key={key}
            selected={key === current}
            disabled={busy}
            onClick={() => void choose(key)}
          >
            {label}
          </Button>
        ))}
      </div>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
