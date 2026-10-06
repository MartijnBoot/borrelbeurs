/**
 * `POST /api/orders` at the bar's boundary (Phase 5 SD7, SD8, SD9).
 *
 * One call is one attempt: the `Idempotency-Key` header, the intent's frozen
 * body, and an 8 s timeout. A receipt (201, or a 200 replay) and a 409
 * `price_changed` are both answers the intent machine acts on, so they
 * resolve, each Zod-validated. Everything else rejects as `lib/http` raised it
 * -- an `HttpError` for an HTTP answer, the original error for a network
 * failure or a timeout -- for the intent machine to classify.
 */
import { z } from 'zod'
import { HttpError, request } from '../../../lib/http'

/** SD8: a request is abandoned after this long, then retried. */
export const ORDER_TIMEOUT_MS = 8000

const Int = z.int()
const NonNegative = z.int().nonnegative()

/** `app/runtime/orders.py: Receipt`, field for field. */
export const Receipt = z.strictObject({
  order_id: Int,
  version: NonNegative,
  wall_ts_ms: Int,
  quote_version: NonNegative,
  lines: z
    .array(
      z.strictObject({
        drink_id: Int,
        qty: z.int().min(1),
        unit_price_cents: NonNegative,
        line_total_cents: NonNegative,
      }),
    )
    .min(1),
  total_cents: NonNegative,
})

/** A 409 `price_changed`'s extra fields (`HttpError.details`): the live version and prices. */
export const PriceChangedBody = z.object({
  version: NonNegative,
  prices: z.array(z.strictObject({ drink_id: Int, price_cents: NonNegative })),
})

export type Receipt = z.infer<typeof Receipt>
export type PriceChangedBody = z.infer<typeof PriceChangedBody>

export interface OrderBody {
  readonly quote_version: number
  readonly lines: readonly {
    readonly drink_id: number
    readonly qty: number
    readonly unit_price_cents: number
  }[]
}

export type OrderOutcome =
  { kind: 'accepted'; receipt: Receipt } | { kind: 'price_changed'; body: PriceChangedBody }

export async function postOrder({
  key,
  body,
  signal = AbortSignal.timeout(ORDER_TIMEOUT_MS),
}: {
  key: string
  body: OrderBody
  signal?: AbortSignal
}): Promise<OrderOutcome> {
  try {
    const receipt = await request('POST', '/api/orders', {
      body,
      schema: Receipt,
      headers: { 'Idempotency-Key': key },
      signal,
    })
    return { kind: 'accepted', receipt }
  } catch (error) {
    if (!(error instanceof HttpError) || error.status !== 409 || error.code !== 'price_changed') {
      throw error
    }
    const parsed = PriceChangedBody.safeParse(error.details)
    if (!parsed.success) {
      throw new HttpError(409, 'invalid_response', 'the price_changed body is not valid')
    }
    return { kind: 'price_changed', body: parsed.data }
  }
}
