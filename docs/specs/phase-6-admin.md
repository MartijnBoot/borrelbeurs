# Spec: Phase 6 — Manipulation and settings

Status: Approved · Depends on: Phase 5 · Fixes: D-02, D-03, D-04, D-19, D-26, D-29

## Problem

The admin surface is the most destructive in the app and carries v1's most dangerous defect:
the demand/supply form uses `placeholder` instead of `value`, and `+"" === 0` is not `NaN`,
so **clicking save without editing zeroes a/d/s0/c for every drink** (`settings.html:668-680`).
Adding a drink mid-event resets every price and wipes all history (`api.py:599-643`).

It comes last deliberately — by now the whole stack is proven by the read-only display and
the order path.

## In scope

- Manipulation: news CRUD, market events, price jumps, idle configuration.
- Settings: system actions, global parameters, bounds, demand parameters, drinks CRUD, the
  theme picker and editor, image uploads.
- Non-destructive drink add and remove.
- The restored home hub with live connection health.

## Out of scope

- Analytics and run lifecycle (Phase 7).

## Acceptance criteria

**The coercion bug class**

- **AC1.** When a numeric field is left untouched, the system shall omit it from the request
  entirely. *(D-03)*
- **AC2.** When the demand/supply form is saved without any edit, the request body shall be
  **empty** and no coefficient shall change. *(D-03)*
- **AC3.** When a numeric field is cleared, the system shall send `null`, never `0`.
- **AC4.** When a drink is added with optional coefficients blank, the system shall apply the
  server defaults, not zeros. *(D-04)*
- **AC5.** While any form is dirty, an incoming broadcast shall not overwrite the user's
  input; the system shall offer to take the server values instead.

**Drinks**

- **AC6.** When a drink is added mid-run, every existing drink's price, history, totals and
  active jumps shall be unchanged. *(D-02)*
- **AC7.** When a drink is removed mid-run, its order lines and revenue shall remain in the
  ledger, and the other drinks' prices shall not reset. *(D-02)*
- **AC8.** When a drink is removed, the relative-demand denominator and the market mean shall
  range over active drinks only.
- **AC9.** When removing the last active drink is attempted, the system shall refuse.
- **AC10.** When a drink with an in-flight price jump is removed, the jump shall be cancelled.

**Theme and uploads**

- **AC11.** When the theme editor is opened, all 21 tokens shall be editable. *(D-19)*
- **AC12.** When an upload is not an allowed image type, the system shall reject it.
- **AC13.** When an SVG is uploaded, the system shall not serve it in a way that can execute
  script in the session's origin. *(D-29)*
- **AC14.** When a theme image is replaced, the previous asset shall be removed.

**Safety and shell**

- **AC15.** When a destructive action is triggered, the system shall show an in-app
  confirmation dialog with the Dutch wording preserved, not a native `confirm`.
- **AC16.** When the home page loads, it shall show live connection and run health, and shall
  log no uncaught errors. *(D-26)*
- **AC17.** When a market correction ("mid") fires, the system shall show a calm banner — not
  a third pulsing overlay.

## Verification

- **Component test written first as a failing regression:** load a settings snapshot, click
  save without editing, assert the request body is empty. This is the D-03 gate.
- Integration: add and remove a drink mid-run, asserting other drinks' `y` values are
  bitwise unchanged.
- Playwright: the destructive-confirmation flow; the theme editor round trip.
- **Manual:** configure a borrel from an empty database, end to end.

## Exit condition

An admin can configure a complete borrel from scratch, and no form can destroy data it was
not asked to change.
