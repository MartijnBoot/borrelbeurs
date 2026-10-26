/**
 * The bar's wallet routes (B-06 SD9, SD13; plan PD9). A lookup shows the bar a
 * wallet's name and balance, nothing more: never an id, a code or a token. The
 * payments list is this key's last 10 minutes, the window the server's (PD16).
 */
import { z } from 'zod'
import type { components } from '../../../api/generated/schema'
import { request } from '../../../lib/http'
import type { WalletQuery } from './orders'

export const BarWallet: z.ZodType<components['schemas']['BarWallet']> = z.strictObject({
  name: z.string(),
  balance_cents: z.int(),
})
export type BarWallet = z.infer<typeof BarWallet>

export const BarPayment: z.ZodType<components['schemas']['BarPayment']> = z.strictObject({
  entry_id: z.int(),
  amount_cents: z.int(),
  created_at: z.string(),
  lines: z.array(z.strictObject({ name: z.string(), qty: z.int() })).nullable(),
  refunded: z.boolean(),
  name: z.string().nullable(),
})
export type BarPayment = z.infer<typeof BarPayment>

/** The wallet behind a scanned token or a typed code, sent exactly as typed (SD12). */
export function lookupWallet(query: WalletQuery): Promise<BarWallet> {
  return request('POST', '/api/bar/wallet-lookup', { body: query, schema: BarWallet })
}

/** The payments this key booked in the last 10 minutes, newest first (SD9, AC20). */
export function recentPayments(): Promise<BarPayment[]> {
  return request('GET', '/api/bar/payments', { schema: z.array(BarPayment) })
}

/** SD9: 409 `already_refunded` or `wallet_deleted`, 403 `refund_not_allowed` when refused. */
export async function refund(entryId: number, key: string): Promise<void> {
  await request('POST', `/api/payments/${entryId}/refund`, {
    headers: { 'Idempotency-Key': key },
    schema: z.unknown(),
  })
}
