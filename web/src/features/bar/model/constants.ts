/**
 * The bar page's four timing constants (Phase 5 SD1, SD4), in one module.
 * Client constants, not run settings: making them configurable is out of
 * scope. `AGE_SHOW_MS` sits above Phase 4's 5 s poll, so the age line does
 * not flicker while polling.
 */

/** A hold ends this long after the last press is released (SD1). */
export const HOLD_MS = 2000
/** ...and never more than this long after it began (SD1). */
export const HOLD_MAX_MS = 10000
/** Above this displayed-quote age the pad shows the age and "Ververs" (SD4). */
export const AGE_SHOW_MS = 8000
/** Above this latest-quote age the pad is disabled (SD4). */
export const STALE_MS = 15000
