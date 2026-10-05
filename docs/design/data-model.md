# Data model

Postgres. Forward-only Alembic migrations in `db/migrations/`. See
[ADR 0004](../adr/0004-postgres-everywhere-offline-first.md) for why there is one engine in
both environments.

## Principles

- **Stable drink identity.** v1 aligns every array positionally to `names`, so a duplicate
  name silently corrupts every name→index map (`backend/api.py:595-646`) and a drink cannot
  be removed without resetting the world. Here `drink_id` is the identity and `slot` is only
  a rendering position. This is also what makes cross-event analytics possible at all.
- **Money is integer cents.** Never float. v1 accumulates revenue as floats
  (`api.py:349`, `persistence.py:117`) and rounds only at the reporting boundary.
- **Per-drink values are keyed by `drink_id` in JSON**, not stored as positional arrays, so
  adding or removing a drink cannot misalign persisted state.
- **Append-only where it is evidence.** Orders, ticks, news and config revisions are
  history; only `engine_state` is mutated in place.

## Tables

| Table | Purpose | Notes |
|---|---|---|
| `run` | One borrel | `status` draft/live/ended, `run_seed`, `tick_interval_ms`, `params` jsonb, `quote_grace_versions` (default 2, ≥ 0), `candle_interval_ms` (default 60 000, > 0) |
| `run_config_revision` | Append-only parameter history | Answers "who set `eta` to 5 mid-borrel". Gives most of the value of an admin audit log for free |
| `drink` | Drink within a run | `drink_id`, `slot`, `name`, `name_key` (`name.strip().casefold()`, unique per run among non-removed drinks), `p_min_cents`, `p_max_cents`, `p0_cents`, `a`, `d`, `s0`, `c`, `bar_price_cents`, `added_at`, `removed_at` (soft delete) |
| `engine_state` | The live simulation | **One row per run, UPSERT per tick.** `y`, `cum_orders`, `flow_ema`, `last_order_ts`, `jumps`, `last_idle_ms`, `last_bm_ms`, `rng_counter`, `version`, `tick_index`, `t_round`, `wall_ts_ms`. Per-drink values are `json` objects keyed by `drink_id`; each jump carries its `drink_id` |
| `price_tick` | The price history | Append-only, PK `(run_id, version)`, one row per accepted transition. `prices` jsonb `{drink_id: {"p_cont", "p_q"}}`, `source` enum |
| `order` | One customer transaction | `idempotency_key` **UNIQUE**, `version`, `actor_key_id` (FK `auth_key`, nullable), `response` jsonb (the receipt exactly as returned, nullable; Phase 2's orders have neither) |
| `order_line` | One drink within an order | `drink_id`, `qty`, `unit_price_cents`, `line_total_cents`, `p_cont` |
| `news` | News ticker items | `run_id`, `level` stored **lowercase**, `deleted_at` for soft delete |
| `market_event` | Crash / bubble / correction | `run_id`, `kind` crash/bubble/correction, `drink_ids` jsonb, `t_start_ms`, **`t_end_ms`** (> `t_start_ms`), `ended_at` (NULL while active; indexed per run) |
| `auth_key` | Access keys | `key_id`, `label` (1–100 characters), `role` display/bar/admin, **argon2id `secret_hash`**, `created_at`, `revoked_at`, `last_used_at` |
| `theme` | Server-side theming | **A single row:** `id` SMALLINT PK, default 1, `CHECK (id = 1)`; `preset` (one of `oudgeld`, `blauw`, `groen`, `paars`, `rood`); `revision` (≥ 1, bumped by every write); `updated_at`. No row means Blauw at revision 0. Token values are not stored: each preset's 24 tokens and its font live in the server's manifest, `app/runtime/theme.py`. Images arrive with Phase 6 |
| `asset` | Uploaded images | *Arrives with Phase 4+.* `filename`, `content_type`, `bytes` |

### `price_tick.source`

`tick` · `order` · `jump` · `idle` · `reset` · **`gap`**

The `gap` value is written on boot when downtime exceeded the catch-up budget
([ADR 0003](../adr/0003-single-writer-owns-time.md)), so the chart can draw a break rather
than a fake straight line across a period in which the market did not exist.

## Two deliberate deviations from the way-of-working

**Uploaded images live in Postgres**, not object storage. The way-of-working says files go
to Blob Storage and never into the database. External object storage requires internet,
which the event laptop will not have. The assets are a handful of files under 5 MB. If
uploads ever grow past tens of MB, revisit.

**`bytea` rather than a container volume** for the same reason: container disks are
ephemeral, and a volume would not survive a Render redeploy.

## What replaces the v1 files

| v1 | v2 |
|---|---|
| `config/exchange_config.json` — simultaneously config *and* state, rewritten with `fsync` on every order | `run`, `run_config_revision`, `drink`, `engine_state` |
| `config/keys.json` — plaintext, committed to git | `auth_key` with argon2 hashes |
| `static/bar_prices.json` — positional sidecar | `drink.bar_price_cents` |
| `static/news.json` — re-read on every broadcast, grows unbounded | `news` |
| `static/earnings/*.xlsx` — the source of truth for money, appended per line item | `order` + `order_line`; xlsx becomes a generated **export** |
| In-memory `history` deque, lost on restart | `price_tick`, with the deque demoted to a cache |

The xlsx change matters most. v1 does `load_workbook` → `append` → `save` of the entire
workbook **per line item** (`persistence.py:113-120`) with no locking, and re-reads and
re-aggregates the whole file on **every WebSocket broadcast** (`persistence.py:126-190`).

Note also that v1 has two divergent revenue sources — `engine.revenue_per_drink` (in-memory,
zeroed on restart and on any drink change) and the workbook aggregate (survives restart, but
is replaced when a drink is added). They disagree in practice. v2 has one: `order_line`.

## Naming corrections carried into the schema

v1 carries two names that lie, and they are not ported:

- **`p0_total` / `p0_per_drink`** are computed from `BAR_PRICE`, not `p0` (`api.py:770` →
  `persistence.py:126`). They mean "revenue if everything had sold at the fixed bar price".
  Renamed to `bar_price_total` / `bar_price_per_drink`.
- **`calibrate_s0_to_p0`** anchors to the *current* `y`, not to `p0` (`engine.py:38-41`).
  At init and reset those coincide; via `POST /config {"anchor_s0": true}` they do not.

## Analytics

Cross-event queries work because `drink` carries identity independent of array position and
`order_line` stores the price actually charged. The intended questions:

- Revenue per borrel, and per drink per borrel.
- Which drinks sell, and at what price points.
- Price curves for the same drink compared across events.

A tenant dimension is **not** present ([SDR](../adr/0001-setup-decision-record.md) decision
13). The repository layer is structured so one additive migration could add it.
