/**
 * The custom theme editor (Phase 6 SD28; AC29, AC30; PD8).
 *
 * It starts from the active theme in the store -- pick a preset above first to
 * start from that one -- so the client holds no preset table (Phase 4 SD6). It
 * lists **every key of the theme's tokens**, the server's whole manifest, each
 * with a colour picker and a hex field checked against SD28's pattern, plus the
 * font. "Opslaan" sends `PUT /api/theme {preset: "custom", tokens, font}` with
 * all of them; any invalid hex disables it. The new theme arrives by broadcast.
 */
import { type FormEvent, useId, useMemo, useState } from 'react'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import fieldStyles from '../../components/ui/Field.module.css'
import { Select } from '../../components/ui/Select'
import { request } from '../../lib/http'
import { selectTheme, useExchange } from '../exchange'
import styles from './settings.module.css'

const HEX = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/

type Font = 'inter' | 'garamond'

const FONTS = [
  { value: 'inter', label: 'Inter' },
  { value: 'garamond', label: 'EB Garamond' },
] as const

function fontOf(fontFamily: string): Font {
  return fontFamily.includes('Garamond') ? 'garamond' : 'inter'
}

/** `#abc` as `#aabbcc`: a colour input takes six digits only. */
function sixDigits(hex: string): string {
  return hex.length === 4 ? `#${[...hex.slice(1)].map((c) => c + c).join('')}` : hex
}

export function ThemeEditor() {
  const theme = useExchange(selectTheme)
  const source = useMemo(
    () => (theme === null ? null : { tokens: theme.tokens, font: fontOf(theme.font_family) }),
    [theme],
  )
  const [edited, setEdited] = useState<{ tokens: Record<string, string>; font: Font } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const current = edited ?? source
  if (current === null) return <p className={styles.muted}>Laden…</p>
  const names = Object.keys(current.tokens)
  const valid = names.every((name) => HEX.test(current.tokens[name]))

  const setToken = (name: string, value: string) =>
    setEdited({ ...current, tokens: { ...current.tokens, [name]: value } })

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!valid || current === null) return
    setBusy(true)
    try {
      await request('PUT', '/api/theme', {
        body: { preset: 'custom', tokens: current.tokens, font: current.font },
        schema: z.unknown(),
      })
      setEdited(null)
      setError(null)
    } catch {
      setError('Opslaan mislukt. Probeer opnieuw.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className={styles.subsection} onSubmit={(event) => void save(event)}>
      <h3>Eigen kleurenschema</h3>
      <p className={styles.muted}>Begint bij het actieve schema.</p>
      <div className={styles.grid}>
        {names.map((name) => (
          <TokenRow
            key={name}
            name={name}
            value={current.tokens[name]}
            onChange={(value) => setToken(name, value)}
          />
        ))}
        <Select
          label="Lettertype"
          value={current.font}
          options={FONTS}
          onChange={(font) => setEdited({ ...current, font })}
        />
      </div>
      <div className={styles.row}>
        <Button type="submit" disabled={busy || !valid}>
          Opslaan
        </Button>
        {edited !== null && (
          <Button disabled={busy} onClick={() => setEdited(null)}>
            Herstellen
          </Button>
        )}
      </div>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </form>
  )
}

function TokenRow({
  name,
  value,
  onChange,
}: {
  name: string
  value: string
  onChange: (value: string) => void
}) {
  const id = useId()
  const valid = HEX.test(value)
  return (
    <Field id={id} label={name} error={valid ? undefined : 'Gebruik #rgb of #rrggbb'}>
      <span className={styles.row}>
        <input
          type="color"
          aria-label={`${name} kleur`}
          value={valid ? sixDigits(value) : '#000000'}
          onChange={(event) => onChange(event.target.value)}
        />
        <input
          id={id}
          className={fieldStyles.input}
          value={value}
          maxLength={7}
          aria-invalid={!valid || undefined}
          onChange={(event) => onChange(event.target.value)}
        />
      </span>
    </Field>
  )
}
