/**
 * An `Idempotency-Key` for a wallet write (B-05 SD10, SD24; AC18, AC20): 16
 * random bytes from `crypto.getRandomValues` as 32 hex characters, which
 * `^[A-Za-z0-9_-]{8,128}$` accepts.
 *
 * Not Web Crypto's UUID function: a browser offers that only in a secure
 * context, and at the venue the kassa page is plain HTTP on a LAN address
 * (D-49's cause). `getRandomValues` works in any context; the wallet code's
 * source scan (`src/walletCode.provenance.test.ts`) keeps it that way.
 */
export function newIdempotencyKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}
