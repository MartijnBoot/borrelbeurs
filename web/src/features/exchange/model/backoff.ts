/**
 * SD15: v1's reconnect curve -- 500 ms, x1.7, capped at 8 s -- with every
 * delay jittered uniformly within ±30 %, so tablets sharing one access point
 * do not reconnect in lockstep.
 */
export const INITIAL_MS = 500
export const FACTOR = 1.7
export const CAP_MS = 8_000
export const JITTER = 0.3

/** The delay before reconnect attempt `attempt` (0 = the first after a close). */
export function reconnectDelayMs(attempt: number, random: () => number): number {
  const curve = Math.min(INITIAL_MS * FACTOR ** attempt, CAP_MS)
  return curve * (1 - JITTER + 2 * JITTER * random())
}
