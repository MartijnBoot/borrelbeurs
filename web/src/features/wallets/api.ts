/**
 * Admin's wallet routes (B-05 SD6, SD15, SD16). The totals are the server's:
 * the page adds nothing up.
 */
import { z } from 'zod'
import type { components } from '../../api/generated/schema'
import { request } from '../../lib/http'

type Schemas = components['schemas']

export const Overview: z.ZodType<Schemas['WalletsOverview']> = z.object({
  outstanding_cents: z.number().int(),
  per_borrel: z.array(
    z.object({
      run_id: z.number().int().nullable(),
      name: z.string().nullable(),
      net_topup_cents: z.number().int(),
    }),
  ),
  wallets: z.array(
    z.object({
      wallet_id: z.number().int(),
      name: z.string(),
      balance_cents: z.number().int(),
      last_activity_at: z.string(),
    }),
  ),
})
export type Overview = z.infer<typeof Overview>
export type ListedWallet = Overview['wallets'][number]

export const WalletSettings: z.ZodType<Schemas['WalletSettingsData']> = z.object({
  signup_code: z.string().nullable(),
  unfunded_days: z.number().int(),
  inactive_months: z.number().int(),
})
export type WalletSettings = z.infer<typeof WalletSettings>

export function getOverview(): Promise<Overview> {
  return request('GET', '/api/admin/wallets', { schema: Overview })
}

export function getSettings(): Promise<WalletSettings> {
  return request('GET', '/api/admin/wallet-settings', { schema: WalletSettings })
}

/** PD12: a blank code is stored as null, sign-up closed; the server says so in its answer. */
export function putSettings(settings: WalletSettings): Promise<WalletSettings> {
  return request('PUT', '/api/admin/wallet-settings', { body: settings, schema: WalletSettings })
}

export async function deleteWallet(walletId: number): Promise<void> {
  await request('DELETE', `/api/admin/wallets/${walletId}`, { schema: z.unknown() })
}
