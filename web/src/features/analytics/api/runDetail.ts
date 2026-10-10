/**
 * A run's detail and its earnings series (Phase 7 SD9, SD10; PD11).
 *
 * `GET /api/analytics/runs/{run_id}`: the run's totals and a row per product
 * that sold, `removed` when none of its drinks is active any more.
 * `GET /api/earnings/series?run_id=&bucket_s=`: cumulative revenue at bucket
 * ends, integer cents.
 */
import { z } from 'zod'
import { request } from '../../../lib/http'
import { AnalyticsRun } from './runs'

const ProductRow = z.object({
  product_key: z.string(),
  product_id: z.number().int().nullable(),
  name: z.string(),
  qty: z.number().int(),
  revenue_cents: z.number().int(),
  bar_price_total_cents: z.number().int(),
  avg_price_cents: z.number().int(),
  removed: z.boolean(),
})
export type ProductRow = z.infer<typeof ProductRow>

const RunDetailData = AnalyticsRun.extend({ per_product: z.array(ProductRow) })
export type RunDetailData = z.infer<typeof RunDetailData>

export function fetchRunDetail(runId: number): Promise<RunDetailData> {
  return request('GET', `/api/analytics/runs/${runId}`, { schema: RunDetailData })
}

const SeriesPoint = z.object({ t_ms: z.number().int(), cum_revenue_cents: z.number().int() })
export type SeriesPoint = z.infer<typeof SeriesPoint>

export type BucketSeconds = 60 | 300 | 900

export function fetchSeries(runId: number, bucketS: BucketSeconds): Promise<SeriesPoint[]> {
  return request('GET', `/api/earnings/series?run_id=${runId}&bucket_s=${bucketS}`, {
    schema: z.array(SeriesPoint),
  })
}
