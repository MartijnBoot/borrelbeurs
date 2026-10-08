/**
 * 🖼️ Afbeeldingen (Phase 6 SD29; AC31, AC33, AC34, AC39): the four image slots.
 *
 * Each slot previews the store's `theme.images` -- a broadcast updates it --
 * uploads a chosen file as multipart `file` (PD1) and removes the image behind
 * `ConfirmDialog` "'{slot label}' verwijderen?". The server types the bytes;
 * its 413 and 415 show in Dutch under the slot.
 */
import { type ChangeEvent, useId, useState } from 'react'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { HttpError, request } from '../../lib/http'
import { selectTheme, type ThemeData, useExchange } from '../exchange'
import styles from './settings.module.css'

type Slot = keyof ThemeData['images']

const SLOTS: readonly (readonly [Slot, string])[] = [
  ['bg', 'Achtergrond'],
  ['header', 'Header'],
  ['logo', 'Logo'],
  ['promo', 'Promotie tegel'],
]

const ImageData = z.object({ asset_id: z.number().int().nullable(), revision: z.number().int() })

const REFUSALS: Readonly<Record<string, string>> = {
  too_large: 'Afbeelding is groter dan 5 MB.',
  unsupported_media_type: 'Alleen PNG, JPEG, WebP of GIF.',
}

function failureText(error: unknown, fallback: string): string {
  if (error instanceof HttpError && REFUSALS[error.code] !== undefined) return REFUSALS[error.code]
  return fallback
}

export function ImagesSection() {
  const images = useExchange(selectTheme)?.images ?? null
  return (
    <>
      {SLOTS.map(([slot, label]) => (
        <ImageSlot key={slot} slot={slot} label={label} url={images?.[slot] ?? null} />
      ))}
    </>
  )
}

function ImageSlot({ slot, label, url }: { slot: Slot; label: string; url: string | null }) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputId = useId()

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (file === undefined) return
    const formData = new FormData()
    formData.append('file', file)
    setBusy(true)
    try {
      await request('POST', `/api/theme/images/${slot}`, { formData, schema: ImageData })
      setError(null)
    } catch (caught) {
      setError(failureText(caught, 'Uploaden mislukt. Probeer opnieuw.'))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setAsking(false)
    setBusy(true)
    try {
      await request('DELETE', `/api/theme/images/${slot}`, { schema: ImageData })
      setError(null)
    } catch (caught) {
      setError(failureText(caught, 'Verwijderen mislukt. Probeer opnieuw.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <fieldset className={styles.subsection} aria-label={label}>
      <h3>{label}</h3>
      <div className={styles.row}>
        {url === null ? (
          <p className={styles.muted}>Geen afbeelding</p>
        ) : (
          <img src={url} alt={label} className={styles.preview} />
        )}
        <label htmlFor={inputId} className={styles.inline}>
          {`${label} kiezen`}
        </label>
        <input
          id={inputId}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          disabled={busy}
          onChange={(event) => void upload(event)}
        />
        {url !== null && (
          <Button disabled={busy} onClick={() => setAsking(true)}>
            Verwijderen
          </Button>
        )}
      </div>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <ConfirmDialog
        open={asking}
        message={`'${label}' verwijderen?`}
        confirmLabel="Bevestigen"
        cancelLabel="Annuleren"
        onConfirm={() => void remove()}
        onCancel={() => setAsking(false)}
      />
    </fieldset>
  )
}
