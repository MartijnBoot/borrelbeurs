/** The `aria-describedby` an input inside a `Field` carries: its hint and error ids. */
export function describedBy(id: string, hint?: string, error?: string): string | undefined {
  const ids = [hint !== undefined ? `${id}-hint` : '', error !== undefined ? `${id}-error` : '']
  const joined = ids.filter(Boolean).join(' ')
  return joined === '' ? undefined : joined
}
