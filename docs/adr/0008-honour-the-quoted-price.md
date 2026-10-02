# ADR 0008: Orders carry the price that was displayed, honoured within a grace

Date: 2026-09-12 · Status: Accepted

## Context

In v1 the bar page shows a price from a buffered snapshot while sending the *current*
`snapshot_version`, so a customer can be charged a price that was never displayed
(`static/bar.html:265` vs `:355`).

The server side is worse than the client side. `snapshot_version` is
`engine.last_snapshot_ts_ms` (`backend/api.py:741`), which only advances on the
`refresh_minutes` gate, while the charged vector `LAST_SNAPSHOT["p_q"]` is recomputed from
live `y` on **every** payload build — including builds triggered by the broadcast loop and
by any client calling `GET /state`. So the charged price is a function of broadcast timing,
and the version token cannot detect that prices moved. The check also runs *outside*
`state_lock` (`api.py:312` vs `:320`), so two tablets can both pass it.

## Decision

The order request carries the exact prices that were on screen:

    POST /api/orders
      Idempotency-Key: <uuid4, stable across retries>
      { lines: [{drink_id, qty}], expected: [{drink_id, unit_price_cents}] }

The server, **with the lock already held**, compares `expected` against live prices and:

- **honours the quoted price** when it is at most a version or two old *and* within one
  `step_quant` of current;
- otherwise returns **409** with the current price and version. The client shows
  "prijs is nu €2,70 — bevestigen?" and a confirmation resends with a new idempotency key,
  because it is a new intent.

## Alternatives

**Strict — any difference rejects.** Provably never charges an unshown price. Rejected: with
Brownian noise live, a price can move one tick in the 300 ms between tap and arrival, so
staff would face constant rejections and learn to mash retry — which is worse for
correctness than the grace.

**Always charge the live price and show a receipt.** Fastest at the bar, no rejections.
Rejected: it reintroduces exactly the "charged a price never shown" problem.

**Two-phase quote then commit.** How you would do it if the money were real. Rejected: it
doubles round-trips, and the bar interaction is "tap +1 Bier, done".

## Consequences

- The bartender said a price out loud to a customer. Honouring it within one tick is the
  correct business behaviour, and the engine's own quantisation supplies a natural tolerance.
- The grace window is a product parameter and must be configurable, not hardcoded.
- `Idempotency-Key` with a unique index means a retry returns the *stored receipt* — the same
  prices — rather than charging twice. v1 has no such protection, and a timeout currently
  shows "Server onbereikbaar" while the order may well have succeeded.
- The check must sit inside the same transaction and the same lock as the state mutation.
  See [design/architecture.md](../design/architecture.md).

## Addendum (Phase 3, SD18)

Date: 2026-10-02

The grace rule is refined: a quoted `unit_price_cents` equal to the live price is charged
**whatever the quote's age**. Every 1 Hz tick bumps `version`, so a strict reading of "at most
a version or two old" would reject any quote held over two seconds even at an unchanged price,
bringing back the constant rejections this ADR rejected. In full, under the lock and per line:

- `unit_price_cents == live` → charge it, at any age;
- `|unit_price_cents − live| ≤ step` and `current_version − quote_version ≤ grace` → honour
  the quoted price;
- otherwise the whole order returns 409 `price_changed` with every line's current price and
  the current version.

`grace` is the product parameter this ADR requires: `run.quote_grace_versions`, default 2,
kept out of the engine's `Params`.
