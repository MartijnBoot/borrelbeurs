# Defect register

Every defect found in the v1 audit. The rebuild **fixes these rather than porting them**, so
each becomes at least one acceptance criterion with a test in the relevant phase spec.

This means the rebuild is deliberately **not** a behavioural clone of v1. Differences are
intentional and documented here.

`ID` is referenced from phase specs as `Fixes: D-nn`.

## A. Money and data loss

| ID | Defect | Where | Consequence | Phase |
|---|---|---|---|---|
| D-01 | Engine dynamic state is never persisted — `to_persist()` saves only static config | `engine.py:139-150` | Restart mid-borrel: **every price snaps back to `p0`**, history, totals and revenue lost | 2 |
| D-02 | `POST /drinks` rebuilds the whole `ExchangeState` | `api.py:599-643` | Adding one drink mid-event **resets every price and wipes all history** | 6 |
| D-03 | Demand form uses `placeholder` not `value`; `+"" === 0` is not `NaN` | `settings.html:668-680` | Saving without editing **zeroes a/d/s0/c for every drink** | 6 |
| D-04 | Same coercion pattern in add-drink | `settings.html:701,712-715` | Server defaults never apply; every optional field arrives as `0` | 6 |
| D-05 | Bar shows the applied (held) price but the server charges the live one | `bar.html:265` vs `:355`; `api.py:741-743` | **Customer charged a price never displayed** | 5 |
| D-06 | No order idempotency key | `api.py:310-370` | A retry on flaky wifi **double-charges and double-moves the price** | 3 |
| D-07 | Stale check runs before `state_lock` (TOCTOU) | `api.py:312` vs `:320` | Two concurrent orders both pass the same version | 3 |
| D-08 | `snapshot_version` is `last_snapshot_ts_ms`, a timestamp | `engine.py:182-188` | Does not change when orders, jumps or noise move prices | 3 |
| D-09 | Money handled as floats throughout | `api.py:349`, `persistence.py:117` | Rounding drift in revenue | 2 |
| D-10 | Two divergent revenue sources | in-memory vs `persistence.py:126` | They disagree after any restart or drink change | 2 |
| D-11 | `bar_price` key destroyed by the first save after boot | `persistence.py:70-71` vs `:76-77` | Bar prices survive only in the sidecar file | 2 |
| D-12 | xlsx read-modify-write of the whole workbook **per line item** | `persistence.py:113-120` | Concurrent writers lose rows; no locking, no append-only semantics | 2 |

## B. Offline

| ID | Defect | Where | Consequence | Phase |
|---|---|---|---|---|
| D-13 | Four runtime CDN dependencies: Google Fonts (Inter), EB Garamond, lightweight-charts, Chart.js | `koers.html:10-11`, `bar.html:11-12`, `theme.js:116-121`, and 3 more pages | **At an offline event today: fonts fall back and the bar revenue chart throws `Chart is not defined`** | 4 |
| D-14 | Theme, branding and candle interval stored in `localStorage` | `theme.js`, `settings.html:614` vs `koers.html:293` | The admin configures branding on their laptop; **the big screen shows defaults** | 4 |

## C. Correctness

