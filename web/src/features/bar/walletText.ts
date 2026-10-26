/**
 * The bar's wallet sentences (B-06 SD7, SD18; PD18), shared by the pad's button
 * and the pending list. A balance is spelled with `formatBalance` (SD19).
 */
import { formatBalance, formatEuro } from '../../lib/format'
import type { Receipt } from './api/orders'

/** "Saldo €7,50 — nog €5,00 tekort" (SD18). */
export function shortfallText(balanceCents: number, shortfallCents: number): string {
  return `Saldo ${formatBalance(balanceCents)} — nog ${formatEuro(shortfallCents)} tekort`
}

/** "Betaald €8,40 — Jan, saldo −€0,90", from the receipt (SD7, AC13). */
export function paidText(receipt: Receipt & { wallet: NonNullable<Receipt['wallet']> }): string {
  const { name, balance_after_cents } = receipt.wallet
  return `Betaald ${formatEuro(receipt.total_cents)} — ${name}, saldo ${formatBalance(balance_after_cents)}`
}
