# render-deploy -- 2026-10-17

- **Image SHA:** 0ad12c6d89581a77f916d7c197ca79c2cc5c527f (n+4). First deployed: 1110f9349cd976fc468885af67940618d8e243ca (n).
- **Who / where:** Martijn Boot, Render (Frankfurt) with GitHub Actions. Phone and browser on the bar and display pages of run 1.
- **What was done:**
  1. Pinned render.yaml to n (PR #11) and applied the Blueprint (Starter web, basic-256mb Postgres). Set DATABASE_URL by hand, turned Auto Sync off, created the smoke key and set the secrets and variable.
  2. Deploy of n (2026-10-11): deploy OK, smoke failed at theme.css (D-H1-1, fixed by T23, n+2 = 7524a8c3555804791db902a5299acd2cf2ac3bc3).
  3. Deploy hook returned 409 (2026-10-11, run 38166029986, probably a suspended service). Deploy of n+2 (2026-10-16, run 38949649203): smoke failed at login with 503 standby (D-H1-2, fixed by T24, n+3 = fe5c063e68f4753823c5bd3971a90e4a6b35fa12).
  4. Deploy of n+3 (2026-10-17, run 39016701680): green, seven smoke steps, no borrel running.
  5. Deploy of n+4 (2026-10-17, run 39018016714) while a phone and a browser were on run 1: green, seven smoke steps. healthz showed build_sha = n+4.
- **Timings:** n+3 run 1m46s, n+4 run 1m42s. Render kept both instances up for ~58-60 s; the app handover was 1.19 s (n+3) and 1.45 s (n+4) from the old instance stopping to runtime_started. Orders failed for about 38 s on the phone (08:37:29-08:38:07 UTC, 28 x 503 on POST /api/orders), working again at 08:38:31. No target is set for this step.
- **What broke:**
  - D-H1-1: smoke rejected a weak ETag (Cloudflare). Fixed in T23.
  - D-H1-2: smoke passed against the old instance during the overlap. Fixed in T24.
  - F-H1-1: Render overlaps the old and new instance for ~60 s (SD4 expected a few seconds). Confirmed on three deploys.
  - F-H1-3: during the overlap, order placement returned 503 and the bar's retries failed until the handover. No order was written or duplicated. Prices did not move in the window. Accepted by the human for a mid-borrel deploy.
  - F-H1-2: lock_hold_ms warnings of 53-278 ms (threshold 50 ms) on a few ticks a minute: the latency of Render's database.
  - Contiguous version numbers across the handover could not be shown: the logs have no version lines.
- **Follow-ups:**
  - Check whether Render lets the overlap delay be set; otherwise reword SD4 to say "~60 s, bar retrying".
  - Decide whether the bar should hold or queue orders during a 503 window (F-H1-3). The runbook should say deploy at a quiet moment.
  - Cause of "prices did not move" during the overlap: not investigated.
  - lock_hold_ms tuning for Render's database (F-H1-2).
  - Show contiguous versions across a handover (a log line or a test), or accept the integration test as proof.
