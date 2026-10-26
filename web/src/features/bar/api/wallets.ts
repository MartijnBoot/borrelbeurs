/**
 * The bar's wallet routes (B-06 SD9, SD13; plan PD9). A lookup shows the bar a
 * wallet's name and balance, nothing more: never an id, a code or a token.
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

/** The wallet behind a scanned token or a typed code, sent exactly as typed (SD12). */
export function lookupWallet(query: WalletQuery): Promise<BarWallet> {
  return request('POST', '/api/bar/wallet-lookup', { body: query, schema: BarWallet })
}
