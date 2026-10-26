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

/** B-06 SD9: a payment at the bar; `lines` is null once the order went with its run. */
export const Payment: z.ZodType<Schemas['KassaPayment']> = z.object({
  entry_id: z.number().int(),
  amount_cents: z.number().int(),
  created_at: z.string(),
  lines: z.array(z.object({ name: z.string(), qty: z.number().int() })).nullable(),
  refunded: z.boolean(),
  actor_label: z.string().nullable(),
})
export type Payment = z.infer<typeof Payment>

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

export const FoundWallet: z.ZodType<Schemas['FoundWallet']> = z.object({
  wallet_id: z.number().int(),
  name: z.string(),
  created_at: z.string(),
  balance_cents: z.number().int(),
  last_topup_at: z.string().nullable(),
})
export type FoundWallet = z.infer<typeof FoundWallet>

const NewCode: z.ZodType<Schemas['NewCode']> = z.object({
  qr_token: z.string(),
  short_code: z.string(),
})

/** B-06 SD9, AC23: the wallet's payments, newest first, at any age. */
export function payments(walletId: number): Promise<Payment[]> {
  return request('GET', `/api/kassa/wallets/${walletId}/payments`, { schema: z.array(Payment) })
}

/** B-06 SD9: 409 `already_refunded` or `wallet_deleted` when refused. */
export async function refund(entryId: number, key: string): Promise<void> {
  await request('POST', `/api/payments/${entryId}/refund`, {
    headers: { 'Idempotency-Key': key },
    schema: BookedEntry,
  })
}

/** SD12: 409 `already_reversed`, `insufficient_balance` or `wallet_deleted` when refused. */
export async function reverse(entryId: number, key: string): Promise<void> {
  await request('POST', `/api/kassa/topups/${entryId}/reversal`, {
    headers: { 'Idempotency-Key': key },
    schema: BookedEntry,
  })
}

/** SD11, PD17: names containing `text`, and the wallet a typed short code names, first. */
export function searchWallets(text: string): Promise<FoundWallet[]> {
  const query = new URLSearchParams({ name: text })
  return request('GET', `/api/kassa/wallets?${query}`, { schema: z.array(FoundWallet) })
}

/** SD11: the balance and the name of `fromWalletId` onto `walletId`; 409 `nothing_to_move`. */
export async function move(walletId: number, fromWalletId: number, key: string): Promise<void> {
  await request('POST', `/api/kassa/wallets/${walletId}/move`, {
    body: { from_wallet_id: fromWalletId },
    headers: { 'Idempotency-Key': key },
    schema: BookedEntry,
  })
}

/** SD14: the old token and short code stop working at once. */
export function newCode(walletId: number): Promise<z.infer<typeof NewCode>> {
  return request('POST', `/api/kassa/wallets/${walletId}/new-code`, { schema: NewCode })
}
