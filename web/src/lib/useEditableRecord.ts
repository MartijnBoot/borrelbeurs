/**
 * An editable copy of a server record (Phase 6 SD27; AC1, AC2, AC3, AC5; D-03).
 *
 * `values` start as the server's. `patch` holds only the fields whose value
 * differs from the server copy the edits started from, so a request carries
 * exactly what the user changed, and an untouched section sends nothing:
 * `save(send)` resolves `'nothing'` without calling `send` (AC2). A field that is
 * empty (`null`) or unparseable (`'invalid'`) stops the save: `'invalid'`, no
 * request (AC3).
 *
 * A new server record (a `config` message, a refetch) replaces `values` while
 * clean. While dirty it keeps the user's input and sets `conflict` (AC5), unless
 * it already says what the edits say, or says what the last one did (a refetch
 * with the same content); `takeServer` then discards the edits.
 * Lists compare by content; everything else with `Object.is`.
 */
import { useCallback, useState } from 'react'

/** What a field may hold while edited: its type, or empty, or unparseable. */
export type Draft<T> = { [K in keyof T]: T[K] | null | 'invalid' }

export type SaveResult = 'sent' | 'nothing' | 'invalid'

export interface EditableRecord<T> {
  values: Draft<T> | null
  set: <K extends keyof T>(field: K, value: T[K] | null | 'invalid') => void
  dirty: boolean
  patch: Partial<T>
  conflict: boolean
  reset: () => void
  takeServer: () => void
  save: (send: (patch: Partial<T>) => Promise<unknown>) => Promise<SaveResult>
}

function same(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((item, i) => same(item, b[i]))
  }
  return Object.is(a, b)
}

function diff<T extends object>(base: T | null, values: Draft<T> | null): Partial<Draft<T>> {
  if (base === null || values === null) return {}
  const changed: Partial<Draft<T>> = {}
  for (const key of Object.keys(values) as (keyof T)[]) {
    if (!same(values[key], base[key])) changed[key] = values[key]
  }
  return changed
}

export function useEditableRecord<T extends object>(server: T | null): EditableRecord<T> {
  const [base, setBase] = useState<T | null>(server)
  const [values, setValues] = useState<Draft<T> | null>(server)
  const [seen, setSeen] = useState<T | null>(server)
  const [conflict, setConflict] = useState(false)

  const changed = diff(base, values)
  const dirty = Object.keys(changed).length > 0

  if (server !== seen) {
    setSeen(server)
    if (server !== null && seen !== null && Object.keys(diff(seen, server)).length === 0) {
      // a new object with the same content (a refetch, an unrelated `config`): nothing to say
    } else if (!dirty || values === null) {
      setBase(server)
      setValues(server)
      setConflict(false)
    } else if (Object.keys(diff(server, values)).length === 0) {
      setBase(server) // the server now holds what the user typed: an echo of the save
      setConflict(false)
    } else {
      setConflict(true)
    }
  }

  const set = useCallback(<K extends keyof T>(field: K, value: T[K] | null | 'invalid') => {
    setValues((current) => (current === null ? current : { ...current, [field]: value }))
  }, [])

  const reset = useCallback(() => {
    setValues(base)
    setConflict(false)
  }, [base])

  const takeServer = useCallback(() => {
    setBase(seen)
    setValues(seen)
    setConflict(false)
  }, [seen])

  const save = useCallback(
    async (send: (patch: Partial<T>) => Promise<unknown>): Promise<SaveResult> => {
      const entries = Object.values(changed)
      if (entries.length === 0) return 'nothing'
      if (entries.some((value) => value === null || value === 'invalid')) return 'invalid'
      await send(changed as Partial<T>)
      return 'sent'
    },
    [changed],
  )

  return { values, set, dirty, patch: changed as Partial<T>, conflict, reset, takeServer, save }
}
