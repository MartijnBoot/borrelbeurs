# Spec: Phase 2 — Data model and persistence

Status: Draft · Depends on: Phase 1 · Fixes: D-01, D-09, D-10, D-11, D-12, D-16, D-24, D-30, D-35

## Problem

v1 persists only static config (`engine.py:139-150`), so **every restart snaps every price
back to `p0`** and loses history, totals and revenue. Money lives in an xlsx that is
read-modify-written per line item and re-aggregated on every WebSocket broadcast. Two
divergent revenue sources disagree in practice. Drink identity is array position, so a
duplicate name corrupts every lookup.

## In scope

- The full schema in [../design/data-model.md](../design/data-model.md), as forward-only
  Alembic migrations.
- Repository layer; async SQLAlchemy over asyncpg.
- A **seed/import script** that loads today's `exchange_config.json`, `keys.json`,
  `news.json` and an existing earnings workbook into the database.
- Rehydrate-on-boot, including the gap rule and the `GROUP BY` earnings recompute.
- The in-memory history ring as a cache over `price_tick`.

## Out of scope

- HTTP routes, the ticker, realtime, any UI. Persistence is exercised by tests and the
  import script only.

## Acceptance criteria

- **AC1.** When the process is killed and restarted mid-run, the system shall resume with
  `y`, `cum_orders`, `flow_ema`, active jumps, counters and the history window intact, and
  shall lose zero orders. *(D-01)*
- **AC2.** When downtime exceeded the catch-up budget, the system shall re-anchor the tick
  grid, write a `price_tick` with `source='gap'`, and not evolve prices across the gap.
- **AC3.** While any euro amount is stored, the system shall store it as integer cents.
  A test shall assert no float column holds money. *(D-09)*
- **AC4.** When revenue is queried, the system shall derive it from `order_line` only.
  There shall be exactly one revenue source. *(D-10)*
- **AC5.** When per-drink state is persisted, the system shall key it by `drink_id`, never
  by array position. *(D-24)*
- **AC6.** When a drink is added with a name that already exists in the run, the system
  shall reject it. *(D-24)*
- **AC7.** When `bar_price` is set and the engine is subsequently saved, the system shall
  retain the bar price. *(D-11)*
- **AC8.** When the import script runs against the current v1 files, the system shall
  reproduce the same drinks, bounds, coefficients, params, news and revenue totals.
- **AC9.** When news is imported or created, the system shall store `level` lowercase, and
  the migration shall normalise historical capitalised values. *(D-16)*
- **AC10.** When a snapshot is built, the system shall not read any file. *(D-30, D-35)*
- **AC11.** When two orders are written concurrently, the system shall lose neither. *(D-12)*
- **AC12.** When any migration is applied and then rolled back against a scratch database,
  both shall succeed.

## Verification

- `pytest tests/db` with testcontainers Postgres, same major version as production.
- **The durability test**: start the app, place orders, `docker kill`, restart, assert prices
  and history resumed and order count is unchanged. Evidence: the assertion output.
- Run the import script against the real `config/` and diff the resulting state against the
  v1 snapshot payload.
- `alembic upgrade head && alembic downgrade base` in CI.

## Exit condition

Today's live configuration round-trips through Postgres, and a hard kill mid-run loses at
most one tick of drift and zero orders.
