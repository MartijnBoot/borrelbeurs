# SDR: BorrelBeurs v2

Date: 2026-09-12 · Tech owner: Martijn Boot · Product owner: Martijn Boot · Status: Approved

## 1. What we are building

A rebuild of BorrelBeurs, the drink stock exchange used at student borrels, as a
React/TypeScript frontend on a restructured FastAPI backend with PostgreSQL as the durable
record. v1 works but loses all price state on restart, keeps money in an incrementally
appended xlsx, and has no authorization on any API endpoint. First release is feature
parity with v1 plus durability, authorization, and cross-event analytics.

## 2. Decisions

| # | Question | Decision | Reason | Est. cost/mo | Owner |
|---|---|---|---|---|---|
| 1 | Database? | **Yes — PostgreSQL** | Orders are money and must survive a restart; cross-event analytics needs queryable history | Render free tier → $7 | MB |
| 2 | Hosting? | **Render.com, one Docker container** | Simplest containerised host; the app must also run offline via Compose | $0–7 | MB |
| 3 | Auth? | **Key-based, hardened in-house** | Bar volunteers type a short code on a shared phone mid-party. Entra is unusable there. Hashing uses argon2, a real library | £0 | MB |
| 4 | File storage? | **In Postgres** (deviation) | Object storage needs internet; the event laptop has none. Handful of files <5 MB | £0 | MB |
| 5 | Cache / queue / search? | **No** | No measured need | — | MB |
| 6 | Background jobs? | **In-process asyncio task** | One ticker and one xlsx export worker; a separate jobs service is unwarranted | £0 | MB |
| 7 | Email? | **No** | Nothing to send | — | MB |
| 8 | Observability? | Structured logs + `/healthz`, `/readyz` | Render gives log aggregation; App Insights is Azure-specific and unavailable offline | £0 | MB |
| 9 | Feature flags? | **No** | Single operator, single deployment, no progressive rollout | — | MB |
| 10 | WAF / CDN? | **No** | Not a public product; a borrel is a closed audience | — | MB |
| 11 | Backend language? | **Python / FastAPI retained** | The numpy pricing engine is the product; porting it is the highest-risk work available and buys nothing. FastAPI is an approved swap in the reference stack | — | MB |
| 12 | Repo? | **Fresh repository** | Current history carries ~600 MB of image tarballs (342 MB pack) and real access keys | — | MB |
| 13 | Scale? | **Single association, many borrels** | No tenant dimension; schema structured so one additive migration could add it | — | MB |

## 3. Environments

**local** and **prod** only. No shared dev environment: the operator is one person, the
audience is a closed event, and a third environment would be drift and cost for no
reviewer. The offline laptop *is* the pre-production rehearsal — a full mock borrel is a
go-live gate (see [plans/rebuild-route.md](../plans/rebuild-route.md), Phase 8).

| | LOCAL | PROD |
|---|---|---|
| Purpose | Development and the event laptop | Hosted instance |
| Data | Seeded / real event data | Real |
| DB | Docker Postgres | Render managed Postgres, same major version |
| Compute | Docker Compose | Render, **1 instance** (see [ADR 0003](0003-single-writer-owns-time.md)) |
| Secrets | `.env.local` | Render environment variables |
| Deploys | n/a | On merge to main |

## 4. Regions and residency

Render EU (Frankfurt). Dutch student association; no residency requirement beyond keeping
personal data in the EU. Note the app stores no personal data — orders are anonymous.

## 5. Naming and tags

Not applicable at this scale. Render service names: `borrelbeurs-web`, `borrelbeurs-db`.

## 6. Total estimate

prod $0–7/mo (Render free tier plus Postgres; the free Postgres instance expires after 90
days, so the $7 paid tier is the realistic steady state). Local $0.

## 7. Explicitly deferred

| Deferred | Trigger that would change it |
|---|---|
| Multi-tenant / other associations | A second association asks to use it |
| Entra or hosted identity | Accounts need to persist across events, or an audit trail per person is required |
| Object storage for uploads | Uploads exceed a few tens of MB, or the offline requirement is dropped |
| Horizontal scale | Measured contention, which fifty phones in one room will not produce |
| Admin action audit log | Considered and not selected; `run_config_revision` gives most of the value |
| Redis / queue / search | A measured problem Postgres cannot solve |

## 8. Open risks

| Risk | Impact | Mitigation | Owner |
|---|---|---|---|
| Pricing maths changes silently during the engine refactor | Prices misbehave at a live borrel; nobody notices until it is too late | Golden fixtures captured from v1 *before* refactoring, live config first. Phase 1 gate | MB |
| Render's free Postgres expires at 90 days | Data loss | Move to the paid tier before the first real event, or keep the offline deployment authoritative | MB |
| Postgres image absent from the local store at an offline venue | `docker compose up` fails at the event | Bundle both images in the `docker save` workflow; rehearse the offline boot | MB |
| Venue laptop clock skew | Tick scheduling misbehaves | Schedule on monotonic time, stamp with wall time, clamp catch-up ([ADR 0003](0003-single-writer-owns-time.md)) | MB |
| v1 access keys remain in git history | Old keys usable until rotated | Rotate keys; fresh repo leaves the history behind | MB |
