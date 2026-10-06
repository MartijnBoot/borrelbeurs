# Spec: Phase 7 — Analytics, run lifecycle and export

Status: Approved · Depends on: Phase 6 · Fixes: D-20, D-31

## Problem

v1 has no concept of an event. The earnings workbook is rotated on reset and on any drink
change, so one borrel's revenue can be split across several files, and nothing can be
compared across nights. The money reporting also carries a lie: `p0_total` and
`p0_per_drink` are computed from the bar price, not from `p0`.

This phase delivers the reason a database was introduced at all.

## In scope

- Run lifecycle: create, open, close a borrel. Reset semantics within a run.
- The xlsx export as a **generated artifact** from `order_line`, produced by the background
  worker.
- A bucketed earnings series endpoint.
- A cross-event view: revenue per borrel, per drink per borrel, and price curves compared.

## Out of scope

- Any change to pricing.
- A BI tool or dashboard framework — this is a few SQL-backed views.

## Acceptance criteria

- **AC1.** When a run is closed, the system shall stop the ticker for that run, record
  `ended_at`, and produce a final export.
- **AC2.** When a run is closed and a new one opened, the previous run's orders, ticks and
  news shall remain queryable and unchanged.
- **AC3.** When an export is generated, its totals shall equal the database totals exactly,
  to the cent.
- **AC4.** When a drink is added or removed mid-run, the export shall still cover the whole
  run in one file. *(fixes v1's workbook rotation)*
- **AC5.** When revenue at the fixed bar price is reported, the system shall name it
  `bar_price_total` / `bar_price_per_drink`, not `p0_*`. *(D-20)*
- **AC6.** When the earnings series is requested, the system shall bucket it in SQL so its
  size is bounded regardless of order count. *(D-31)* — Phase 5 brought this forward: `GET
  /api/earnings/series` exists for the live run, in 60 s buckets (Phase 5 SD16). This phase
  extends it with a run parameter and other bucket sizes.
- **AC7.** When an export is requested, the system shall return immediately and produce the
  file asynchronously, and shall run at most one export at a time.
- **AC8.** While an export is running, the system shall continue ticking and serving orders
  without a stall.
- **AC9.** When two runs contain the same drink, the system shall compare them by
  `drink_id`-backed identity, not by name string.
- **AC10.** When a run has no orders, every analytics view shall render an empty state rather
  than an error.

## Verification

- A test asserting export totals equal `SELECT sum(line_total_cents)` exactly.
- Seed two complete synthetic runs and exercise the comparison views.
- A timing test: trigger an export under load and assert tick cadence is unaffected.
- **Manual:** import a real past event from an existing xlsx and compare against the original
  workbook.

## Exit condition

Two past borrels are comparable in the UI, and the generated xlsx matches the database to
the cent.
