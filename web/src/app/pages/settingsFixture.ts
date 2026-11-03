/**
 * Test helper (B-12 T5): the settings pages' live-run fixture, moved out of the
 * old `/settings` page test so the screens' tests and the coverage test share
 * it. A live run "Vrijmibo" with two active drinks and one inactive one, one
 * bar key, no wallets, noise on and demand on. `stubServer()` answers every
 * GET the sections make; anything else is a 404.
 */
import { vi } from 'vitest'

const DRINK = {
  slot: 0,
  active: true,
  p_min_cents: 150,
  p0_cents: 260,
  p_max_cents: 500,
  bar_price_cents: 260,
  a: 10,
  d: 0.6,
  s0: 8,
  c: 0.4,
}

export const CONFIG = {
  revision: 3,
  run: {
    run_id: 7,
    name: 'Vrijmibo',
    status: 'live',
    candle_interval_s: 60,
    wallet_required: true,
    credit_limit_cents: 0,
  },
  params: {
    step_quant: 0.1,
    eta: 0.8,
    K: 5,
    lambda_orders: 1.5,
    alpha_price: 0,
    phi_persist: 0.1,
    decay_rho: 0.98,
    history_window_minutes: 15,
    refresh_minutes: 0.2,
    idle_decay_minutes: 0.1,
    idle_rise_minutes: 0.1,
    idle_strength: 1.5,
    idle_rise_strength: 1.5,
    idle_targets: [],
    idle_rise_targets: [],
    demand_enabled: true,
    auto_calibrate_s0: false,
    bm_enabled: true,
    bm_sigma_y: 0.18,
    bm_dt_minutes: 1,
    flow_vol_amp: 0.7,
    flow_beta: 0.25,
    y_clip: 6,
  },
  drinks: [
    { ...DRINK, drink_id: 11, name: 'Bier' },
    { ...DRINK, drink_id: 12, slot: 1, name: 'Wijn' },
    { ...DRINK, drink_id: 13, slot: 2, name: 'Oud', active: false },
  ],
}

const KEY = {
  key_id: 1,
  label: 'Tap 1',
  role: 'bar',
  created_at: '2026-10-01T10:00:00Z',
  last_used_at: null,
  revoked: false,
}

export const SERVED: Readonly<Record<string, unknown>> = {
  '/api/runs/current': { run_id: 7, name: 'Vrijmibo', status: 'live' },
  '/api/runs/7/config': CONFIG,
  '/api/keys': [KEY],
  '/api/analytics/runs': [],
  '/api/profiles': [],
  '/api/admin/wallets': {
    positive_balance_cents: 0,
    negative_balance_cents: 0,
    per_borrel: [],
    wallets: [],
  },
  '/api/admin/wallet-settings': {
    signup_code: null,
    unfunded_days: 30,
    inactive_months: 12,
    show_signup_on_screen: false,
  },
}

export function stubServer(served: Readonly<Record<string, unknown>> = SERVED) {
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(served[path] ?? { error: { code: 'not_found', message: path } }),
          {
            status: path in served ? 200 : 404,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      ),
    ),
  )
}

/** `MobileSectionNav` reads this: `true` is the narrow screen's select. */
export function stubNarrow(narrow: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: narrow,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
}
