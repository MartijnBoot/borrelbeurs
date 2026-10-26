/**
 * The bar page's timing constants (Phase 5 SD1, SD4; B-06 SD6), in one module.
 * Client constants, not run settings: making them configurable is out of
 * scope. `AGE_SHOW_MS` sits above Phase 4's 5 s poll, so the age line does
 * not flicker while polling.
 */

/** A hold ends this long after the last press is released (SD1). */
export const HOLD_MS = 2000
/** ...and never more than this long after it began (SD1). */
export const HOLD_MAX_MS = 10000
/** After one conflict is answered, the next one's "Bevestigen" ignores taps this long, so a double tap cannot confirm it unread (AC14). */
export const CONFIRM_GUARD_MS = 400
/** Above this displayed-quote age the pad shows the age and "Ververs" (SD4). */
export const AGE_SHOW_MS = 8000
/** Above this latest-quote age the pad is disabled (SD4). */
export const STALE_MS = 15000
/** B-06 SD6, PD15: with no tap on the page this long, a held wallet and the basket clear. */
export const WALLET_IDLE_MS = 60_000
/** B-06 PD16: the recent payments are fetched again this often while the page is open. */
export const PAYMENTS_REFRESH_MS = 30_000
