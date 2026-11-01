/**
 * Whether saving `next` over the `saved` sign-up code breaks QR codes already
 * printed with it (B-09 SD7): `'change'` for a different code, `'clear'` when
 * sign-up closes, `null` when nothing printed can break. "Different" is the
 * server's trimmed, case-insensitive comparison; `toLowerCase` stands in for
 * Python's `casefold` and can only ask once too often, never miss (SD9).
 */
export function breaksPrinted(
  saved: string | null,
  next: string | null,
): 'change' | 'clear' | null {
  if (saved === null) return null
  if (next === null || next.trim() === '') return 'clear'
  return next.trim().toLowerCase() !== saved.trim().toLowerCase() ? 'change' : null
}