| ID | Defect | Where | Consequence | Phase |
|---|---|---|---|---|
| D-15 | Market event carries no end time; cleared only on the next broadcast | `api.py:773` | A 30-second crash overlay can persist up to **10 minutes** | 3 |
| D-16 | News level case mismatch — select emits `Danger`, CSS keys on `.danger` | `manipulation.html:143` vs `koers.html:66` | News colouring silently fails. **Migration must normalise historical rows** | 2 |
| D-17 | No WebSocket liveness check on any page | all pages | Half-open socket freezes the big screen silently on a stale price | 4 |
| D-18 | `GET /state` advances the engine and rewrites globals | `api.py:278-281` | A read endpoint with write side effects; the display page's polling changes bar prices | 3 |
| D-19 | Theme editor exposes only 13 of the theme's tokens (21 in this register's first count; 24 in v2's manifest, `app/runtime/theme.py`) | `settings.html:428-442` | Custom themes look half-applied | 6 |
| D-20 | `p0_total` / `p0_per_drink` are computed from `BAR_PRICE`, not `p0` | `api.py:770` → `persistence.py:126` | A lie in the money reporting | 7 |
| D-21 | `calibrate_s0_to_p0` anchors to current `y`, not `p0` | `engine.py:38-41` | Name lies about behaviour | 1 — **Resolved (Phase 1 T2):** renamed `anchor_s0_to_current_y`, maths unchanged, docstring says why ([exchange/spec.py](../../exchange/spec.py)) |
| D-22 | Idle gate uses `refresh_minutes`, not `idle_decay_minutes` | `engine.py:239` | The setting labelled as the threshold is not the gate | 1 — **Resolved (Phase 1 T6):** kept as v1, documented on `apply_idle` ([exchange/steps.py](../../exchange/steps.py)) and pinned by `test_d22_idle_fires_on_the_refresh_boundary_not_the_idle_threshold` ([tests/engine/test_steps_idle_brownian.py](../../tests/engine/test_steps_idle_brownian.py)) |
| D-23 | `flow_ema` only updates on order and never decays | `api.py:325` | Volatility amplification stays frozen after a quiet spell | 1 — **Resolved by decision (Phase 1 T10):** kept as v1, see [ADR 0012](../adr/0012-flow-ema-keeps-v1-semantics.md); moved into `apply_orders` (T4), pinned by `test_d23_flow_ema_is_unchanged_by_idle_and_brownian` (T6) |
| D-24 | Index-based drink identity; no duplicate-name check | `api.py:595-646` | A duplicate name corrupts every name→index map | 2 |
| D-25 | Inconsistent HTML escaping; drink names interpolated into `innerHTML` | `koers.html:462`, `settings.html:633`, `manipulation.html:383-386` | Injection via drink name | 4 |
| D-26 | `home.html` health strip references DOM that does not exist | `home.html:110-151` | Throws uncaught on every load | 6 |
| D-27 | `/shutdown` requires `X-Admin-Token` which the UI never sends | `settings.html:762` vs `api.py:565-570` | The button always 401s | v1 hotfix |
| D-28 | Three price tracks treated as one; history dedupes on the display track | `engine.py:370-375` | A tile can show a stale price while its chart has moved; the client's version token freezes when flat | 3 |
| D-29 | `.svg` accepted as an upload and served from the session's origin | `api.py:216` | Stored XSS | 6 |

## D. Performance

| ID | Defect | Where | Consequence | Phase |
|---|---|---|---|---|
| D-30 | Entire earnings xlsx re-read and re-aggregated on **every broadcast** | `persistence.py:126-190` via `api.py:770` | O(rows) synchronous disk read per WebSocket broadcast | 2 |
| D-31 | `earnings.series` — one entry per sale — rebroadcast in full every 12 s | `persistence.py:161` | Grows linearly all night; **the largest payload item by the end of an event** | 3 |
| D-32 | Full history window rebroadcast on every tick | `api.py:748` | Tens of kB per client per tick | 3 |
| D-33 | Five broadcast fields no client reads | `api.py:750-774` | Dead weight (*but see note below*) | 3 |
| D-34 | `broadcast` awaits each send serially | `api.py:254-267` | One slow client stalls every other client **and the ticker** | 3 |
| D-35 | All file I/O synchronous inside async handlers, under the lock | throughout `persistence.py` | Event loop stalls grow with the workbook | 2 |
| D-36 | Any client can force an engine advance via the WS string `"state"` | `api.py:864` | Trivial denial-of-service | 3 |

> **Note on D-33.** Two of the "unread" fields are not actually unread: `revenue_per_drink`
> is served by `/financials` (`api.py:296`), and `prices_disp` is read by the candle chart
> (`koers.html:369`). Verify against real consumers before dropping anything.

