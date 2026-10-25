/**
 * The player's own routes (B-05 SD3, SD6, SD21). The wallet cookie travels on
 * its own: the page never sees it. A 401 `no_wallet` means this phone holds no
 * wallet (any more), and the page shows sign-up.
 */
import { z } from 'zod'
import type { components } from '../../api/generated/schema'
import { HttpError, request } from '../../lib/http'

export const Wallet: z.ZodType<components['schemas']['WalletData']> = z.object({
  name: z.string(),
  balance_cents: z.number().int(),
  qr_token: z.string(),
  short_code: z.string(),
  created_at: z.string(),
})
export type Wallet = z.infer<typeof Wallet>

const NameCheck: z.ZodType<components['schemas']['NameCheck']> = z.object({
  available: z.boolean(),
  suggestions: z.array(z.string()),
})

const Suggestions = z.array(z.string())

export function getWallet(): Promise<Wallet> {
  return request('GET', '/api/wallet', { schema: Wallet })
}

export function signUp(name: string, code: string): Promise<Wallet> {
  return request('POST', '/api/wallet', { body: { name, code }, schema: Wallet })
}

/** SD15: the closing entry and the cleared cookie are the server's. */
export async function deleteWallet(): Promise<void> {
  await request('DELETE', '/api/wallet', { schema: z.unknown() })
}

/** `null` when `name` is free; else the server's free suggestions (SD3, AC4). */
export async function nameCheck(name: string, code: string): Promise<readonly string[] | null> {
  const checked = await request('POST', '/api/wallet/name-check', {
    body: { name, code },
    schema: NameCheck,
  })
  return checked.available ? null : checked.suggestions
}

export function isNoWallet(error: unknown): boolean {
  return error instanceof HttpError && error.status === 401
}

/** The suggestions a 409 `name_taken` carries, or `null` for any other failure. */
export function takenSuggestions(error: unknown): readonly string[] | null {
  if (!(error instanceof HttpError) || error.code !== 'name_taken') return null
  const parsed = Suggestions.safeParse(error.details.suggestions)
  return parsed.success ? parsed.data : []
}
