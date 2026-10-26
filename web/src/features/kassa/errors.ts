/** The kassa's refusals in Dutch (B-05 PD15); anything else is a connection error. */
import { HttpError } from '../../lib/http'

const REFUSALS: Readonly<Record<string, string>> = {
  wallet_not_found: 'Onbekende wallet',
  already_reversed: 'Deze opwaardering is al teruggedraaid.',
  insufficient_balance: 'Te weinig saldo om terug te draaien.',
  wallet_deleted: 'Deze wallet bestaat niet meer.',
  nothing_to_move: 'Er is niets over te zetten.',
  // B-06 PD18: refunding a payment.
  already_refunded: 'Deze betaling is al teruggeboekt.',
  refund_not_allowed: 'Terugboeken kan hier alleen binnen 10 minuten na de betaling.',
}

export const NETWORK = 'Verbindingsfout. Probeer opnieuw.'

export function refusalText(error: unknown): string {
  return (error instanceof HttpError && REFUSALS[error.code]) || NETWORK
}
