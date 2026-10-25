/**
 * The kassa's routes (B-05 SD10-SD14, SD22). The server normalises a typed short
 * code (PD6), so the page sends it exactly as typed. A money write carries an
 * `Idempotency-Key` made once per intent by the caller, so a retry of that
 * intent cannot book it twice (AC18).
 */
import { z } from 'zod'
import type { components } from '../../api/generated/schema'
import { request } from '../../lib/http'

type Schemas = components['schemas']

export const KassaWallet: z.ZodType<Schemas['KassaWalletData']> = z.object({
  wallet_id: z.number().int(),
  name: z.string(),
  balance_cents: z.number().int(),
  created_at: z.string(),
  last_topup_at: z.string().nullable(),
  recent_topup: z.object({ at: z.string(), amount_cents: z.number().int() }).nullable(),
})
export type KassaWallet = z.infer<typeof KassaWallet>

export const Topup: z.ZodType<Schemas['TopupData']> = z.object({
  entry_id: z.number().int(),
  amount_cents: z.number().int(),
  created_at: z.string(),
  actor_label: z.string().nullable(),
  reversed: z.boolean(),
})
export type Topup = z.infer<typeof Topup>

const BookedEntry: z.ZodType<Schemas['BookedEntry']> = z.object({
  entry_id: z.number().int(),
  wallet_id: z.number().int(),
  amount_cents: z.number().int(),
  created_at: z.string(),
})

/** What a lookup is by: a scanned token or a typed code (AC14). */
export type WalletQuery = { qr_token: string } | { short_code: string }

export function lookup(query: WalletQuery): Promise<KassaWallet> {
  return request('POST', '/api/kassa/lookup', { body: query, schema: KassaWallet })
}

export function topups(walletId: number): Promise<Topup[]> {
  return request('GET', `/api/kassa/wallets/${walletId}/topups`, { schema: z.array(Topup) })
}

export async function topUp(walletId: number, amountCents: number, key: string): Promise<void> {
  await request('POST', `/api/kassa/wallets/${walletId}/topups`, {
    body: { amount_cents: amountCents },
    headers: { 'Idempotency-Key': key },
    schema: BookedEntry,
  })
}
