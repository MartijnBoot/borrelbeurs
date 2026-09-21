# Spec: Phase 3 — API, authorization, ticker and realtime

Status: Draft · Depends on: Phase 2
Fixes: D-06, D-07, D-08, D-15, D-18, D-28, D-31, D-32, D-33, D-34, D-36
Re-establishes in v2: D-27, D-37, D-38, D-39, D-40, D-41, D-42 — these were closed by the
v1 hotfix ([ADR 0007](../adr/0007-v1-authorization-hotfix.md)), **which is discarded when v2
lands**. v2 must prove them again on its own code, not inherit the fix.

## Problem

v1 has no tick thread — time advances on the read path (`api.py:735-738`), which is the root
cause of the meaningless version token and the broken order path. The broadcast is one fat
message containing the full history, full news and full earnings including a per-sale series
that grows all night. One slow client stalls every other client. And with an SPA, v1's
page-level RBAC would become literally nothing.

## In scope

- The ticker: 1 Hz fixed grid, monotonic scheduling, wall stamping, bounded catch-up
  ([ADR 0003](../adr/0003-single-writer-owns-time.md)).
- Postgres advisory lock at boot.
- All REST routes under `/api/*`, with Pydantic schemas and generated OpenAPI.
- Authorization on **every** route plus the WebSocket handshake.
- Argon2 key auth, `bb_<key_id>_<secret>` format, thread-offloaded verify, rate limiting
  before hashing.
- The realtime protocol in [../design/realtime-protocol.md](../design/realtime-protocol.md),
  with per-connection queues and backpressure.
- The order path per [ADR 0008](../adr/0008-honour-the-quoted-price.md).

## Out of scope

- Any UI. This phase is exercised by integration tests and an HTTP client.
- Analytics endpoints and the xlsx export (Phase 7).

## Acceptance criteria

**Authorization**

- **AC1.** When any request without a valid session reaches any route other than login,
  health or the SPA shell, the system shall return 401.
- **AC2.** When a session's role is not permitted for a route, the system shall return 403.
- **AC3.** When a WebSocket handshake carries no valid session, the system shall reject it.
- **AC4.** When `JWT_SECRET` is absent at boot, the system shall fail to start.
- **AC5.** When login is attempted more than the configured rate, the system shall return 429
  **before** performing an argon2 verification.
- **AC6.** When a login attempt is made, the system shall perform exactly one hash
  verification regardless of how many keys exist.
- **AC6a.** When a session cookie is issued, the system shall set `Secure`, `HttpOnly` and
  `SameSite`. *(D-40)*
- **AC6b.** While CORS is configured, the system shall not use a wildcard origin alongside
  credentialed sessions, and CSRF protection shall not rely on the absence of an `Origin`
  header. *(D-41)*
- **AC6c.** When access keys are stored, the system shall store only argon2 hashes, and no
  plaintext key shall exist in the repository or in any config file. *(D-42)*
- **AC6d.** When an admin triggers shutdown from the UI, the system shall authorise it via
  the session, with no separate token mechanism. *(D-27)*

**Order path**

- **AC7.** When an order arrives, the system shall acquire the state lock **before** reading
  any price or version. *(D-07)*
- **AC8.** When two orders are submitted concurrently, the system shall apply them in a
  well-defined order and produce a coherent `price_tick` sequence. *(D-07)*
- **AC9.** When the same `Idempotency-Key` is submitted twice, the system shall charge once
  and return the identical stored receipt both times. *(D-06)*
- **AC10.** When the quoted price is within one `step_quant` and at most the configured
  version grace, the system shall honour the quoted price. *(ADR 0008)*
- **AC11.** When the quoted price is outside that grace, the system shall return 409 with the
  current price and version, **and shall not charge or move the price**.
- **AC12.** When an order is accepted, the price returned in the receipt shall equal the price
  charged. *(D-05 server half)*
- **AC13.** If the database transaction fails, then the system shall discard the candidate
  state, return 503, and leave prices and the ledger unchanged.
- **AC14.** While the state lock is held, the system shall perform no file I/O and no
  WebSocket send, and shall log a warning if held beyond 50 ms.

**Ticker and state**

- **AC15.** When `GET /api/state` is called, the system shall not advance the engine or
  mutate any state. *(D-18)*
- **AC16.** When a client sends any WebSocket message, the system shall not advance the
  engine. *(D-36)*
- **AC17.** When the ticker has not run for three intervals, `/healthz` shall report
  unhealthy and expose `last_tick_age_ms`.
- **AC18.** When a second instance starts against the same database, it shall fail fast on
  the advisory lock.

**Protocol**

- **AC19.** When a market event starts, the system shall broadcast an absolute `t_end_ms`.
  *(D-15)*
- **AC20.** When a tick is broadcast, the system shall not include the history window, the
  full news list, or the per-sale earnings series. *(D-31, D-32)*
- **AC21.** When a client reconnects with `last_version` still inside the ring, the system
  shall send only the missed ticks; otherwise a full snapshot.
- **AC22.** When a client's send queue overflows, the system shall drop queued ticks and
  enqueue a `resync`, and shall not block the ticker or other clients. *(D-34)*
- **AC23.** While broadcasting, the system shall name exactly one price track as charged and
  one as charted. *(D-28)*

## Verification

- `pytest tests/api` with testcontainers Postgres: every endpoint's happy path, validation
  failure, **auth failure**, and not-found.
- A concurrency test issuing simultaneous orders and asserting the ledger and tick sequence.
- An idempotency test replaying the same key.
- A backpressure test with one deliberately stalled client, asserting the ticker keeps time.
- Start a second instance; assert it exits on the advisory lock.

## Exit condition

Integration tests green against a real Postgres, with an explicit authorization test for
every route.
