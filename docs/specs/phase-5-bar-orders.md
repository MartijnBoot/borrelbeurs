# Spec: Phase 5 — Bar page and the order path

Status: Draft · Depends on: Phase 4 · Fixes: D-05

## Problem

This is where money changes hands, and where v1's worst user-facing defect lives: the bar
page displays a held price while the server charges the live one, so **a customer can be
charged a price they were never shown** (`bar.html:265` vs `:355`).

The anti-flicker buffering that causes this exists for a good reason — prices must not
change under a bartender's thumb mid-tap. The fix is not to remove it but to make the price
and its version inseparable.

## In scope

- The order pad, with Dutch strings preserved.
- The held-quote buffer as a **display hold**, with `Quote` as one immutable record.
- The 409 confirmation flow.
- Idempotency keys per tap.
- Pending-order optimistic UI.
- The financial overview panel, driven by server aggregates.
- The revenue chart on lightweight-charts.

## Out of scope

- Admin configuration surfaces (Phase 6).
- Cross-event analytics (Phase 7).

## Acceptance criteria

- **AC1.** When a bartender taps a drink, the system shall send the exact `unit_price_cents`
  currently displayed, together with the version that price belongs to. *(D-05)*
- **AC2.** While a quote is held for display, the system shall make it structurally
  impossible to obtain the price without its matching version — they shall be one immutable
  object.
- **AC3.** When the server honours a quoted price, the confirmation shall show that price.
- **AC4.** When the server returns 409, the system shall show the new price in Dutch
  ("prijs is nu €X — bevestigen?") and shall not have charged anything.
- **AC5.** When the bartender confirms after a 409, the system shall send a **new**
  idempotency key.
- **AC6.** When the same tap is retried after a network timeout, the system shall reuse the
  same idempotency key, and the customer shall be charged once.
- **AC7.** When an order succeeds, the held quote shall be force-promoted so the next tap
  uses a current price.
- **AC8.** While an order is in flight, the system shall show it as pending without
  computing revenue locally.
- **AC9.** When revenue is displayed, it shall come from the server. There shall be no
  client-side revenue model. *(deletes `computeLocalEarnings`)*
- **AC10.** While the held quote is older than a threshold, the system shall indicate its age
  so the hold reads as deliberate rather than as a frozen screen.
- **AC11.** When two sales occur in the same second, the revenue chart shall render both
  without a duplicate-timestamp error. *(lightweight-charts requires strictly ascending
  unique times; Chart.js tolerated duplicates)*
- **AC12.** At ≤640 px the revenue chart shall not be constructed at all.

## Verification

- **A property test** over thousands of random interleavings of tick arrivals and taps,
  asserting `request.price_version === displayedQuote.version`. This is the money bug; an
  example test is not enough. Evidence: the run output with the case count.
- Playwright: tap → order posted at the displayed price; force a 409 → new price shown, not
  charged; double-tap → two distinct idempotency keys.
- A unit test for the same-second revenue adapter.
- **Manual:** run a mock service round with two phones on the same access point.

## Exit condition

The price shown is the price charged, or the order is rejected — enforced by a property test
that would fail if the invariant broke.