## E. Security — fixed in the v1 hotfix

Closed ahead of the rebuild, see [ADR 0007](../adr/0007-v1-authorization-hotfix.md).
Listed because v2 must not reintroduce them.

| ID | Defect | Consequence |
|---|---|---|
| D-37 | **No API-level authorization on any endpoint** | Anyone reachable could `POST /reset` and wipe a live event |
| D-38 | `/static` mount served every admin page unauthenticated | Page RBAC was decorative |
| D-39 | `JWT_SECRET` fell back to a per-process random value | Every restart logged out every bar tablet |
| D-40 | Session cookie not `Secure` | — |
| D-41 | `allow_origins=["*"]` with an ad-hoc CSRF middleware whose stated premise is wrong | — |
| D-42 | Access keys stored in plaintext and committed to git | **Rotate them; they remain in history** |
| D-43 | No `.dockerignore`; `COPY . .` copied the image tarball into the image | 1.65 GB image for an 814 kB app |

## F. Found while specifying Phase 6

Found by the Phase 6 spec's audit of v1's admin surface (2026-10-06). Line numbers are
against `legacy/v1/` as it stands now, after the ADR 0007 hotfix. Some older rows above
(D-02's `api.py:599-643`, now `:635-686`; D-29's `api.py:216`, now `:246-260`) predate the
hotfix.

| ID | Defect | Where | Consequence | Phase |
|---|---|---|---|---|
| D-44 | `POST /config` allows the bar role | `api.py:404` | A bar key can rewrite every bound, coefficient and engine scalar; only the `/settings` *page* was admin-gated | 6 |
| D-45 | `/config` mutates bounds before the retarget, and retargets on every save | `api.py:409-419`, `:453` | Changing a bound **rescales every price** instead of holding it; even an idle-only save snaps `y` and discards drift | 6 |
| D-46 | Price-jump form coerces with `+""` | `manipulation.html:348-351` | An empty target jumps the drink to `p_min` | 6 |
| D-47 | Upload size checked after reading the whole body | `api.py:254-256` | Any authenticated admin request can make the server buffer an unbounded body | 6 |
| D-48 | Theme image→slot mapping kept in `localStorage['theme-images']` | `theme.js:150,215` | Uploaded logo, background and promo tile show only in the admin's own browser, never on the big screen | 6 |

### Phase 6 evidence

Each defect Phase 6 fixes, the acceptance criteria that pin it
([phase-6-admin.md](phase-6-admin.md)), and the tasks whose tests are its evidence
([plan](../plans/phase-6-admin.md)):

| ID | ACs | Evidence tasks |
|---|---|---|
| D-02 | AC14, AC15 | T2, T3 (engine), T12 (add), T14 (remove) |
| D-03 | AC1, AC2 | T28 (the gate, written first as a failing test); T10, T13, T21, T23, T25, T34 |
| D-04 | AC4 | T12, T26 |
| D-19 | AC29, AC30 | T17, T30 |
| D-26 | AC41 | T16, T35, T38 |
| D-29 | AC31, AC32 | T18, T31 |
| D-44 | AC7 | T8–T18 (authorization-matrix rows), T33, T34 |
| D-45 | AC8, AC9 | T3, T11, T13 |
| D-46 | AC6 | T6, T33 |
| D-47 | AC33 | T18, T31 |
| D-48 | AC35 | T19, T38 |

## Deliberately not treated as defects

Two items surfaced in the audit that, on reflection, should not be "fixed":

**`market_event === "mid"` renders no visual** (`koers.html:583-593`). "Terug naar start" is
a correction, not a spectacle, and the server already writes a news item for it. v2 renders a
calm banner rather than inventing a third pulsing overlay.

**`home.html`'s dead KPI strip** should be *restored as a real feature* rather than deleted.
Live connection health driven by the shared WebSocket state is genuinely useful mid-event —
"is the big screen still connected?" — whereas a grid of four links is not.
