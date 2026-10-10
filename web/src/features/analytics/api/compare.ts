/**
 * Two runs compared, and a product's price curve in each (Phase 7 SD10; PD13,
 * PD14). `GET /api/analytics/compare?a=&b=`: per product, joined on the
 * product, a side `null` where the product did not sell. `GET
 * /api/analytics/price-curve?product_id=&a=&b=&bucket_s=`: per run, the price
 * at each bucket, minutes since that run's start; `price_cents` is `null` in a
 * bucket with a gap, and a run without the product is `[]`.
 */
import { z } from 'zod'
import { request } from '../../../lib/http'
import type { BucketSeconds } from './runDetail'

const Side = z.object({
  qty: z.number().int(),
  revenue_cents: z.number().int(),
  bar_price_total_cents: z.number().int(),
})

const CompareRow = z.object({
  product_key: z.string(),
  product_id: z.number().int().nullable(),
  name: z.string(),
  a: Side.nullable(),
  b: Side.nullable(),
})
export type CompareRow = z.infer<typeof CompareRow>

export function fetchCompare(a: number, b: number): Promise<CompareRow[]> {
  return request('GET', `/api/analytics/compare?a=${a}&b=${b}`, { schema: z.array(CompareRow) })
}

const CurvePoint = z.object({ minute: z.number().int(), price_cents: z.number().int().nullable() })
export type CurvePoint = z.infer<typeof CurvePoint>

const PriceCurve = z.object({ a: z.array(CurvePoint), b: z.array(CurvePoint) })
export type PriceCurve = z.infer<typeof PriceCurve>

export function fetchPriceCurve(
  productId: number,
  a: number,
  b: number,
  bucketS: BucketSeconds,
): Promise<PriceCurve> {
  return request(
    'GET',
    `/api/analytics/price-curve?product_id=${productId}&a=${a}&b=${b}&bucket_s=${bucketS}`,
    { schema: PriceCurve },
  )
}
