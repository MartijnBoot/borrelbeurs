/**
 * 📰 Nieuws (Phase 6 SD21; AC39): the store's news, newest first, with level,
 * text and time. "Toevoegen" posts text (1–500) and a level, sent lowercase;
 * "Verwijderen" asks "'{first 40 chars}' verwijderen?". No edit.
 */
import { type FormEvent, useId, useMemo, useState } from 'react'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Field } from '../../components/ui/Field'
import fieldStyles from '../../components/ui/Field.module.css'
import { Select } from '../../components/ui/Select'
import { request } from '../../lib/http'
import { type NewsItem, selectNews, useExchange } from '../exchange'
import styles from './ManipulationPage.module.css'

type Level = NewsItem['level']

const LEVELS = [
  { value: 'info', label: 'Info' },
  { value: 'success', label: 'Succes' },
  { value: 'warning', label: 'Waarschuwing' },
  { value: 'danger', label: 'Gevaar' },
] as const satisfies readonly { value: Level; label: string }[]

const LEVEL_LABEL: Readonly<Record<Level, string>> = Object.fromEntries(
  LEVELS.map((level) => [level.value, level.label]),
) as Record<Level, string>

const TIME = new Intl.DateTimeFormat('nl-NL', { hour: '2-digit', minute: '2-digit' })

export function NewsSection() {
  const news = useExchange(selectNews)
  const newestFirst = useMemo(() => [...news].sort((a, b) => b.ts_ms - a.ts_ms), [news])
  const [text, setText] = useState('')
  const [level, setLevel] = useState<Level>('info')
  const [deleting, setDeleting] = useState<NewsItem | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const textId = useId()

  async function add(event: FormEvent) {
    event.preventDefault()
    if (text.trim() === '') {
      setError('Vul een bericht in.')
      return
    }
    setBusy(true)
    try {
      await request('POST', '/api/news', { body: { text, level }, schema: z.unknown() })
      setText('')
      setError(null)
    } catch {
      setError('Toevoegen mislukt. Probeer opnieuw.')
    } finally {
      setBusy(false)
    }
  }

  async function remove(item: NewsItem) {
    setDeleting(null)
    setBusy(true)
    try {
      await request('DELETE', `/api/news/${item.news_id}`, { schema: z.unknown() })
      setError(null)
    } catch {
      setError('Verwijderen mislukt. Probeer opnieuw.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <form className={styles.row} onSubmit={(event) => void add(event)}>
        <Field id={textId} label="Bericht">
          <input
            id={textId}
            className={fieldStyles.input}
            value={text}
            maxLength={500}
            onChange={(event) => setText(event.target.value)}
          />
        </Field>
        <Select label="Niveau" value={level} options={LEVELS} onChange={setLevel} />
        <Button type="submit" disabled={busy}>
          Toevoegen
        </Button>
      </form>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <ul className={styles.list} aria-label="Nieuws">
        {newestFirst.map((item) => (
          <li key={item.news_id} className={styles.item}>
            <span className={styles.muted}>{TIME.format(item.ts_ms)}</span>
            <span className={styles.badge}>{LEVEL_LABEL[item.level]}</span>
            <span className={styles.grow}>{item.text}</span>
            <Button disabled={busy} onClick={() => setDeleting(item)}>
              Verwijderen
            </Button>
          </li>
        ))}
      </ul>
      <ConfirmDialog
        open={deleting !== null}
        message={`'${deleting?.text.slice(0, 40) ?? ''}' verwijderen?`}
        confirmLabel="Bevestigen"
        cancelLabel="Annuleren"
        onConfirm={() => deleting !== null && void remove(deleting)}
        onCancel={() => setDeleting(null)}
      />
    </>
  )
}
