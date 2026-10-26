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
| 13 | Scale? | **Single association, many borrels** | No tenant dimension; schema structured so one additive migration could add it. *Amended by B-05: one association per deployment (Addendum).* | — | MB |

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
| Deploys | n/a | Manual: the `deploy` workflow, dispatched with a SHA (Phase 8 SD6) |

*Amended in Phase 8.* Merging to `main` builds, checks and pushes one image to GHCR by full
commit SHA, and deploys nothing, so a merge mid-borrel cannot redeploy a live event (ADR 0009).
Render runs that image; the `deploy` workflow takes a SHA, refuses one that is not in GHCR,
calls Render's deploy hook, and smoke-tests the result. The event laptop runs the same image
from an offline bundle under `APP_ENV=venue`: plain-HTTP session cookie, API docs hidden, no
proxy trusted. It sits behind a dedicated travel router with no uplink and a fixed address for
the laptop (Phase 8 SD1, SD2). `production` still refuses an insecure cookie.

## 4. Regions and residency

Render EU (Frankfurt). Dutch student association; no residency requirement beyond keeping
personal data in the EU. Note the app stores no personal data — orders are anonymous.
*Amended by B-05: one name per player wallet (Addendum).*
*Amended by B-06: a wallet's purchases are linked to its name while it exists (Addendum).*

## 5. Naming and tags

Not applicable at this scale. Render service names: `borrelbeurs-web`, `borrelbeurs-db`.

## 6. Total estimate

prod $0–7/mo (Render free tier plus Postgres; the free Postgres instance expires after 90
days, so the $7 paid tier is the realistic steady state). Local $0.

## 7. Explicitly deferred

| Deferred | Trigger that would change it |
|---|---|
| Multi-tenant / other associations | A second association asks to use it. *Amended by B-05: it gets its own deployment; a tenant inside one stays deferred (Addendum).* |
| Entra or hosted identity | Accounts need to persist across events, or an audit trail per person is required. *Amended by B-05: a wallet persists, but is no account (Addendum).* |
| Object storage for uploads | Uploads exceed a few tens of MB, or the offline requirement is dropped |
| Horizontal scale | Measured contention, which fifty phones in one room will not produce |
| Admin action audit log | Considered and not selected; `run_config_revision` gives most of the value |
| Redis / queue / search | A measured problem Postgres cannot solve |

## 8. Open risks

| Risk | Impact | Mitigation | Owner |
|---|---|---|---|
| Pricing maths changes silently during the engine refactor | Prices misbehave at a live borrel; nobody notices until it is too late | Golden fixtures captured from v1 *before* refactoring, live config first. Phase 1 gate | MB |
| Render's free Postgres expires at 90 days | Data loss | Move to the paid tier before the first real event, or keep the offline deployment authoritative. Tiers are the human's cost decision (Phase 8 SD10): a paid Starter web service and paid Postgres before any live borrel on Render | MB |
| Postgres image absent from the local store at an offline venue | `docker compose up` fails at the event | Bundle both images in the `docker save` workflow; rehearse the offline boot | MB |
| Venue laptop clock skew | Tick scheduling misbehaves | Schedule on monotonic time, stamp with wall time, clamp catch-up ([ADR 0003](0003-single-writer-owns-time.md)) | MB |
| v1 access keys remain in git history | Old keys usable until rotated | Rotate keys; fresh repo leaves the history behind | MB |

## Addendum (B-05, 2026-10-25)

Date: 2026-10-25

Player wallets (B-05 SD2, SD5, SD26) change three things this record states. The owner
approved the amendment at the B-05 interview (Q3, Q9c). The original text above stands as it
was decided; the marks beside it point here.

- **Decision 13, scale: one association per deployment.** Each association that uses the app
  gets its own deployment and its own Postgres, set up by the owner, so a wallet of one
  association cannot exist in another's database. A tenant dimension inside one deployment is
  still deferred: there is no tenant table and no tenant column. The §7 row "Multi-tenant /
  other associations" is answered the same way: a second association gets a second deployment.
- **§4, personal data: one name per player wallet.** The app now stores one free-text name per
  wallet, chosen by the player (1–40 characters), and nothing else that identifies a person.
  Orders stay anonymous. *Amended by B-06: a paid order is linked to its wallet's name while
  the wallet exists (Addendum, B-06).* A name goes with its wallet: deleted by the player or by admin, or by
  the automatic clean-up — a wallet never topped up within the unfunded period (default 30
  days), or with no ledger entry for the inactivity period (default 12 months). A deleted
  wallet's row keeps only its ledger; its name, codes and cookie hash are blanked
  (`wallet_deleted_check`). Wallets are not in the xlsx export, so final exports, which are
  never pruned, hold no names.
- **§7, "Entra or hosted identity": the first trigger is answered without it.** A wallet
  persists across borrels, but it is a cookie on the phone and a name, not an account with a
  login: no email, no password, no recovery. A lost phone means signing up again and the kassa
  moving the balance. The second trigger, an audit trail per person, still stands.

## Addendum (B-06, 2026-10-26)

Date: 2026-10-26

Paying at the bar from a wallet (B-06 SD10) changes one thing this record states. The owner
approved the amendment at the B-06 interview (Q13). The original text above, and B-05's
addendum, stand as they were decided; the marks beside them point here.

- **§4, personal data: a wallet's purchases are linked to its name while the wallet exists.**
  A `payment` entry names the order it paid, so the bar's and the kassa's refund lists can show
  "2× Bier, 1× Wijn — €8,40 om 21:14" beside the wallet's name. This replaces B-05's "Orders
  stay anonymous.": an order paid from a wallet is linked to that wallet's name for as long as
  the wallet exists. An order booked without a wallet stays anonymous. The link goes when
  either end goes: deleting the wallet blanks its name (B-05 `wallet_deleted_check`), so its
  payments are anonymous again; deleting the run sets the payment's order and run to NULL
  (`ON DELETE SET NULL`), so it keeps its amount and time and loses only the drinks. Wallets,
  names and payments stay out of the xlsx export and `/analytics`, so final exports, which are
  never pruned, still hold no names.
