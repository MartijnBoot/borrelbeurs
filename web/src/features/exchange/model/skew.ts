/**
 * SD18: the server clock's offset from this one, for countdowns and the
 * header clock (`Date.now() + offset`).
 *
 * Each `pong` is a sample, `server_ts_ms - (sent + received) / 2`, using the
 * pong's own `server_ts_ms` (PD11), not the envelope's. Of the last eight, the
 * one with the smallest round trip wins: the least time in flight is the least
 * room for asymmetry. Before the first pong, `hello.ts_ms - received`.
 */
export const SAMPLES = 8

interface Sample {
  rttMs: number
  offsetMs: number
}

export class SkewEstimator {
  private samples: Sample[] = []
  private fallbackMs: number | null = null

  sample(sentMs: number, receivedMs: number, serverTsMs: number): void {
    this.samples.push({
      rttMs: receivedMs - sentMs,
      offsetMs: serverTsMs - (sentMs + receivedMs) / 2,
    })
    if (this.samples.length > SAMPLES) this.samples.shift()
  }

  fallback(helloTsMs: number, receivedMs: number): void {
    this.fallbackMs = helloTsMs - receivedMs
  }

  offsetMs(): number | null {
    if (this.samples.length === 0) return this.fallbackMs
    let best = this.samples[0]
    for (const s of this.samples) if (s.rttMs < best.rttMs) best = s
    return best.offsetMs
  }
}
