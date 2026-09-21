# MvR Way of Working (V1.1)

## 0 How to use this document

This is the team's operating manual. It covers five linked stages, in order:

  --------------------------------------------------------------------------------------------------------------------------------------------
  **STAGE**                         **WHAT IT ANSWERS**                                           **OUTPUT ARTIFACT**
  --------------------------------- ------------------------------------------------------------- --------------------------------------------
  **1. Setup** (Phase 0)            Do we need a DB? Hosting? Auth? What does it cost?            Setup Decision Record (SDR)

  **2. AI** (Phase 1)               How we use AI so it produces quality, not just volume         SPEC.md, PLAN.md, review evidence

  **3. Development** (Phase 2--3)   Structure, standards, local environment, Azure architecture   Working repo + provisioned dev environment

  **4. Deployment** (Phase 4--6)    Git, branching, CI, containers, feedback loops                Green pipeline, tested build

  **5. Production** (Phase 7--8)    Is it valid to go live, and how we operate it                 Go-live sign-off, running product
  --------------------------------------------------------------------------------------------------------------------------------------------

**Reference stack.** The practices are stack-agnostic; the examples assume:

-   **Frontend:** TypeScript / React (Next.js) --- swap: Vue, Angular, Blazor

-   **Backend:** TypeScript (NestJS or Fastify) --- swap: .NET 8+, Python (FastAPI)

-   **Data:** Azure Database for PostgreSQL Flexible Server --- swap: Azure SQL

-   **Runtime:** Docker → Azure Container Apps

-   **Source + CI:** GitHub + GitHub Actions

-   **Infra:** Bicep (Azure-native IaC) --- swap: Terraform

-   **AI:** an agentic coding tool in VS Code (Claude Code, or equivalent)

Where a rule is stack-specific it is marked *(stack-specific)*. Everything else applies regardless.

## 1 The 14 non-negotiables

If someone reads only one page, it is this one.

1.  **No code before a spec.** Every unit of work starts as written intent with acceptance criteria.

2.  **No implementation before an approved plan.** The plan is audited by a human against the spec.

3.  **Build in sections.** One vertical slice at a time. A section is only "in" when it passes the Section Definition of Done (§4.6).

4.  **The AI must have a check it can run.** Tests, a build, a script, a screenshot diff. If you cannot verify it, do not ship it.

5.  **Evidence, not assertions.** "Tests pass" is not acceptable; the test output is.

6.  **Fresh eyes review.** The context that wrote the code is not the only context that reviews it.

7.  **AI never holds production credentials.** Agents work against local and dev only. Production is changed by CI, using federated identity.

8.  **Secrets never live in the repo.** .env.example is committed; real values are local-only or in Key Vault.

9.  **Every environment is created by the same IaC.** One template, one parameter file per environment. Never hand-build a resource.

10. \*\*main is always deployable.\*\* Work happens on short-lived feature branches, merged by PR with passing gates.

11. **Immutable, scanned, non-root containers.** Tagged by git SHA. Never latest in production.

12. **Nothing reaches real users un-gated.** Un-validated products sit behind credentials; new features sit behind flags.

13. **A rollback that has not been tested does not exist.** Prove it before go-live.

14. **Feedback closes the loop.** User feedback re-enters as a spec, not as a hotfix.

## 2 Principles: from vibe coding to engineered delivery

Vibe coding --- loosely prompting an agent and shipping what comes back --- is legitimate for throwaway prototypes and spikes. It is not how we ship. The failure mode is not slow generation; it is **drift**: confident, plausible code that quietly solves the wrong problem and decays as the project grows.

  --------------------------------------------------------------------------------------------
  **VIBE CODING**                **OUR WAY OF WORKING**
  ------------------------------ -------------------------------------------------------------
  Prompt → code → hope           Spec → plan → audit → section → verify → review → integrate

  Intent lives in chat history   Intent lives in docs/specs/\*.md, versioned in git

  "It looks right"             A check returns pass/fail

  One long session               Short scoped sessions, cleared between tasks

  Reviewer = the author          Reviewer = fresh context + a human

  Speed measured in lines        Speed measured in shipped, non-reverted increments
  --------------------------------------------------------------------------------------------

Three ideas do most of the work:

-   **The spec is the highest-leverage artifact a human produces.** When the agent writes most of the code, precision at the intent layer is where quality is decided.

-   **Context is the scarce resource.** Agent quality degrades as its context fills. Scope narrowly, delegate research, clear often.

-   **Code is still the source of truth; tests are the enforcer.** We are spec-*anchored*, not spec-as-source. We do not regenerate the app from Markdown.

**Adopt in phases.** Expect a temporary dip in throughput while the team learns the loop. Roll out on one product, with two or three developers, before making it standard.

**PHASE 0**

# SETUP (before anything is built)

Nothing is provisioned and no feature code is written until Phase 0 is signed off. Target: half a day for a small product, two days for something substantial.

## 3.1 The Setup Decision Record (SDR)

Create docs/adr/0001-setup-decision-record.md from the template in Appendix A. It is a table of explicit decisions, each with a reason, a cost and an owner. Its purpose is to stop the two most expensive mistakes: adding infrastructure we do not need, and discovering three weeks in that we needed something we skipped.

Ask each question in order. **Default answer is "no" --- the burden of proof is on adding a component.**

### Question 1 --- Do we need a database?

  ---------------------------------------------------------------------------------------------------
  **SIGNAL**                                            **DECISION**
  ----------------------------------------------------- ---------------------------------------------
  Users create/modify data that must survive a deploy   **Yes** --- managed relational DB

  Content changes but only editors change it            Consider headless CMS or files in git first

  Only configuration and feature flags                  No DB. Config in env + a flag service

  Purely presentational / marketing                     No DB. Azure Static Web Apps
  ---------------------------------------------------------------------------------------------------

If yes: **Azure Database for PostgreSQL Flexible Server** is the default. Reasons: managed backups and patching, point-in-time restore, Microsoft Entra authentication so the app can connect with a managed identity instead of a password, built-in PgBouncer connection pooling, and private networking. Choose Azure SQL instead if the team's expertise or an existing estate points that way.

**Is it optimal?** Check these before committing:

-   One relational database per product, not per service, until there is a measured reason to split.

-   Do **not** add Redis, a queue, a search index or a NoSQL store in Phase 0. Add each only when a specific measured problem exists. Postgres does caching (materialised views), queueing (SKIP LOCKED), JSON documents and full-text search well enough to get to real traffic.

-   Blob/file storage is **not** a database question --- files go to Azure Blob Storage, never into the DB and never onto container disk (containers are ephemeral).

-   Sizing: dev on **Burstable** (B1ms/B2s), production on **General Purpose**. Storage grows but cannot shrink --- start modest.

### Question 2 --- Where does it run?

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **OPTION**                             **USE WHEN**                                                                              **NOTES**
  -------------------------------------- ----------------------------------------------------------------------------------------- --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Azure Container Apps** *(default)*   Anything containerised; APIs, SSR web apps, microservices, jobs                           Serverless Kubernetes without touching kubectl. Scale-to-zero for dev. Built-in revisions + traffic splitting = canary and instant rollback.

  Azure App Service                      Simple code-deploy web app, no container, no native dependencies                          Mature PaaS, deployment slots. On Linux it runs a minimal Microsoft-managed container: native modules (e.g. sharp, anything via node-gyp) and custom system libraries are a recurring source of pain. Production needs Standard minimum, Premium v3 realistically.

  Azure Static Web Apps                  Pure static site or SPA with no server runtime                                            Free tier, global CDN, GitHub-native deploys.

  Azure Kubernetes Service               You genuinely need the Kubernetes control plane, Helm assets or multi-cloud portability   Highest operational load. Not a starting point.
  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

Default: **Container Apps for the API and the SSR web app; Static Web Apps for a marketing site.** Choose the option with the lowest operational load that meets the requirement, not the most capable one.

### Question 3 --- Authentication and identity

**Buy, do not build.** Never hand-roll password hashing, session management or token issuance.

-   Internal/staff app → **Microsoft Entra ID**

-   Customer-facing → **Microsoft Entra External ID**, or Auth0/Clerk if a richer flow library is needed

-   Service-to-service inside Azure → **managed identity**, never keys

### Question 4 --- What else, honestly?

Tick only what has a named requirement behind it. Everything ticked appears in the IaC and in the cost estimate.

  -------------------------------------------------------------------------------------------------------------------------
  **COMPONENT**               **AZURE SERVICE**                         **ADD IT WHEN**
  --------------------------- ----------------------------------------- ---------------------------------------------------
  Secrets                     Key Vault                                 Always (production)

  Container registry          Azure Container Registry                  Always (containerised)

  Files/uploads               Blob Storage                              Users upload or we generate files

  Background/scheduled work   Container Apps Jobs                       Work outside a request cycle

  Email                       Azure Communication Services / SendGrid   Transactional email needed

  Observability               Application Insights + Log Analytics      Always

  Front door / WAF            Azure Front Door                          Public product needing WAF, caching, multi-region

  Feature flags               Azure App Configuration, or a flag SaaS   From the first production release

  CDN                         Front Door / Static Web Apps built-in     Heavy static assets
  -------------------------------------------------------------------------------------------------------------------------

### Question 5 --- Environments

Standard is **three**: local, dev (shared, cloud), prod. Add uat/staging only if a client contractually signs off in a separate environment, or regulation demands it. More environments means more drift and more cost.

  -------------------------------------------------------------------------------------------------------------------------------------------
                    **LOCAL**           **DEV**                                         **PROD**
  ----------------- ------------------- ----------------------------------------------- -----------------------------------------------------
  Purpose           Fast inner loop     Integration, internal + external testing        Real users

  Data              Seeded, synthetic   Synthetic only --- **never production data**    Real

  DB tier           Docker Postgres     Burstable, public access + firewall             General Purpose, private endpoint, HA if required

  Compute           Docker Compose      Container Apps, scale-to-zero, min replicas 0   Container Apps, min replicas ≥2, autoscale

  Secrets           .env.local          Key Vault (dev vault)                           Key Vault (prod vault), separate subscription or RG

  Deploys           n/a                 Automatic on merge to main                      Manual approval, tagged release

  Domain            localhost           dev.example.com                                 example.com / app.example.com
  -------------------------------------------------------------------------------------------------------------------------------------------

**Rule:** dev and prod are provisioned from the *same* Bicep template with different parameter files. If you find yourself copying a module folder into dev/ and prod/, stop --- within months you will have two hand-written environments that merely happen to be in git.

### Question 6 --- Cost and ownership

The SDR is not complete without: monthly cost estimate per environment (use the Azure Pricing Calculator), a budget with alerts at 50/80/100%, a named technical owner and a named product owner.

## 3.2 Azure foundation setup (once per product)

Order matters. Steps 1--4 are manual, one-off, done by a lead. Everything after step 5 is code.

1.  **Subscription and resource groups.** One RG per environment: rg-\<workload\>-\<env\>-\<region\>. Separate subscriptions for prod vs non-prod if governance requires it.

2.  **Naming convention and tags.** Fix these now (Appendix I). Every resource carries tags: env, workload, owner, costCentre, managedBy=bicep.

3.  **Entra app registrations + federated credentials** for GitHub OIDC --- one identity per environment (§7.4). Grant each the least privilege it needs, scoped to its resource group.

