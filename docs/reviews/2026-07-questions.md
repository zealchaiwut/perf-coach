# Open Questions for Discussion — 2026-07 Review

Decisions the review surfaced that need the owner's call. Grouped by theme;
each has a recommendation but none has been acted on.

## Security (decide first)

1. **Lock down `/api/users` CRUD now?** GET/POST/PATCH/DELETE are
   unauthenticated (main.py:283, 352, 377, 404); DELETE cascades all of a
   user's data. Recommendation: gate behind `require_admin` immediately —
   small, isolated change. Same ticket: add ownership check to
   `GET /api/sync/strava/status` (IDOR, main.py:9780).
2. **Delete the `LEGACY_USER_ID_SHIM` path entirely** (main.py:458-481), or
   keep the flag? It's one flag-flip from full impersonation.

## Model / calculation direction

3. **Which readiness formula is canonical?** Four exist (see
   calculations/readiness.md). Consolidate to the persisted
   `services/readiness` calculator and have home/trends read
   `daily_readiness`? Or keep per-surface formulas deliberately?
4. **Close the calibration loop or replace it?** Accepted `ctl_days/atl_days`
   are written but never read. Options: (a) make `training_load` read prefs —
   small; (b) retire the heuristic calibration and finish wiring the Banister
   fitting stack (`model_refit.py`/`refit_scheduler.py`, currently test-only)
   — the better long-term ML path. Which?
5. **Unify the two Banister stacks?** `training_load.py` vs
   `fitness_model.py`/`projection.py` differ on TSB day-convention → different
   TSB per tab for the same date. Pick one convention, one constants module.
6. **Performance-score normalization: move to absolute anchoring?** Min-max
   within the 90-day window means score 100 = "best recent run", not fitness.
   Requires deciding an anchor (threshold-pace efficiency? benchmark efforts?).
7. **TSS defaults for new users:** silent 270 s/km / 170 bpm / 280 W defaults
   mean uncalibrated TSS until prefs set. Force threshold setup in onboarding,
   or flag TSS as "uncalibrated" until prefs exist?
8. **Unify the two TSS paths** so synced and manual runs score on the same
   scale (reconcile uses the defaults-happy estimator, CRUD uses the strict
   one)?
9. **Fix the broken decoupling calls** (main.py:5480, :5606 — wrong arity,
   silently disabled durability)? Concept question: should log-card scores
   even include durability, given the correct path does?

## ML groundwork (cheap now, priceless later)

10. **Start a `predictions` table now?** (user, made_on, horizon, predicted
    ctl/atl/tsb, predicted race time, band). Zero UI; pure logging. Unblocks
    learned confidence bands and race-time models. Recommendation: yes, next
    sprint.
11. **Start injury/illness/missed-session logging?** Smallest possible UI (a
    daily flag or workout tag). Only path to a learned guardrail.
12. **Persist score history** (endurance/speed per day) instead of
    recomputing? Also fixes the per-request O(all laps) `/performance` cost.
13. **Stamp formula versions** on `daily_readiness` and cached bundles?

## Architecture / cleanup

14. **Retire sync System B?** (`POST /api/sync/strava` + `strava_sync.py` +
    `workout_reconcile.py`). System A covers it with better upserts and the
    richer reconciler. Any client still calling System B endpoints?
15. **main.py decomposition:** 15,878 lines, 214 routes, routers hold <3 %.
    Adopt a rule ("every new resource = router file") plus gradual extraction?
    Which groups first — users/auth, sync, plan/performance?
16. **Dead-code deletion batch:** dead router `sessions.py`, ~18 test-only
    service modules, orphan frontend pages (projection.html/js,
    weekly-check-in.*, index.html), orphan JS libs, mock-data.js prod
    fallback, dead functions (~500+ lines total). Delete in one sweep ticket,
    or keep any deliberately (e.g. modules awaiting wiring — which)?
17. **Reconcile → snapshots gap:** sync updates TSS but never refreshes
    `training_load_snapshots`. Chain `daily_update` after reconcile?
18. **`workouts.updated_at`:** absence breaks plan-cache invalidation on
    edits AND blocks edit-aware signatures generally. Add the column +
    backfill migration?
19. **Settings page structure:** 2,385 lines inline JS vs 52-line module —
    externalize to match every other page?
20. **Frontend shared lib:** one `lib/` module for esc()/today()/apiGet/sync
    poller (currently 10/8/2/5 copies). Worth a small ticket now, or fold
    into each page's next rework?
21. **`/log` full-history fetch:** paginate/window the training-log API, or
    keep client-side filtering deliberately (issue #637)? Re-fetch-everything
    after each edit is the costlier half — patch locally instead?
22. **Docs cleanup:** delete `backend/db/SCHEMA.md` + `docs/data-model.md`
    (keep root SCHEMA.md as the one schema doc), delete `docs/STATUS.md`,
    move `services/readiness/README.md` into `docs/calculations/`, regenerate
    or de-scope `docs/api-reference.md`, update CLAUDE.md (routers + point at
    SCHEMA.md). OK to do all?

## Watch-outs (no decision needed, noting)

- Refit daemon thread resets its 7-day timer on every restart — frequent
  deploys starve weekly Banister refits (main.py:15845).
- `_DAILY_RECONCILE_LIMIT=10` leaves >10-activity syncs partially
  unreconciled until next full sync.
- In-process state (lockout, caches, sync registry) assumes single-worker
  uvicorn — document as a deployment constraint or move to DB/Redis when
  scaling.
- `detect_stryd_origin` power-field branch dead (wrong field names,
  strava.py:72-73).
