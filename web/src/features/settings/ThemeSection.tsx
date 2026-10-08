/**
 * The "🎨 Kleurenschema" section of `/settings` (Phase 4 SD10; moved here by
 * Phase 6 PD13; `SettingsLayout` gives it its heading): the five presets, the current
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
  // The stored custom theme (Phase 6 SD28): 409 `no_custom_theme` until one is saved.
  ['custom', 'Eigen'],
] as const

type PresetKey = (typeof PRESETS)[number][0]

// The strings already in the app: SD13's for a 403, PD17's for the rest.
function failureText(error: unknown): string {
  if (error instanceof HttpError && error.code === 'no_custom_theme') {
    return 'Nog geen eigen schema. Sla er eerst een op.'
  }
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
    <div>
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
    </div>
  )
}