4.  **DNS zone.** Delegate the domain to Azure DNS (or keep the registrar's DNS and manage records there --- decide once, write it down).

5.  **Write the IaC** (infra/), then deploy dev from a branch, then prod. Never click a resource into existence in the portal; if you must, retrofit it into Bicep the same week.

6.  **Key Vault + managed identities.** Each app gets a user-assigned managed identity with Key Vault Secrets User on its environment's vault and AcrPull on the registry.

7.  **Budgets, alerts, diagnostic settings** shipped as part of the same IaC.

## 3.3 The .env standard

Environment configuration is a contract. Treat it like one.

**Rules**

1.  .env.example is **committed** and lists every variable with a comment and a safe placeholder. It is the canonical list.

2.  .env, .env.local, .env.\*.local are **git-ignored**. Never commit real values --- not even for dev.

3.  Names are SCREAMING_SNAKE_CASE, grouped by prefix: DATABASE\_\*, AUTH\_\*, AZURE\_\*, FEATURE\_\*.

4.  Anything prefixed NEXT_PUBLIC\_ / VITE\_ is **shipped to the browser**. No secret may ever carry that prefix. *(stack-specific)*

5.  **Validate at boot and fail fast.** A single config module parses process.env through a schema (zod/envalid) and throws on start-up if anything is missing or malformed. No process.env reads anywhere else in the codebase.

6.  Non-secret configuration (log level, feature defaults, URLs) lives in the IaC as plain environment variables. **Secrets** live in Key Vault and are injected as secret references --- the app never sees the vault, only the resolved variable.

7.  Adding a variable is a three-file change: .env.example, the config schema, and the Bicep parameter/secret. A PR that adds one without the other two fails review.

8.  Rotation: every secret has an owner and a rotation interval recorded in the SDR. Prefer managed identity so there is no secret to rotate at all.

See Appendix B for the standard .env.example.

## 3.4 Phase 0 exit criteria

> ❑ SDR completed, reviewed and merged
>
> ❑ Cost estimate approved; budget + alerts live
>
> ❑ Naming convention and tag policy documented
>
> ❑ Resource groups, DNS zone, Entra registrations, federated credentials in place
>
> ❑ infra/ deploys dev end-to-end from CI
>
> ❑ .env.example + config schema exist and the app fails fast on missing config
>
> ❑ Repo initialised with structure (§5.2), CLAUDE.md, branch protection, PR template

**PHASE 1**

# THE AI WAY OF WORKING

The goal is not to get code out of the model. It is to get **a correct, reviewable, integrable increment**, repeatedly, with the human doing the thinking that only a human can do.

## 4.1 Which model for what

Model choice matters less than the loop around it, but the loop is cheaper when the tiers are used deliberately.

  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **TASK CLASS**                                                     **TIER**                           **WHY**
  ------------------------------------------------------------------ ---------------------------------- ----------------------------------------------------------------------------
  Architecture, specs, planning, tricky debugging, security review   **Most capable reasoning model**   Errors here propagate into everything downstream. Cheapest place to spend.

  Bulk implementation of an approved plan, tests, refactors          **Mid-tier / fast model**          The plan already carries the thinking. Speed and cost win.

  Mechanical work: renames, formatting, boilerplate, doc strings     **Smallest model**                 No judgement required.

  Review of a diff                                                   **Capable model, fresh context**   Must not be the same session that wrote it.
  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

Rules that hold regardless of model:

-   **Never let the session that wrote the code be its only reviewer.** A fresh context judges the result on its own terms rather than defending the reasoning that produced it.

-   Record which tier is expected for each step in CLAUDE.md so the team is consistent.

-   Re-evaluate the tier mapping when models change --- do not carry a stale mapping for a year.

## 4.2 The loop

Nine steps. Steps 1, 4, 7 and 9 are **human-owned** and cannot be delegated.

> 1\. FRAME (human) → problem, users, constraints, acceptance criteria
>
> 2\. INTERVIEW (AI) → agent interrogates you; produces SPEC.md
>
> 3\. PLAN (AI) → read-only exploration; produces PLAN.md with task list
>
> 4\. AUDIT (human) → verify each task's expected output is what is actually needed
>
> 5\. IMPLEMENT (AI) → ONE section only
>
> 6\. VERIFY (AI) → run the check; produce evidence
>
> 7\. REVIEW (human + fresh AI context) → diff vs SPEC and PLAN
>
> 8\. INTEGRATE (AI) → PR, CI green, merge
>
> 9\. LOG (human) → ADR if a decision was made; prune CLAUDE.md

### Step 1 --- Frame (human)

Write, in your own words, before opening the agent:

-   The problem and who has it

-   What "done" looks like from the user's side

-   Hard constraints (existing patterns to follow, things not to touch, performance/security requirements)

-   What is explicitly **out of scope**

Five minutes here removes hours later.

### Step 2 --- Interview → SPEC.md

Do not write the spec alone; make the agent find the holes. Start a session and ask it to interview you:

> I want to build \[one-line description\]. Interview me in detail. Ask about technical implementation, UI/UX, edge cases, failure modes and trade-offs. Skip obvious questions --- dig into the hard parts I may not have considered. Keep going until we have covered everything, then write a complete spec to docs/specs/\<feature\>.md.

A good spec is **self-contained**: it names the files and interfaces involved, states what is out of scope, lists acceptance criteria in testable form, and ends with an end-to-end verification step that proves the feature works.

Write acceptance criteria in a trigger-response form (EARS-style) so they convert directly into tests:

-   *When* a user submits an invalid email, *the system shall* return 422 with field-level errors.

-   *While* a session is expired, *the system shall* refresh the token once, then redirect to login on failure.

-   *If* the payment provider times out after 5s, *then the system shall* mark the order pending and enqueue a retry.

Bad: "User can log in." Good: "User can log in with email + password; receives a 24h JWT; 5 attempts per minute per IP, then 429; failed attempts are logged without the password."

**Then start a fresh session for planning.** The interview context is noise for implementation.

### Step 3 --- Plan → PLAN.md (read-only)

Use the agent's plan/read-only mode so it explores without editing. Ask for:

-   Files to be created and modified, by path

-   The task breakdown, each task independently implementable and verifiable

-   Data model and migration implications

-   Test plan per acceptance criterion

-   Risks, unknowns, and anything it wants to confirm before starting

-   Explicit out-of-scope list

Skip formal planning only when the change is genuinely small --- a typo, a log line, a rename. **If you could describe the diff in one sentence, skip the plan; otherwise plan.**

### Step 4 --- Audit the plan (human) ← the step teams skip

The plan is a proposal, not an instruction. Read every task and confirm that **the expected output of that task is what the product actually needs.** An agent will happily plan, build and verify the wrong thing to a very high standard.

Audit checklist --- every line must be a yes:

> ❑ Every acceptance criterion in SPEC.md maps to at least one task
>
> ❑ Every task maps back to an acceptance criterion (no orphan work --- this is where scope creep enters)
>
> ❑ The expected output of each task is stated concretely enough to be checked, and is genuinely what we need
>
> ❑ Existing patterns and modules are reused; nothing is being reinvented
>
> ❑ No new third-party dependency is introduced without an explicit approval note
>
> ❑ Data changes are additive/reversible; migration strategy is stated
>
> ❑ Error paths, empty states, permissions and edge cases are tasks, not afterthoughts
>
> ❑ Each task is small enough to review in one sitting
>
> ❑ The verification method for each task is named
>
> ❑ Nothing touches production, secrets, or infrastructure it should not

Edit the plan directly rather than negotiating in chat --- it is faster and the file is the record. Commit PLAN.md alongside the spec; the reviewer will check the diff against it.

### Step 5 --- Implement one section

A **section** is one vertical slice that leaves the system working: schema + API + UI + tests for a single capability. Not "the whole backend".

Sizing guide: reviewable in under 30 minutes --- roughly **≤400 changed lines across ≤10 files**. If the plan produces sections larger than that, split them.

Prompt with the plan as the source of truth:

> Implement task 3 from PLAN.md: \[name\]. Follow the pattern in src/modules/orders/ --- orders.service.ts is the closest example. Write tests for the listed edge cases first, then the implementation. Run the test suite and the type check, and fix failures. Do not change anything outside the files named in the task. If a requirement is ambiguous, stop and ask rather than guessing.

### Step 6 --- Verify: give the agent a check it can run

This is the single highest-leverage practice in the document. An agent stops when the work *looks* done; without a check, "looks done" is the only signal it has, and you become the verification loop.

  -------------------------------------------------------------------------------------
  **CHANGE TYPE**           **THE CHECK**
  ------------------------- -----------------------------------------------------------
  Business logic            Unit tests with the acceptance criteria as cases

  API endpoint              Integration test against a real DB in a container

  UI                        Playwright test, plus a screenshot compared to the design

  Bug fix                   A failing regression test first, then the fix

  Build/config              Build exit code, type check, lint

  Migration                 Apply + rollback against a scratch DB

  Performance               A script asserting a p95 threshold
  -------------------------------------------------------------------------------------

Escalation ladder, cheapest first:

1.  **In the prompt** --- "run the tests and iterate until they pass". Works today, on any task.

2.  **As a session goal** --- the agent keeps working until a stated condition holds.

3.  **As a deterministic hook** --- a script that blocks the turn from ending until the check passes. Use for anything that must happen every time (lint, format, type check).

4.  **As a second opinion** --- a verification subagent, in a fresh context, tries to refute the result.

**Demand evidence.** Require the actual command and its output, not a claim. Reviewing evidence is faster than re-running the verification yourself, and it works for sessions you were not watching.

### Step 7 --- Adversarial review (human + fresh AI context)

Two passes, in this order.

**Pass A --- fresh-context AI review.** In a *new* session or a subagent that sees only the diff and the criteria:

> Review this diff against docs/specs/\<feature\>.md and PLAN.md. Check that every acceptance criterion is implemented, that the listed edge cases have tests, and that nothing outside the task's scope changed. Report gaps that affect correctness or the stated requirements. Do not report style preferences.

Calibration warning: a reviewer asked to find gaps will find some, because that is what it was asked to do. Chasing every finding produces over-engineering --- extra abstraction layers, defensive code, tests for cases that cannot happen. Fix correctness gaps; treat the rest as optional.

**Pass B --- human review of the diff.** Non-delegable. See §7.5 for the checklist, including the AI-specific items.

### Step 8 --- Integrate: the puzzle-piece rule

A section is not "done" when the code exists. It is done when it can be **added to the puzzle** --- merged into main, deployed to dev, and left there without anyone babysitting it. See the Section Definition of Done (§4.6).

### Step 9 --- Log

-   A decision with consequences → an ADR in docs/adr/ (one page: context, decision, alternatives, consequences).

-   A convention the agent got wrong twice → add one line to CLAUDE.md, or better, a hook.

-   A repeated multi-step workflow → a skill file, not a paragraph pasted into every session.

## 4.3 Prompting for quality, not output

Quality is a property of constraints, context and verification --- not of prompt length.

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **DO**                                                                                                                                                 **INSTEAD OF**
  ------------------------------------------------------------------------------------------------------------------------------------------------------ ----------------------------------------------
  "Write a test for foo.ts covering the logged-out case; avoid mocks."                                                                                 "Add tests for foo.ts"

  "Follow the pattern in orders.service.ts; use only libraries already in the project."                                                                "Build an order service"

  "Users report login fails after session timeout. Check src/auth/, especially token refresh. Write a failing test that reproduces it, then fix it."   "Fix the login bug"

  "Fix the root cause; do not suppress the error."                                                                                                     "Make the build pass"

  "Here are the acceptance criteria as test cases. Run them after implementing."                                                                       "Make it work"

  "Simplest solution that satisfies the criteria. No new abstractions unless two callers exist today."                                                 (silence --- you will get a framework)

  "Do not change anything outside these files."                                                                                                        (silence --- you will get a 40-file diff)

  "If requirements are ambiguous, stop and ask."                                                                                                       (silence --- you will get a confident guess)
  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

Standing rules for every implementation prompt:

1.  Name the files and the pattern to follow.

2.  State the acceptance criteria and the check to run.

3.  Forbid new dependencies without approval.

4.  Forbid scope beyond the named task.

5.  Require evidence of verification.

6.  Require it to stop and ask on ambiguity.

Vague prompts still have a place --- "what would you improve in this file?" surfaces things you would not have asked about. Use them for exploration, never for delivery.

## 4.4 Context engineering

Agent quality degrades as context fills. Managing it is a core skill, not housekeeping.

\*\*CLAUDE.md / agent instructions file **--- committed to the repo, loaded every session. Keep it** short\**. For every line ask:* would removing this cause a mistake?\* If not, cut it. A bloated instructions file causes the agent to ignore the rules that matter. Include:

-   Commands it cannot guess (pnpm test:int, pnpm db:migrate)

-   Conventions that differ from language defaults

-   Branch naming and PR etiquette

-   Architectural decisions specific to this project

-   Environment quirks and known gotchas

Exclude: anything discoverable by reading the code, standard language conventions, API documentation (link instead), file-by-file descriptions, and platitudes like "write clean code".

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **SURFACE**                     **USE FOR**                                                                                                  **GUARANTEE**
  ------------------------------- ------------------------------------------------------------------------------------------------------------ ------------------------
  Instructions file (CLAUDE.md)   Always-relevant conventions                                                                                  Advisory

  Skills (SKILL.md)               Occasional domain knowledge and repeatable workflows (release process, incident runbook, migration recipe)   Loaded on demand

  Hooks                           Things that **must** happen every time --- lint after edit, block writes to infra/ or applied migrations     Deterministic

  Subagents                       Research that reads many files; independent review                                                           Isolated context

  Permissions / sandbox           Constraining what the agent may run                                                                          Enforced
  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------

**Session hygiene**

-   Clear context between unrelated tasks. A kitchen-sink session is the most common cause of degraded output.

-   After **two failed corrections on the same issue**, stop correcting. Clear and re-prompt with what you learned. A clean session with a better prompt beats a long session full of failed approaches.

-   Delegate wide exploration to a subagent so the reading does not consume your main context.

-   Never paste secrets, credentials, customer data or PII into a prompt or an instructions file.

-   Parallel sessions are capped by **your review capacity** --- two or three in practice, in separate git worktrees. Unreviewed parallel output is not throughput.

## 4.5 AI as guidance, and the regular checks

The agent is also the fastest way to understand a system. Use it for onboarding and for keeping the codebase honest.

**Guidance uses.** Ask it what you would ask a senior engineer: How does logging work here? How do I add an endpoint? What edge cases does this class handle? Why does this call foo() and not bar()? What would you change about this module? --- This cuts ramp-up time and takes load off senior engineers.

**Regular checks.** AI-assisted codebases accumulate duplication and quiet dead code faster than hand-written ones. Schedule the audits; do not rely on noticing.

  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **CADENCE**           **CHECK**                                                                                                                                                                        **OWNER**
  --------------------- -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- ------------------------
  Every save/edit       Format, lint, type check (via hook)                                                                                                                                              Automated

  Every commit          Unit tests, secret scan                                                                                                                                                          Automated

  Every PR              CI gates + fresh-context AI review + human diff review                                                                                                                           Author + reviewer

  Weekly                Dependency and CVE scan; IaC drift check (what-if); AI-generated code audit --- pick two recently changed modules and review for duplication, dead code, inconsistent patterns   Dev on rota

  Weekly                Prune the instructions file; convert repeatedly-ignored rules into hooks                                                                                                         Tech lead

  Every release         Security review of the diff; cost review; rollback rehearsal                                                                                                                     Tech lead

  Monthly               Restore a backup into a scratch DB; access review; review model/tool tier mapping                                                                                                Tech lead

  Quarterly             Review this document; review the ADR log for decisions now wrong                                                                                                                 Eng lead
  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

**Weekly audit prompt**

> Review src/modules/{a,b} for: logic duplicated elsewhere in the repo, unreachable or unused code, deviations from the patterns in CLAUDE.md, and tests that assert implementation details rather than behaviour. Report findings with file and line references, ranked by impact. Do not fix anything yet.

## 4.6 Section Definition of Done

A section is a puzzle piece. It is only in the puzzle when **all** of these are true:

> ❑ Every acceptance criterion for the section is implemented
>
> ❑ Automated tests cover the criteria and the listed edge cases; the suite passes locally and in CI
>
> ❑ Type check and lint clean; no new warnings
>
> ❑ Error paths, empty states and permission checks handled --- not just the happy path
>
> ❑ No secrets, keys or PII in code, logs or tests
>
> ❑ No new dependency without an approval note in the PR
>
> ❑ Migrations are additive and have been applied and rolled back against a scratch DB
>
> ❑ Fresh-context AI review returned no correctness gaps (or they are fixed)
>
> ❑ A human has read the whole diff
>
> ❑ Docs updated where behaviour changed: README, .env.example, API contract, ADR
>
> ❑ Observability: meaningful logs/metrics for the new path
>
> ❑ Deployed to dev and exercised there by a human
>
> ❑ Feature flagged if it is user-visible and not yet signed off

## 4.7 Known AI failure modes and countermeasures

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **FAILURE MODE**                                    **COUNTERMEASURE**
  --------------------------------------------------- -------------------------------------------------------------------------------------------------------------------------------------
  Drift --- solves a nearby, wrong problem            Spec + plan audit (§4.2, step 4)

  Plausible but wrong; edge cases missed              A runnable check; adversarial fresh-context review

  Silent scope creep --- 30 files changed             "Do not change anything outside these files"; small sections; read the diff

  Invented APIs and hallucinated config               Point at real files and real docs; the build/type check catches most

  Duplicated logic instead of reuse                   Name the module to reuse; weekly duplication audit

  Tests written to pass rather than to test           Reviewer checks the tests, not just the code; require a failing test first for bug fixes

  Over-engineering after a gap-hunting review         Tell reviewers to report only correctness gaps; prefer the simplest solution

  Secrets pasted into code or the instructions file   Secret scanning in CI + pre-commit; never paste real values

  Destructive infrastructure or data actions          Agents never hold prod credentials; hooks block writes to infra/ and applied migrations; least-privilege permissions and sandboxing

  Context rot in long sessions                        Clear between tasks; two-correction rule; subagents for research
  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

**PHASE 2**

# DEVELOPMENT

## 5.1 VS Code baseline

Every developer, same setup. Commit .vscode/extensions.json and .vscode/settings.json so the editor configuration is part of the repo, not folklore.

**Extensions:** the AI agent extension (Claude Code or equivalent) · ESLint · Prettier · EditorConfig · Docker · Bicep · Azure Resources · Azure Container Apps · GitLens · Playwright · Bruno or REST Client · Error Lens · a code-intelligence plugin for the language (gives the agent precise symbol navigation and post-edit error detection).

**Committed settings:** format on save, organise imports on save, ESLint as the fixer, one tab width, LF line endings, files.trimTrailingWhitespace.

**Toolchain pinning:** .nvmrc / global.json / .python-version committed. Same major runtime version locally, in CI and in the container. Lockfile committed and CI installs with \--frozen-lockfile / npm ci.

**Optional but recommended:** a .devcontainer/ so a new developer is productive in one command and the local environment cannot drift.

**Agent configuration in the repo** *(commit all of it)*:

> .claude/
>
> ├─ settings.json \# permissions, hooks
>
> ├─ agents/ \# reviewer, security-reviewer, test-writer subagents
>
> └─ skills/ \# release-process, incident-runbook, migration-recipe
>
> CLAUDE.md \# short, always-loaded conventions

Grant the agent an allow-list of safe commands (pnpm lint, pnpm test, git commit) so routine work is not a click-through, and **deny** anything that touches production, secrets or infra/ without explicit human action. Approving the tenth prompt in a row is not review, it is muscle memory --- configure the permissions instead.

## 5.2 Repository structure

Start with structure. Retrofitting it is one of the more expensive things you can do, and an agent generating files into an unclear tree makes it worse fast.

Two principles: **group by feature, not by technical layer**, and **every feature exposes a public API** (index.ts) --- outside code imports the public surface, never the internals. The test for whether your boundaries hold: pick one feature folder, imagine deleting it, and see how many other places break. If the answer is "many", the boundary is fiction.

> \<repo\>/
>
> ├─ .github/
>
> │ ├─ workflows/ ci.yml, deploy-dev.yml, deploy-prod.yml, nightly-scan.yml
>
> │ ├─ PULL_REQUEST_TEMPLATE.md
>
> │ └─ ISSUE_TEMPLATE/ bug.yml, feedback.yml
>
> ├─ .claude/ agents, skills, hooks, permissions
>
> ├─ .vscode/ settings.json, extensions.json
>
> ├─ apps/
>
> │ ├─ web/ frontend (Next.js)
>
> │ └─ api/ backend service
>
> ├─ packages/
>
> │ ├─ shared/ types, DTOs, validation schemas shared by web + api
>
> │ ├─ ui/ design system primitives
>
> │ └─ config/ eslint, tsconfig, vitest, prettier presets
>
> ├─ infra/
>
> │ ├─ main.bicep
>
> │ ├─ modules/ containerapp.bicep, postgres.bicep, keyvault.bicep, \...
>
> │ └─ params/ dev.bicepparam, prod.bicepparam
>
> ├─ db/
>
> │ ├─ migrations/ timestamped, forward-only
>
> │ └─ seeds/ dev/test seed data only
>
> ├─ docker/
>
> │ ├─ Dockerfile.web
>
> │ └─ Dockerfile.api
>
> ├─ docs/
>
> │ ├─ specs/ one file per feature
>
> │ ├─ adr/ architecture decision records (0001-...)
>
> │ ├─ runbooks/ deploy, rollback, incident, restore
>
> │ └─ gated-sites.md register of credential-gated environments (§9.3)
>
> ├─ scripts/ setup.sh, seed.ts, smoke-test.sh
>
> ├─ tests/e2e/ Playwright, critical journeys only
>
> ├─ docker-compose.yml local only --- never a deployment artifact
>
> ├─ .dockerignore .gitignore .editorconfig .nvmrc
>
> ├─ .env.example
>
> ├─ CLAUDE.md
>
> └─ README.md setup in ≤5 commands

\*\*Inside apps/web/src\* (stack-specific)\*

> app/ routes only --- thin; no business logic
>
> features/
>
> orders/
>
> components/ UI local to this feature
>
> hooks/
>
> api/ data fetching for this feature
>
> model/ types, state, business rules
>
> \_\_tests\_\_/
>
> index.ts ← the ONLY import surface
>
> components/ui/ shared primitives (Button, Modal)
>
> lib/ cross-cutting helpers (http client, formatters)
>
> config/ env schema + parsed config
>
> styles/

**Inside apps/api/src**

> modules/
>
> orders/
>
> orders.controller.ts HTTP only --- parse, authorise, delegate
>
> orders.service.ts business logic
>
> orders.repository.ts data access
>
> orders.schema.ts request/response validation
>
> \_\_tests\_\_/
>
> core/
>
> config/ env schema, fail-fast
>
> logging/ structured logger + correlation id
>
> errors/ error types + global handler
>
> auth/ guards, middleware
>
> db/ client, transactions, migration runner

**Enforced rules** --- these are lint rules, not suggestions:

-   No imports from another feature's internals (eslint-plugin-boundaries or equivalent).

-   Controllers hold no business logic; services hold no HTTP concerns; repositories hold no business rules.

-   No circular dependencies between modules.

-   shared/ is for genuinely shared contracts. If it starts collecting "misc", it has failed --- split it.

-   Folder hierarchy stays shallow. Deep nesting hides things from humans and agents alike.

-   Avoid ambiguous folder names. Define what lib, core, services and utils mean for this repo in CLAUDE.md, or do not use them.

Start as a monorepo only if there is more than one app surface or real shared code. A single app is src/ with the same feature layout --- the structure scales up unchanged when you add apps/.

## 5.3 Coding standards

-   **Formatting and linting are automated and non-negotiable.** No style debate in review; the formatter decides.

-   **Conventional commits**: feat:, fix:, chore:, refactor:, test:, docs:, perf:, build:. Scope where useful: feat(orders): ....

-   **Types at the boundary.** Every external input (HTTP body, query, env, webhook, third-party response) is parsed and validated before use. No any at boundaries.

-   **Errors:** typed error classes, one global handler, never swallow. Log with context and a correlation id; never log secrets, tokens or PII.

-   **Logging:** structured JSON, one line per event, correlation id propagated from the edge through every layer.

-   **No business logic in controllers, components or migrations.**

-   **Dependencies:** adding one requires justification in the PR --- what it does, why not standard library, licence, maintenance status, install size. Prefer removing over adding.

-   **Comments** explain *why*, never *what*.

-   **Feature flags** for anything user-visible that is not yet signed off.

## 5.4 Testing strategy

Tests are how an agent verifies itself. They are load-bearing infrastructure, not paperwork.

  ------------------------------------------------------------------------------------------------------------------------------------------------
  **LAYER**         **SCOPE**                          **SPEED**         **RULE**
  ----------------- ---------------------------------- ----------------- -------------------------------------------------------------------------
  **Unit**          Pure logic, no I/O                 ms                Every branch of business logic; acceptance criteria become cases

  **Integration**   API + real DB in a container       seconds           Every endpoint: happy path, validation failure, auth failure, not-found

  **E2E**           Browser, real stack                minutes           Critical journeys only --- sign-up, core action, payment. Cap at \~10.

  **Contract**      Shared types between web and api   build-time        Types live in packages/shared; a breaking change fails the build

  **Smoke**         Post-deploy against a live URL     seconds           Health, auth, one read, one write. Runs after every deploy.
  ------------------------------------------------------------------------------------------------------------------------------------------------

-   **Coverage is a signal, not a target.** Gaming it produces worthless tests. Watch it, do not gate on a magic number --- except: coverage must not *decrease* in a PR.

-   **Every bug fix begins with a failing test.** No exceptions. This is the main defence against regression in an AI-assisted codebase.

-   Tests must be deterministic. No sleeps, no shared mutable fixtures, no network calls to third parties (record/replay or stub at the boundary).

-   Test data is built by factories, not copy-pasted fixtures.

-   Integration tests run against the same Postgres major version as production, in a container.

## 5.5 Local development

Target: a new developer runs **two commands** and has a working stack with seeded data.

> ./scripts/setup.sh \# copies .env.example → .env.local, installs, starts containers, migrates, seeds
>
> pnpm dev

docker-compose.yml runs Postgres (and any other backing service) locally with pinned versions matching production. It is a **development tool only** --- it is never a deployment artifact and never referenced by the Azure pipeline.

A scripts/check.sh runs the full local gate --- format, lint, types, unit, integration --- in one command. This is the script the agent runs, and the same script CI runs. One definition of "green" means an agent cannot pass locally and fail in CI.

## 5.6 Database workflow

-   **Migrations are code**: versioned, reviewed, forward-only, in db/migrations/, applied in timestamp order.

-   **Never edit an applied migration.** Add a new one. Configure a hook that blocks the agent from writing to already-applied migration files.

-   **Expand → migrate → contract** for anything breaking: add the new column/table (deploy), backfill and dual-write (deploy), switch reads (deploy), remove the old (deploy). Never a destructive change in the same release as the code that depends on it.

-   Migrations run in CI as a **separate job that gates the app deploy** --- never on application start-up, which races across replicas.

-   Every migration must be reversible or explicitly documented as irreversible with a restore plan.

-   Rehearse migrations against a restored copy of production before production.

-   Seeds are for dev and test only. Reference/lookup data belongs in a migration.

-   Connection handling: pool with sensible limits; use PgBouncer (built into Flexible Server) when replica count × pool size approaches the server's connection limit.

-   **Production data never leaves production.** No copies to dev, no dumps on laptops. Need realistic data? Generate it or anonymise through a documented, automated process.

**PHASE 3**

# AZURE ARCHITECTURE AND ENVIRONMENTS

## 6.1 Target architecture

> Internet
>
> │
>
> (optional) Azure Front Door + WAF
>
> │
>
> ┌──────────────┴───────────────┐
>
> │ Container Apps Environment │ rg-\<workload\>-\<env\>-\<region\>
>
> │ ┌────────────┐ ┌───────────┐ │
>
> │ │ ca-\...-web │ │ ca-\...-api│ │ ingress: external (web/api)
>
> │ └─────┬──────┘ └─────┬─────┘ │ revisions + traffic split
>
> │ │ managed identity │
>
> └────────┼──────────────┼────────┘
>
> │ │
>
> ┌─────────────┴──┐ ┌───────┴─────────┐ ┌──────────────┐
>
> │ Key Vault │ │ PostgreSQL │ │ Blob Storage │
>
> │ (secrets) │ │ Flexible Server │ │ (uploads) │
>
> └────────────────┘ └─────────────────┘ └──────────────┘
>
> │
>
> ┌────────┴────────────────┐
>
> │ ACR (images) │
>
> │ App Insights + Log │
>
> │ Analytics (telemetry) │
>
> └─────────────────────────┘

Same diagram for dev and prod. The differences are tiers, replica counts and network exposure --- expressed as parameters, never as different templates.

## 6.2 Infrastructure as code

-   \*\*One main.bicep, one .bicepparam per environment.\*\* If you are copying module folders per environment, you no longer have IaC --- you have hand-written environments checked into git.

-   Modules in infra/modules/, one resource type each, with a documented interface.

-   Names are generated by a shared naming function, not typed by hand (Appendix I).

-   Every deploy runs az deployment group what-if first; the diff is posted to the PR and reviewed. Unexpected changes mean drift --- investigate before applying.

-   Outputs (FQDNs, resource IDs, identity client IDs) feed the deploy job; nothing is hard-coded in workflows.

-   Infrastructure changes go through the same PR process as application code. infra/ requires an additional reviewer.

## 6.3 Identity and secrets --- the golden path

**No passwords, no connection strings, no long-lived keys anywhere in the pipeline or the repo.**

1.  Each app gets a **user-assigned managed identity**.

2.  That identity is granted, by RBAC in Bicep:

-   AcrPull on the container registry

-   Key Vault Secrets User on that environment's Key Vault

-   Microsoft Entra database role on PostgreSQL

-   Storage Blob Data Contributor on its container, if it needs blobs

3.  The app authenticates to Postgres, Blob and Key Vault with its managed identity. Third-party secrets (payment keys, SMTP) sit in Key Vault and are injected as Container Apps **secret references** resolved into environment variables at start-up.

4.  CI authenticates to Azure with **GitHub OIDC / workload identity federation** --- a short-lived token exchanged per run. No client secrets in GitHub, nothing to rotate, nothing to leak.

5.  Keep exactly one break-glass Postgres administrator credential, in Key Vault, with access logged and reviewed. Everything else uses Entra.

6.  Separate vaults per environment. A dev identity must not be able to read a prod secret.

7.  Enable soft-delete and purge protection on Key Vault. Enable diagnostic logging on secret access.

## 6.4 Networking

  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
                           **DEV**                                                                     **PROD**
  ------------------------ --------------------------------------------------------------------------- ---------------------------------------------------------------------------
  Container Apps ingress   External, but access-gated (§9.3)                                           External (or via Front Door)

  PostgreSQL               Public access with strict firewall rules (developer IPs + Azure services)   **Private** --- VNet integration or Private Link. Public access disabled.

  Blob Storage             Key/SAS or identity                                                         Private endpoint, public network access disabled

  Key Vault                Firewall + identity                                                         Firewall + identity, private endpoint if compliance requires
  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

Public access with IP allow-listing is acceptable for development and wrong for production. Decide between VNet integration and Private Link deliberately --- they behave differently for cross-subscription access and network topology; do not pick whichever appeared in the first tutorial you read. Note that a dedicated Container Apps environment inside a VNet carries a fixed monthly cost regardless of how many apps run in it.

## 6.5 Databases: creating and managing

**Creating (via Bicep, per environment)**

-   Postgres major version pinned and identical across local, dev and prod.

-   Tier: dev Burstable (B1ms/B2s); prod General Purpose (start D2ds_v5, scale on evidence).

-   Storage: start small --- it grows but cannot shrink. Enable storage auto-grow, and alert at 80%.

-   Authentication: **both** Entra and PostgreSQL auth enabled; Entra for applications via managed identity, one PostgreSQL admin retained for break-glass. Disable local auth entirely if governance allows.

-   Backups: automated backups default to 7 days retention and can be configured up to 35. **Set prod to 35** with geo-redundancy if the RPO demands it. Automated backups cannot be retained long-term --- if you need archival copies, implement an explicit long-term backup process.

-   High availability: zone-redundant HA for prod only where the SLA justifies the doubled cost. Decide in the SDR, not at go-live.

-   Maintenance window: set explicitly, outside business hours.

-   Connection pooling: enable built-in PgBouncer for prod.

**Managing**

-   Alerts on CPU, memory, storage %, connection count, failed connections, and replication lag if applicable.

-   **Restore drill monthly**: restore to a new server, run the smoke suite, record the elapsed time in the runbook. An untested backup is not a backup.

-   Firewall rules and private endpoints are **not** copied to a restored server --- the runbook must include re-applying them.

-   Query performance: enable Query Store / pg_stat_statements; review the top ten queries at each release.

## 6.6 Domains, DNS and TLS

Naming plan, decided once:

  -------------------------------------------------------------------------
  **PURPOSE**                 **HOST**
  --------------------------- ---------------------------------------------
  Production web              example.com and/or app.example.com

  Production API              api.example.com

  Dev/test                    dev.example.com, api-dev.example.com

  Preview per PR (optional)   pr-123.dev.example.com
  -------------------------------------------------------------------------

**Setup for Azure Container Apps** *(the mechanics that catch people out)*

-   **Subdomain** → CNAME from the subdomain directly to the container app's generated FQDN (\<app\>.\<suffix\>.\<region\>.azurecontainerapps.io), plus a TXT record at asuid.\<subdomain\> holding the domain verification ID.

-   **Apex domain** → an A record pointing at the Container Apps environment's static IP, plus the asuid TXT record. A standard CNAME at the apex is invalid DNS; if your DNS provider cannot do ALIAS/ANAME/CNAME-flattening, use Azure DNS or redirect the apex to www.

-   **Free managed certificates** are issued and auto-renewed by Azure as long as the requirements keep being met. Requirements: HTTP ingress enabled, app publicly reachable by the issuing CA, and --- critically --- **the CNAME must point directly at the container app**. Pointing it at an intermediate CNAME (a proxied Cloudflare record, a traffic manager) blocks both issuance and renewal. If a CAA record exists on the root domain, it must explicitly permit the issuing CA.

-   Allow 15--60 minutes for propagation before assuming failure; verify with dig from outside your network, not just the browser.

-   Lower the TTL to 300s a day *before* a cutover, restore it afterwards.

-   Enforce HTTPS-only, HSTS, and redirect apex ↔ www consistently in one direction.

Record every hostname, its record type, target, and owner in docs/runbooks/dns.md. DNS is the single most common cause of a failed launch and the least documented part of most stacks.

## 6.7 Observability

Non-negotiable before a product goes live:

-   **Application Insights + Log Analytics** wired in via IaC, per environment.

-   **Structured JSON logs** with a correlation id propagated from ingress through every layer. No PII, no secrets.

-   **Health endpoints**: /healthz (process alive) and /readyz (dependencies reachable) wired to Container Apps probes.

-   **Distributed tracing** via OpenTelemetry across web → api → db.

-   **Alerts** (each routed to a named human or channel): availability drop, 5xx rate above threshold, p95 latency regression, unhandled exception spike, DB CPU/storage/connection thresholds, failed deploy, certificate expiry, budget anomaly.

-   **Dashboard** per product: traffic, error rate, latency, DB health, cost-to-date. Reviewed weekly.

-   An external uptime check hitting /healthz from outside Azure --- so you learn about an outage before your users do.

## 6.8 Cost control

-   Dev scales to zero (min replicas 0); Burstable DB tier; short log retention.

-   Auto-delete PR/preview environments on merge or after 7 days.

-   Budgets with alerts at 50/80/100% per environment; a cost anomaly alert.

-   Review spend monthly against the SDR estimate; investigate anything more than 20% out.

-   Log ingestion is a common surprise --- sample high-volume debug logs in production.

**PHASE 4**

# SOURCE CONTROL AND CI

## 7.1 Repository setup

Done once, on day one, before the first feature:

> ❑ Repo created private, with a licence and README
>
> ❑ .gitignore covering .env\*, build output, node_modules, \*.tfstate, IDE files
>
> ❑ main created and protected
>
> ❑ Branch protection: PR required, ≥1 approving review, required status checks, dismiss stale approvals, no force-push, no deletion, linear history
>
> ❑ CODEOWNERS --- infra/ and db/migrations/ require the tech lead
>
> ❑ PR and issue templates
>
> ❑ Secret scanning + push protection enabled
>
> ❑ Dependabot (or Renovate) enabled, grouped weekly PRs
>
> ❑ GitHub Environments dev and prod; prod requires reviewers
>
> ❑ Federated credentials configured per environment (§7.4)
>
> ❑ Commit signing required (recommended)

## 7.2 Branching model

Trunk-based with short-lived branches. Simple, and it keeps main honest.

> main ───────●────────●────────●────────●───────► always deployable, auto-deploys to dev
>
> \\ / \\ /
>
> feature/PROJ-101-order-form feature/PROJ-118-invoice-pdf

  -------------------------------------------------------------------------------------------------------------------------------------------
  **BRANCH**                                      **NAMING**                    **LIFETIME**      **MERGES VIA**
  ----------------------------------------------- ----------------------------- ----------------- -------------------------------------------
  main                                            ---                           permanent         ---

  Feature                                         feature/\<ticket\>-\<slug\>   **≤3 days**       Squash merge + PR

  Fix                                             fix/\<ticket\>-\<slug\>       ≤1 day            Squash merge + PR

  Hotfix                                          hotfix/\<ticket\>-\<slug\>    hours             PR to main, expedited review, still gated

  Release *(only if you must support versions)*   release/x.y                   as needed         cherry-pick
  -------------------------------------------------------------------------------------------------------------------------------------------

Rules:

-   **One section per branch** (§4.6). If the branch has been open more than three days, it is too big --- split it.

-   Rebase on main daily; resolve conflicts in the branch, never in main.

-   Squash merge, so main reads as one commit per section, with the ticket reference in the message.

-   Delete the branch on merge.

-   Tag production releases v\<major\>.\<minor\>.\<patch\> from main.

**Feature branch → test → main** is the loop: push the branch, CI runs the full gate, an optional preview environment is deployed for the branch, a human plus a fresh-context AI review the diff, gates pass, squash merge to main, main auto-deploys to dev, dev is exercised, then production is a deliberate, approved promotion of that exact artifact.

## 7.3 CI pipeline

One workflow on every PR and push to main. Fast checks first so failures surface in under two minutes.

  --------------------------------------------------------------------------------------------------------------------------------------------------
  **\#**                **STAGE**                                                                         **GATE**
  --------------------- --------------------------------------------------------------------------------- ------------------------------------------
  1                     Checkout, restore cache, install with frozen lockfile                             Fail = stop

  2                     Format check, lint, type check                                                    Blocking

  3                     Unit tests                                                                        Blocking

  4                     Build (web + api)                                                                 Blocking

  5                     Integration tests against a Postgres service container, with migrations applied   Blocking

  6                     Secret scan (gitleaks) + dependency audit                                         Blocking on high/critical

  7                     SAST (CodeQL)                                                                     Blocking on high/critical

  8                     bicep build + what-if against dev; post diff to PR                                Blocking on error, informational on diff

  9                     Docker build (both images), tagged \<git-sha\>                                    Blocking

  10                    Image scan (Trivy)                                                                **Fail on CRITICAL/HIGH**

  11                    Generate SBOM, attach as artifact                                                 Blocking

  12                    Push to ACR (only on main)                                                        ---

  13                    Deploy dev → run migrations job → deploy revision → smoke test                    Blocking

  14                    E2E (Playwright) against dev                                                      Blocking

  15                    *(manual approval)* → deploy prod                                                 Gated by GitHub Environment reviewers
  --------------------------------------------------------------------------------------------------------------------------------------------------

Non-negotiables:

-   The pipeline runs the **same script** developers run locally (scripts/check.sh). One definition of green.

-   **Build once, promote the artifact.** The image deployed to production is byte-identical to the one tested in dev, identified by git SHA. Never rebuild for prod.

-   Migrations are a separate job that must succeed before the app revision is deployed.

-   Concurrency locks per environment so two deploys cannot race.

-   A failing gate is never bypassed. If a check is wrong, fix the check in its own PR.

## 7.4 Deployment credentials: OIDC only

Store no Azure client secrets in GitHub. Configure workload identity federation once per environment:

1.  Create an Entra app registration (or user-assigned managed identity) per environment: id-github-\<workload\>-dev, id-github-\<workload\>-prod.

2.  Add a **federated credential** scoped as tightly as possible --- by repository *and* by GitHub Environment (repo:org/repo:environment:prod), not merely by repository. This is what stops a branch in a fork from requesting a production token.

3.  Assign least-privilege RBAC on the target resource group only. The dev identity gets nothing in prod.

4.  In the workflow, request the token and log in:

> permissions:
>
> id-token: write \# required for OIDC
>
> contents: read
>
> jobs:
>
> deploy:
>
> environment: prod \# ties the token's subject claim to the environment
>
> steps:
>
> \- uses: azure/login@v2
>
> with:
>
> client-id: \${{ vars.AZURE_CLIENT_ID }}
>
> tenant-id: \${{ vars.AZURE_TENANT_ID }}
>
> subscription-id: \${{ vars.AZURE_SUBSCRIPTION_ID }}

Client id, tenant id and subscription id are identifiers, not secrets --- store them as environment variables. GitHub issues a short-lived token per run; Entra validates it against the federated credential; the token dies with the job. Nothing to rotate, nothing to leak.

## 7.5 Pull request standard

**Size:** one section. Under 400 changed lines. A reviewer who cannot hold the change in their head does not review it, they approve it.

**Description must contain:** the ticket, a link to the spec, what changed and why, how it was verified (with evidence), screenshots for UI, migration notes, rollback notes, and any new dependency with justification.

**Reviewer checklist**

**Correctness**

> ❑ Every acceptance criterion in the spec is implemented --- check the spec, not the description
>
> ❑ Tests exist for the criteria and the edge cases, and actually assert behaviour
>
> ❑ Error paths, empty states, permissions handled
>
> ❑ Migrations additive and reversible

**AI-specific --- the things that slip through**

> ❑ Nothing outside the task's scope changed
>
> ❑ No logic duplicated from somewhere that already exists in the repo
>
> ❑ No invented API, config key or dependency (does it exist? is it in the lockfile?)
>
> ❑ No unnecessary abstraction added "for future flexibility"
>
> ❑ No dead code, commented-out blocks, or unused exports
>
> ❑ Tests would actually fail if the implementation were wrong --- try to break one mentally
>
> ❑ Consistent with existing patterns rather than a new local style

**Non-functional**

> ❑ No secrets, keys, tokens or PII in code, tests, logs or fixtures
>
> ❑ Inputs validated at the boundary; authorisation checked, not assumed
>
> ❑ Obvious N+1 queries, unbounded queries or missing indexes
>
> ❑ Logs/metrics adequate to debug this path in production
>
> ❑ Docs, .env.example and API contract updated

Approve, request changes, or ask a question. "LGTM" on a diff you did not read is the single fastest way to lose the benefit of everything else in this document.

**PHASE 5**

# TESTING AND FEEDBACK LOOPS

Four stages, each with a wider audience and a tighter feedback mechanism. You do not skip a stage because you are confident.

> Stage 1: LOCAL you → automated checks + your own eyes
>
> Stage 2: INTERNAL the team → dev environment, scripted UAT, bug template
>
> Stage 3: EXTERNAL invited users → gated environment + in-app feedback button
>
> Stage 4: PRODUCTION real users → feature flags, canary %, monitoring

## 8.1 Stage 1 --- Local

Exit criteria: scripts/check.sh green, the feature exercised by hand against seeded data, edge cases tried deliberately (empty state, long strings, slow network, permission denied, double submit), and the fresh-context AI review clean.

## 8.2 Stage 2 --- Internal (dev environment)

Automated tests prove the code does what we asked. They cannot tell us we asked for the wrong thing. That is what this stage is for.

-   Merge to main auto-deploys to dev. Every team member can reach it.

-   **Scripted UAT scenarios** in docs/specs/\<feature\>.md: numbered steps, expected result per step, written from the *user's* perspective. Two people who did not build the feature walk them.

-   **Dogfood**: whoever will support this product uses it for a real task for a week before external users see it.

-   Bugs go to the issue tracker with the bug template (build SHA, environment, steps, expected, actual, screenshot, console/network output). Never in chat, where they evaporate.

-   Cross-browser and mobile-viewport pass on the critical journeys.

-   Accessibility pass: keyboard-only navigation, visible focus, labels, contrast, automated axe scan.

## 8.3 Stage 3 --- External testing with feedback loops

The point of external testing is that real users do things the team never would.

**Access.** The environment is not public. Gate it (§9.3): invited accounts via Entra External ID, or an IP allow-list, or credentials in front of the ingress. Add noindex and a robots.txt disallow so it never reaches a search engine.

**The feedback button --- mandatory before any external test.** A persistent, always-visible widget on every screen. It must capture, automatically, without asking the user:

  --------------------------------------------------------------------------------------------------------------
  **CAPTURED**                                                     **WHY**
  ---------------------------------------------------------------- ---------------------------------------------
  Free-text comment + category (bug / confusing / idea / praise)   The human signal

  Screenshot of the current view (with a redact tool)              Removes 80% of "cannot reproduce"

  Current route/URL and app state summary                          Where they were

  **Build SHA and environment**                                    Which code they were running

  User/tenant id (if authenticated)                                Follow-up and reproduction

  Browser, OS, viewport size                                       Environment-specific bugs

  Last N console errors and failed network requests                The actual cause, most of the time

  Timestamp with timezone                                          Correlation with logs and traces

  Optional "may we contact you" checkbox                         Follow-up consent
  --------------------------------------------------------------------------------------------------------------

Requirements: submits in one click without leaving the page; never blocks the user; queues and retries if offline; writes directly into the issue tracker (labelled feedback, env:external) so nothing is manually re-typed; visibly confirms receipt --- a widget that feels ignored stops being used. Privacy: tell users what is captured, in the widget, and honour redaction.

**Triage SLA** --- reviewed daily during an active test round:

  -------------------------------------------------------------------------------------------------------
  **SEVERITY**          **DEFINITION**                               **RESPONSE**
  --------------------- -------------------------------------------- ------------------------------------
  P1                    Blocks a core journey, data loss, security   Acknowledge 2h, fix same day

  P2                    Major feature broken, workaround exists      Acknowledge 1 day, fix this sprint

  P3                    Minor bug, cosmetic, friction                Backlog, batch

  P4                    Idea / enhancement                           Product backlog for prioritisation
  -------------------------------------------------------------------------------------------------------

**Close the loop.** This is the part that gets dropped. Feedback that implies a change of intent goes back to **Step 1 of the AI loop** --- update the spec, re-plan, re-audit. It does not become a prompt typed straight into an agent at 5pm. Report back to the testers what changed because of their feedback; participation collapses without it.

**Also instrument**: product analytics on the critical funnel (with consent), session replay if privacy review allows, and a short structured survey at the end of the round. Anonymous free-text feedback and observed behaviour disagree more often than you would expect --- trust the behaviour.

## 8.4 Stage 4 --- Production feedback

-   Keep the feedback button in production, routed to the same triage queue.

-   Every user-visible feature ships behind a **feature flag**, default off.

-   Roll out progressively: internal users → 5% → 25% → 50% → 100%, watching error rate, latency and the feature's own success metric at each step. Halt or roll back on anomaly rather than pushing through.

-   Deployment and release are separate events. The code can be in production for days before anyone sees it.

-   **Flags are debt.** Every flag has an owner and a removal date. Remove it within two releases of reaching 100%. A codebase full of stale flags is untestable --- you cannot reason about the combinations.

-   Prefer an open standard (OpenFeature) for the SDK interface so the provider can be swapped without touching application code.

-   Evaluate sensitive rules server-side; a flag is not a security boundary.

**PHASE 6**

# PRODUCTION CONTAINERS

The decisions in the Dockerfile determine the runtime attack surface more than any policy applied afterwards. Four changes carry most of the benefit: a minimal base image, a non-root user, a multi-stage build, and CI scanning that gates on critical CVEs.

## 9.1 Dockerfile standard

Rules, all mandatory for production images:

1.  **Multi-stage build.** Compilers, package managers and dev dependencies stay in the builder stage and never reach the runtime image.

2.  **Minimal runtime base**: distroless or slim. Verify musl compatibility before choosing Alpine --- native modules and glibc assumptions bite here.

3.  **Pin the base image by digest**, not by tag. A moving tag makes builds irreproducible.

4.  **Non-root.** USER 1001 (or the distroless nonroot user) before ENTRYPOINT. Application directories chowned appropriately.

5.  **No secrets in layers, ever.** Not in ARG, not in ENV, not in a copied file. Build-time credentials use BuildKit RUN \--mount=type=secret. Layers are permanent and inspectable.

6.  \*\*.dockerignore\*\* excluding .git, .env\*, node_modules, tests, docs, CI config. It shrinks the context and prevents accidental secret inclusion.

7.  **Order layers for cache**: manifest files, then install, then source. A one-line source change must not reinstall dependencies.

8.  **Production dependencies only** in the runtime stage.

9.  \*\*Clean caches in the same RUN\*\* that creates them.

10. \*\*HEALTHCHECK\*\* defined, and matching the platform probe.

11. **Correct signal handling** so SIGTERM drains connections gracefully --- an init shim if the runtime needs one.

12. **Generate an SBOM** at build (docker buildx \--sbom=true) and retain it as a release artifact.

13. **Scan with Trivy in CI and fail on CRITICAL/HIGH.**

14. **Tag by git SHA.** latest is banned in production.

15. **Rebuild regularly** even without code changes, to absorb base-image patches. A weekly scheduled rebuild-and-scan job catches CVEs disclosed after release.

Runtime configuration (set in Bicep, not the Dockerfile): read-only root filesystem with a writable tmpfs where needed, all Linux capabilities dropped, no privilege escalation, memory and CPU limits set. Never mount the Docker socket into a container.

## 9.2 Reference Dockerfile (stack-specific --- Node/TypeScript)

> \# syntax=docker/dockerfile:1.7
>
> \# \-\-\-- deps \-\-\--
>
> FROM node:22-bookworm-slim@sha256:\<pin\> AS deps
>
> WORKDIR /app
>
> COPY package.json pnpm-lock.yaml ./
>
> RUN \--mount=type=cache,target=/root/.local/share/pnpm/store \\
>
> corepack enable && pnpm install \--frozen-lockfile
>
> \# \-\-\-- build \-\-\--
>
> FROM deps AS build
>
> COPY . .
>
> RUN pnpm build && pnpm prune \--prod
>
> \# \-\-\-- runtime \-\-\--
>
> FROM gcr.io/distroless/nodejs22-debian12:nonroot AS runtime
>
> WORKDIR /app
>
> ENV NODE_ENV=production PORT=8080
>
> COPY \--from=build \--chown=nonroot:nonroot /app/node_modules ./node_modules
>
> COPY \--from=build \--chown=nonroot:nonroot /app/dist ./dist
>
> COPY \--from=build \--chown=nonroot:nonroot /app/package.json ./
>
> USER nonroot
>
> EXPOSE 8080
>
> CMD \["dist/main.js"\]

Health checking is configured on the Container App probes (/healthz, /readyz) since distroless has no shell for a HEALTHCHECK command.

## 9.3 Access gating for products not yet validated

**Rule: if a product is not signed off for public release, it does not sit on a public URL unauthenticated --- even if "nobody knows the address".**

Choose a gate, in order of preference:

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **GATE**                                     **USE WHEN**                                    **HOW**
  -------------------------------------------- ----------------------------------------------- ------------------------------------------------------------------------------------------------------
  **Entra ID / External ID sign-in**           Any product with user accounts                  Real auth on the app; invited users only. Preferred --- no shared credentials to leak.

  **IP allow-list**                            Client testing from a fixed office network      Container Apps ingress restrictions or Front Door WAF rules

  **Shared credentials in front of ingress**   Quick client review, static site, no auth yet   Basic-auth at the edge (Front Door rule or a small auth middleware). Weakest option --- last resort.
  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

In all cases: noindex meta tag plus robots.txt disallow, a visible non-production banner showing the environment and build SHA, and no production data.

**Credential handling, per site.** Where shared credentials are unavoidable:

-   One credential set **per site and per audience** --- never one password reused across clients or environments.

-   Stored in Key Vault or the team password manager. **Never** in the repo, a spreadsheet, a chat message or an email body.

-   Shared with the client through the password manager's secure-share link with an expiry.

-   Every gated site is entered in docs/gated-sites.md: URL, purpose, audience, gate type, credential reference, owner, created date, **review/expiry date**, and revocation trigger.

-   Reviewed monthly. Rotate on any personnel change on either side. Revoke the moment the test round ends.

-   No production credential is ever used for a test environment, and no test credential grants any production access.

**PHASE 7**

# DEPLOYMENT TO PRODUCTION

## 10.1 The validity gate: is this product allowed to go live?

Every item is a yes, or the product does not go to public production. It goes to a gated environment (§9.3) until it does. This is signed off by the tech lead **and** the product owner, recorded in the release ticket.

**Product**

> ❑ All acceptance criteria in scope are met and signed off by the product owner
>
> ❑ Stage 2 and Stage 3 testing complete; no open P1/P2 issues
>
> ❑ Critical journeys pass on supported browsers and mobile viewports
>
> ❑ Accessibility pass complete
>
> ❑ Support process defined --- who answers a user email on day one

**Security**

> ❑ No CRITICAL/HIGH findings in image scan, SAST or dependency audit
>
> ❑ Secret scan clean across full history
>
> ❑ Authentication and authorisation tested, including negative cases (can user A reach user B's data?)
>
> ❑ Rate limiting on auth and write endpoints
>
> ❑ HTTPS enforced, HSTS, security headers, CORS locked to known origins
>
> ❑ All inputs validated server-side; output encoded
>
> ❑ Container runs non-root; capabilities dropped; read-only FS where possible
>
> ❑ No production secret has ever been in the repo, a log, or an agent's context

**Data and legal**

> ❑ Privacy policy, terms, cookie/consent banner live and accurate
>
> ❑ PII inventory documented: what we store, where, why, for how long
>
> ❑ Retention and deletion path implemented (a user can be deleted)
>
> ❑ Backups configured **and a restore has been tested end-to-end**
>
> ❑ Data residency requirements met by the chosen region
>
> ❑ DPA/contractual obligations reviewed if processing client data

**Operations**

> ❑ Alerts live and routed to a named human; someone is on call
>
> ❑ Dashboard exists; health probes wired
>
> ❑ Runbooks written: deploy, rollback, restore, incident, common failures
>
> ❑ **Rollback rehearsed in dev and timed**
>
> ❑ Budget and cost alerts active
>
> ❑ Custom domain live with a valid, auto-renewing certificate

**Delivery**

> ❑ main green; the exact artifact has been running in dev and passed smoke + E2E
>
> ❑ Migrations rehearsed against a restored copy of production data
>
> ❑ Feature flags at their intended default states
>
> ❑ Release notes written

## 10.2 Release procedure

Deploy at a low-traffic time, never on a Friday afternoon, never with half the team unreachable.

1.  **Announce** the window in the team channel; note the current healthy baseline metrics.

2.  **Tag** the release from main (v1.4.0). The artifact is already built and tested --- promotion only.

3.  **Run migrations** as a gated job (expand-only changes).

4.  **Deploy a new revision** with **0% traffic**. Verify it starts and passes health probes in isolation.

5.  **Shift 10%** of traffic to the new revision. Watch for 15--30 minutes: error rate, p95 latency, key business metric, DB load.

6.  **Ramp** 50% → 100% if all clean. Any anomaly: shift traffic back to the previous revision immediately --- do not debug in front of users.

7.  **Smoke test** against the production URL.

8.  **Enable feature flags** progressively (§8.4). Release ≠ deploy.

9.  **Watch for an hour**, then check again the next morning.

10. **Contract migrations** (dropping the old column) in a later release, once the new code is proven.

11. **Publish release notes**; close the release ticket with the evidence.

**Rollback**

  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **SITUATION**         **ACTION**                                                                                                                                                                                   **TARGET TIME**
  --------------------- -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- ------------------------
  Bad code              Shift Container Apps traffic to the previous revision                                                                                                                                        \<2 min

  Bad feature           Turn the flag off                                                                                                                                                                            seconds

  Bad config            Revert the setting, restart revision                                                                                                                                                         \<5 min

  Bad migration         **Roll forward** with a corrective migration. Never restore a production DB to undo a schema change unless there is data loss --- that is a last resort with an accepted data-loss window.   varies
  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

Because migrations are expand-only, the previous revision keeps working against the new schema. This is the whole reason for the discipline.

## 10.3 Post-deployment setups

The launch is not the end of the work. Complete within 48 hours of first production deploy, tracked as a checklist on the release ticket.

**Platform**

> ❑ Custom domain resolving; certificate valid and auto-renewal confirmed
>
> ❑ DNS TTLs restored to normal values
>
> ❑ www ↔ apex redirect verified in one direction
>
> ❑ External uptime monitor active; status page published if customer-facing
>
> ❑ Scale rules and min/max replicas tuned against observed load
>
> ❑ WAF/Front Door rules active if applicable

**Data**

> ❑ Backup schedule and retention confirmed (35 days for prod); first backup verified present
>
> ❑ Restore drill scheduled and in the calendar
>
> ❑ Log and telemetry retention set deliberately (cost vs forensics)
>
> ❑ Reference/lookup data seeded via migration; verified

**Access**

> ❑ Admin accounts created with MFA enforced; no shared logins
>
> ❑ Azure RBAC reviewed --- remove any standing contributor access no longer needed
>
> ❑ Break-glass credentials stored, sealed and logged
>
> ❑ Client-facing credentials, if any, registered in docs/gated-sites.md

**Communication and compliance**

> ❑ Email domain authentication configured: SPF, DKIM, DMARC (transactional mail lands in spam without it)
>
> ❑ Analytics live with consent handling; goals/funnels configured
>
> ❑ sitemap.xml, robots.txt, canonical URLs, Open Graph metadata
>
> ❑ Error tracking receiving events and de-duplicating correctly
>
> ❑ Feedback button live and writing into the tracker
>
> ❑ Cookie/consent banner verified against the actual scripts loaded

**Team**

> ❑ Runbooks final and linked from the repo README
>
> ❑ On-call rota and escalation path published
>
> ❑ Handover/knowledge session held
>
> ❑ Post-release retro scheduled

**PHASE 8**

# OPERATE AND IMPROVE

## 11.1 Operating cadence

  ----------------------------------------------------------------------------------------------------------------------------------------------------
  **CADENCE**               **ACTIVITY**
  ------------------------- --------------------------------------------------------------------------------------------------------------------------
  Daily                     Alert triage; feedback queue triage; error-tracking review

  Weekly                    Dashboard review; dependency PRs merged; scheduled image rebuild + scan; IaC drift check; AI-generated code audit (§4.5)

  Fortnightly               Backlog grooming with feedback signal; flag cleanup

  Monthly                   Backup restore drill; access review; cost review vs estimate; performance review of top queries

  Quarterly                 This document reviewed; ADR log reviewed; DR exercise; penetration or security review
  ----------------------------------------------------------------------------------------------------------------------------------------------------

## 11.2 Incidents

1.  **Detect** --- an alert, or a user report.

2.  **Declare** --- say the word "incident" in the channel. Name one incident lead. Ambiguity costs more than a false alarm.

3.  **Mitigate before diagnosing** --- flag off, roll back traffic, scale up. Restore service first; understand later.

4.  **Communicate** --- status page and affected users, on a fixed interval even when there is nothing new.

5.  **Resolve and verify** --- confirm with metrics, not vibes.

6.  **Post-mortem within five working days** --- blameless, focused on the system: timeline, contributing causes, what detection missed, action items with owners and dates. Action items go into the backlog as real tickets or the post-mortem was theatre.

## 11.3 Metrics we watch

Delivery health: lead time (commit → production), deployment frequency, change failure rate, time to restore.

AI-assisted health --- the ones that reveal whether the loop is working:

  ----------------------------------------------------------------------------------------------------------------
  **METRIC**                                                         **WATCH FOR**
  ------------------------------------------------------------------ ---------------------------------------------
  Rework rate --- PRs needing \>2 review rounds                      Rising = specs or plan audits are too thin

  Reverted/hotfixed PRs                                              Rising = verification gaps

  Review time per PR                                                 Rising = sections are too large

  Bugs found in Stage 3 that Stage 1--2 should have caught           Testing strategy gap

  Ratio of feedback items that changed the spec vs became hotfixes   Loop discipline
  ----------------------------------------------------------------------------------------------------------------

Individual velocity going up while change failure rate goes up is not a win. Optimise for shipped, non-reverted increments.

**REFERENCE**

# APPENDICES

## Appendix A Setup Decision Record template

docs/adr/0001-setup-decision-record.md

> \# SDR: \<Product name\>
>
> Date: YYYY-MM-DD · Tech owner: \<name\> · Product owner: \<name\> · Status: Approved
>
> \## 1. What we are building
>
> \<Three sentences. The problem, the users, the first release scope.\>
>
> \## 2. Decisions
>
> \| \# \| Question \| Decision \| Reason \| Est. cost/mo \| Owner \|
>
> \|\-\--\|\-\--\|\-\--\|\-\--\|\-\--\|\-\--\|
>
> \| 1 \| Database? \| Yes --- PostgreSQL Flexible Server \| User-owned mutable state \| dev £15 / prod £140 \| \|
>
> \| 2 \| Hosting? \| Container Apps (web + api) \| Containerised SSR app \| dev £0 (scale-to-zero) / prod £90 \| \|
>
> \| 3 \| Auth? \| Entra External ID \| Customer-facing, do not build \| £0 at expected volume \| \|
>
> \| 4 \| File storage? \| Blob Storage \| User uploads \| £5 \| \|
>
> \| 5 \| Cache / queue / search? \| \*\*No\*\* \| No measured need; revisit with evidence \| --- \| \|
>
> \| 6 \| Background jobs? \| Container Apps Jobs \| Nightly reconciliation \| £5 \| \|
>
> \| 7 \| Email? \| Azure Communication Services \| Transactional only \| £5 \| \|
>
> \| 8 \| Observability? \| App Insights + Log Analytics \| Mandatory \| £20 \| \|
>
> \| 9 \| Feature flags? \| Azure App Configuration \| Progressive rollout \| £5 \| \|
>
> \| 10 \| WAF / Front Door? \| Not at launch \| Single region, no WAF requirement yet \| --- \| \|
>
> \## 3. Environments
>
> local / dev / prod. \<Justify any additional environment.\>
>
> \## 4. Regions and residency
>
> Primary: \<region\>. Reason: \<latency / residency\>.
>
> \## 5. Naming and tags
>
> Convention: see Appendix I. Tags: env, workload, owner, costCentre, managedBy.
>
> \## 6. Total estimate
>
> dev £\<x\>/mo · prod £\<y\>/mo · Budget alerts at 50/80/100%.
>
> \## 7. Explicitly deferred
>
> \<Things we consciously are not doing, and the trigger that would change that.\>
>
> \## 8. Open risks
>
> \| Risk \| Impact \| Mitigation \| Owner \|

## Appendix B .env.example standard

> \# ============================================================
>
> \# Copy to .env.local and fill in. NEVER commit real values.
>
> \# Every variable here is validated at boot by src/config.
>
> \# ============================================================
>
> \# \-\-- Runtime \-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\--
>
> NODE_ENV=development \# development \| test \| production
>
> PORT=8080
>
> LOG_LEVEL=debug \# debug \| info \| warn \| error
>
> APP_BASE_URL=http://localhost:3000
>
> \# \-\-- Database \-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\--
>
> \# Local: password auth. Dev/prod: managed identity, injected by the platform.
>
> DATABASE_URL=postgresql://app:app@localhost:5432/app_dev
>
> DATABASE_POOL_MAX=10
>
> DATABASE_SSL=false \# true in dev/prod
>
> \# \-\-- Auth (secret) \-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\--
>
> AUTH_ISSUER_URL=
>
> AUTH_CLIENT_ID=
>
> AUTH_CLIENT_SECRET= \# Key Vault in dev/prod
>
> AUTH_SESSION_SECRET= \# 32+ random bytes; Key Vault in dev/prod
>
> \# \-\-- Azure \-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\--
>
> AZURE_STORAGE_ACCOUNT=
>
> AZURE_STORAGE_CONTAINER=uploads
>
> AZURE_KEY_VAULT_URI= \# empty locally
>
> AZURE_CLIENT_ID= \# user-assigned managed identity (dev/prod)
>
> \# \-\-- Telemetry \-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\--
>
> APPLICATIONINSIGHTS_CONNECTION_STRING=
>
> OTEL_SERVICE_NAME=api
>
> \# \-\-- Third party (secret) \-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\--
>
> PAYMENTS_API_KEY=
>
> SMTP_PASSWORD=
>
> \# \-\-- Feature flags \-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\-\--
>
> FEATURE_FLAGS_ENDPOINT=
>
> FEATURE_NEW_CHECKOUT=false
>
> \# \-\-- Browser-exposed: NEVER put a secret behind this prefix \--
>
> NEXT_PUBLIC_APP_NAME=Acme
>
> NEXT_PUBLIC_API_URL=http://localhost:8080

## Appendix C SPEC.md template

> \# Spec: \<Feature\>
>
> Ticket: PROJ-123 · Author: \<name\> · Status: Draft \| Approved · Date:
>
> \## Problem
>
> Who has it, what it costs them today.
>
> \## Users and permissions
>
> \| Role \| Can do \| Cannot do \|
>
> \## In scope
>
> \- ...
>
> \## Out of scope ← be generous here
>
> \- ...
>
> \## Acceptance criteria (each becomes a test)
>
> AC1. When \<trigger\>, the system shall \<response\>.
>
> AC2. While \<state\>, the system shall \<response\>.
>
> AC3. If \<error condition\>, then the system shall \<response\>.
>
> \## Data
>
> New/changed tables, fields, indexes, constraints. Migration strategy.
>
> \## API contract
>
> \| Method \| Path \| Request \| Response \| Errors \|
>
> \## UI
>
> Screens, states (loading / empty / error / partial / success), key interactions.
>
> \## Non-functional
>
> Performance target · Security/authorisation rules · Accessibility · Observability
>
> (what must be logged/measured) · Limits (rate, size, pagination)
>
> \## Edge cases and failure modes
>
> \- ...
>
> \## Verification
>
> End-to-end scenario that proves the feature works, start to finish.
>
> \## UAT script (for Stage 2)
>
> \| \# \| Step \| Expected result \|
>
> \## Open questions
>
> \- ...

## Appendix D PLAN.md template and audit

> \# Plan: \<Feature\> (generated in plan mode, audited by \<name\> on \<date\>)
>
> Spec: docs/specs/\<feature\>.md
>
> \## Approach
>
> Two paragraphs. Why this way, what was rejected.
>
> \## Files
>
> \| Path \| Create/Modify \| Purpose \|
>
> \## Tasks
>
> \### T1 --- \<name\>
>
> \- Implements: AC1, AC2
>
> \- Expected output: \<concretely, what exists after this task\>
>
> \- Verification: \<command / test file / manual step\>
>
> \- Depends on: ---
>
> \### T2 --- ...
>
> \## Data changes
>
> Migration name, columns, backfill, expand/contract sequence.
>
> \## Risks and unknowns
>
> \| Risk \| Mitigation \|
>
> \## Out of scope for this plan
>
> \- ...
>
> \## Audit (human --- tick before implementation starts)
>
> \- \[ \] Every AC maps to ≥1 task
>
> \- \[ \] Every task maps to ≥1 AC (no orphans)
>
> \- \[ \] Each task's expected output is what we actually need
>
> \- \[ \] Existing patterns reused; no reinvention
>
> \- \[ \] No new dependency without approval
>
> \- \[ \] Data changes additive/reversible
>
> \- \[ \] Errors, empty states, permissions covered as tasks
>
> \- \[ \] Each task reviewable in one sitting
>
> \- \[ \] Verification named per task
>
> \- \[ \] Nothing touches prod, secrets or infra it should not
>
> Audited by: \_\_\_\_\_\_ Date: \_\_\_\_\_\_

## Appendix E CLAUDE.md starter

Keep it under a page. Prune monthly. If a rule is ignored twice, make it a hook.

> \# Project: \<name\>
>
> Monorepo: apps/web (Next.js), apps/api (NestJS), packages/shared (types).
>
> \## Commands
>
> \- pnpm dev \# web + api + db
>
> \- pnpm check \# format, lint, types, unit --- run before any commit
>
> \- pnpm test:int \# integration; needs docker compose up -d
>
> \- pnpm db:migrate \# apply migrations
>
> \- pnpm db:new \<name\> \# create a migration
>
> \## Workflow
>
> \- Work from docs/specs/\<feature\>.md and PLAN.md. Do not start without an audited plan.
>
> \- One task per session. Run \`pnpm check\` and show me the output before saying done.
>
> \- Branch: feature/\<ticket\>-\<slug\>. Conventional commits. Squash merge.
>
> \- Bug fixes start with a failing test.
>
> \- If a requirement is ambiguous, stop and ask.
>
> \## Conventions
>
> \- Group by feature. Import features only via their index.ts, never internals.
>
> \- Controllers: HTTP only. Services: business logic. Repositories: data access.
>
> \- Validate all external input with zod at the boundary. No \`any\` at boundaries.
>
> \- Read env only through src/config (schema-validated). Never process.env elsewhere.
>
> \- New dependencies need approval --- ask first.
>
> \## Never
>
> \- Never edit a migration that has already been applied --- add a new one.
>
> \- Never edit infra/ without telling me.
>
> \- Never commit .env files or real credentials.
>
> \- Never use production credentials or connect to production.

## Appendix F Pull request template

> \## What and why
>
> Ticket: PROJ-\_\_\_ · Spec: docs/specs/\_\_\_.md
>
> \## Section
>
> Which slice of the plan is this? (T3 of PLAN.md)
>
> \## How it was verified
>
> \<paste the command and its output --- not "tests pass"\>
>
> \- \[ \] \`pnpm check\` green
>
> \- \[ \] Integration tests green
>
> \- \[ \] Exercised by hand locally
>
> \- \[ \] Fresh-context AI review run; findings addressed
>
> \## Screenshots / recordings
>
> \<UI changes only\>
>
> \## Data changes
>
> \- \[ \] None
>
> \- \[ \] Migration: \<name\> --- additive? reversible? backfill?
>
> \## Rollback
>
> How do we undo this? (flag / revision / corrective migration)
>
> \## New dependencies
>
> None / \<name --- what it does, why not stdlib, licence, weekly downloads\>
>
> \## Checklist
>
> \- \[ \] Only files in scope changed
>
> \- \[ \] No secrets, keys or PII in code, tests or logs
>
> \- \[ \] Docs / .env.example / API contract updated
>
> \- \[ \] Feature flag added if user-visible
>
> \- \[ \] Logs and metrics adequate to debug in production

## Appendix G Bug / feedback issue template

> \*\*Environment:\*\* local \| dev \| external-test \| production
>
> \*\*Build SHA:\*\*
>
> \*\*URL / route:\*\*
>
> \*\*User / tenant:\*\*
>
> \*\*Browser + OS + viewport:\*\*
>
> \*\*Steps to reproduce\*\*
>
> 1\.
>
> \*\*Expected:\*\*
>
> \*\*Actual:\*\*
>
> \*\*Screenshot / recording:\*\*
>
> \*\*Console errors / failed requests:\*\*
>
> \*\*Severity:\*\* P1 \| P2 \| P3 \| P4

## Appendix H Prompt library

  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **PURPOSE**                **PROMPT**
  -------------------------- -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Interview → spec**       "I want to build \<X\>. Interview me in detail. Ask about implementation, UX, edge cases, failure modes and trade-offs. Skip the obvious; dig into the hard parts. Keep going until we've covered everything, then write the spec to docs/specs/\<x\>.md."

  **Plan**                   "Read-only. Read docs/specs/\<x\>.md plus src/modules/orders as the pattern reference. Produce PLAN.md: files to create/modify, tasks each independently verifiable with a stated expected output and verification method, data changes, risks, and what's out of scope. Do not write code."

  **Implement**              "Implement T\<n\> from PLAN.md. Follow the pattern in \<file\>. Write the tests for the listed edge cases first, then the implementation. Run pnpm check and show me the output. Change nothing outside the files named in T\<n\>. Stop and ask if anything is ambiguous."

  **Bug fix**                "Users report \<symptom\>. Likely in \<dir\>. Write a failing test that reproduces it, then fix the root cause --- do not suppress the error. Show the test failing before and passing after."

  **Fresh-context review**   "Review this diff against docs/specs/\<x\>.md and PLAN.md. Check every AC is implemented, listed edge cases have tests, and nothing out of scope changed. Report only gaps affecting correctness or stated requirements. No style preferences."

  **Security review**        "Review this diff as a senior security engineer: injection, authn/authz flaws, secrets in code, unsafe data handling, missing rate limits, IDOR. Give line references and concrete fixes."

  **Challenge it**           "Grill me on these changes. What breaks under concurrency, at 100× data volume, on a slow network, or with a hostile user? Don't approve until you've tried to break it."

  **Simplify**               "This works. Now: what's the simplest version that still satisfies every AC? Identify unnecessary abstraction, unused flexibility and dead paths. Propose the reduction before making it."

  **Weekly audit**           "Review src/modules/{a,b} for duplicated logic elsewhere in the repo, unreachable code, deviations from CLAUDE.md, and tests asserting implementation rather than behaviour. Report with file/line, ranked by impact. Fix nothing yet."

  **Onboarding**             "How does \<auth / logging / caching\> work in this codebase? Point me at the files and explain the flow end to end."

  **Pre-deploy diff**        "Summarise every change between v1.3.0 and main grouped by risk: data/migration, auth/security, external integrations, UI. Flag anything needing a manual verification step in production."
  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

## Appendix I Naming conventions

Pattern: \<type\>-\<workload\>-\<component\>-\<env\>-\<region\>\[-\<instance\>\] Environments: dev, prod · Regions: short form, e.g. weu (West Europe), uks (UK South)

  ----------------------------------------------------------------------------------------------------------
  **RESOURCE**                 **PREFIX**        **EXAMPLE**            **NOTES**
  ---------------------------- ----------------- ---------------------- ------------------------------------
  Resource group               rg-               rg-acme-prod-weu       One per environment

  Container Apps environment   cae-              cae-acme-prod-weu      

  Container app                ca-               ca-acme-api-prod-weu   Lowercase, ≤32 chars

  Container registry           none              cracmeprod             Alphanumeric only, globally unique

  PostgreSQL server            psql-             psql-acme-prod-weu     Globally unique

  Key Vault                    kv-               kv-acme-prod-weu       ≤24 chars, globally unique

  Storage account              st                stacmeprodweu          Lowercase alphanumeric, ≤24

  Managed identity             id-               id-acme-api-prod       

  App Insights                 appi-             appi-acme-prod-weu     

  Log Analytics                log-              log-acme-prod-weu      

  Front Door                   afd-              afd-acme-prod          

  DNS zone                     none              example.com            
  ----------------------------------------------------------------------------------------------------------

Length-constrained resources (Key Vault, storage, ACR) drop separators and abbreviate the workload. Generate names from a shared Bicep function so they cannot drift.

**Mandatory tags on every resource:** env, workload, owner, costCentre, managedBy=bicep.

## Appendix J Roles

  -------------------------------------------------------------------------------------------------
  **ACTIVITY**        **PRODUCT OWNER**   **TECH LEAD**           **DEVELOPER**      **REVIEWER**
  ------------------- ------------------- ----------------------- ------------------ --------------
  SDR                 Approve             Author                  Contribute         ---

  Spec                Approve             Review                  Author (with AI)   ---

  Plan audit          ---                 Approve for high-risk   Author             ---

  Implementation      ---                 ---                     Own (with AI)      ---

  PR review           ---                 infra/, db/             ---                Own

  Go/no-go            Sign off            Sign off                Evidence           ---

  Production deploy   Approve             Execute                 Support            ---

  Incident lead       Comms               Usually lead            Support            ---
  -------------------------------------------------------------------------------------------------

## Appendix K One-page quick reference

> BEFORE YOU BUILD SDR signed → infra deployed → repo structured → .env standard
>
> BEFORE YOU PROMPT Frame it yourself → SPEC.md → PLAN.md → AUDIT the plan
>
> WHILE YOU BUILD One section at a time → a check the AI can run → evidence
>
> BEFORE YOU MERGE Fresh-context AI review → human reads the diff → CI green
>
> BEFORE YOU RELEASE Validity gate signed → migrations rehearsed → rollback tested
>
> WHILE YOU RELEASE 0% → 10% → 50% → 100% → then flip the flag
>
> AFTER YOU RELEASE Post-deploy setups within 48h → watch → close the feedback loop
>
> STOP IF the plan has an orphan task
>
> the AI says "done" without evidence
>
> the diff touches files outside scope
>
> you have corrected the same mistake twice (clear and re-prompt)
>
> a gate is red and someone suggests skipping it

## Appendix L Sources and further reading

-   Claude Code best practices --- https://code.claude.com/docs/en/best-practices

-   Spec-driven development field guide (2026) --- https://dev.to/krlz/spec-driven-development-in-2026-what-it-is-the-tooling-and-how-teams-actually-use-it-2fk2

-   Spec-driven development best practices --- https://blog.allegro.tech/2026/06/spec-driven-development-best-practices.html

-   Azure: choosing App Service vs Container Apps --- https://learn.microsoft.com/en-us/azure/container-apps/compare-options

-   Best practices for IaC CI/CD on Azure --- https://techcommunity.microsoft.com/blog/ITOpsTalkBlog/best-practices-for-infrastructure-as-code-cicd-on-azure/4529941

-   Configuring OpenID Connect in Azure (GitHub Docs) --- https://docs.github.com/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-azure

-   Custom domains and managed certificates in Container Apps --- https://learn.microsoft.com/en-us/azure/container-apps/custom-domains-managed-certificates

-   Securing Azure Database for PostgreSQL Flexible Server --- https://learn.microsoft.com/en-us/azure/postgresql/security/security-overview

-   Backup and restore in PostgreSQL Flexible Server --- https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-backup-restore

-   Docker building best practices --- https://docs.docker.com/build/building/best-practices/

-   Feature flag and progressive delivery practices --- https://www.flagsmith.com/blog/progressive-delivery

\*This document is version-controlled at docs/way-of-working.md. Changes go through a PR like anything else. If a rule here is costing more than it saves, raise it at the quarterly review rather than quietly ignoring it.\*
