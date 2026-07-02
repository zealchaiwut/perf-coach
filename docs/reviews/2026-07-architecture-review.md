# Architecture & Flow Review — 2026-07

Full-repo concept review (performance, flow, loopholes, dead code — not a bug
hunt). Branch `review/architecture-docs-2026-07`; line anchors from that
checkout. Companion docs: `docs/calculations/` (formula-level detail),
`docs/reviews/2026-07-questions.md` (open decisions).

---

## 1. Backend structure

- `backend/main.py` is **15,878 lines with 214 route decorators** — ~60
  concatenated modules. The router mechanism exists (`backend/routers/`) but
  holds <3 % of routes (`plan.py`, `strength_sessions.py`).
- `backend/routers/sessions.py` (331 lines) is a **dead router** — defines the
  same strength/plyo CRUD as `strength_sessions.py` but is never mounted.
- `backend/services/` has ~100 modules (~19k lines); ~18 are prod-dead
  (test-only, see §6).
- Two module-level daemon threads start **at import time**
  (main.py:15817 hourly sleep-sync; :15873 weekly Banister refit). Under
  multi-worker uvicorn they'd run once per worker; each restart resets the
  7-day refit timer (sleep-first loop, :15845) so frequent redeploys can
  starve the weekly refit indefinitely.

## 2. Sync & reconcile flow

**Two parallel, independent sync systems exist:**

- **System A (primary):** in-memory job registry (`sync_jobs.py`) +
  `ThreadPoolExecutor(max_workers=3)` shared across ALL users (main.py:9432).
  ON-CONFLICT upserts; chains into `reconcile.reconcile_workouts`.
  Incremental reconcile capped at `_DAILY_RECONCILE_LIMIT = 10`
  (main.py:9429) — a sync pulling >10 activities leaves the excess
  unreconciled until the next full sync.
- **System B (Strava only):** DB `SyncJob` rows + FastAPI BackgroundTasks
  (`POST /api/sync/strava`, main.py:9667). `strava_sync.py` does manual
  read-modify-write, **one Session and commit per activity** (:177-205), and
  has its own weaker reconciler (`workout_reconcile.py`) with divergent merge
  semantics. Both systems write `SyncJob` rows, so history mixes them.

Other flow notes:

- Sync cancel flag exists (`sync_jobs.py:41,82`) but **no endpoint sets it** —
  dead feature.
- Registry is in-memory: restart mid-sync shows idle while orphaned pool
  threads may still run; single-flight resets → duplicate syncs possible.
- Reconcile matches by start_time ±5 min (`reconcile.py:12`); manual entries
  >5 min off create duplicates.
- Reconcile does NOT refresh training-load snapshots (no `training_load`
  reference in reconcile.py) — synced workouts update TSS but not CTL/ATL
  snapshots.
- `detect_stryd_origin` power heuristic checks `avg_power_w`/`max_power_w`
  (strava.py:72-73) but raw Strava payloads use `average_watts`/`max_watts` —
  that branch never fires; only device-name/external-id detection works.
- Systemic stream-fetch failures are log-and-continue
  (stryd_sync.py:256, reconcile.py:187) — a failing enrichment pipeline looks
  like a successful sync. 41 bare `except Exception:` blocks in main.py.

## 3. Security loopholes (highest severity findings)

1. **Unauthenticated user CRUD.** `GET /api/users` (main.py:283) enumerates
   all users with integration status; `POST /api/users` (:352),
   `PATCH /api/users/{id}` (:377), and `DELETE /api/users/{id}` (:404) require
   no session. DELETE cascades the user's entire data. These predate session
   auth and were never locked down (an admin-guarded POST duplicate exists at
   :11779).
2. **IDOR on sync job status.** `GET /api/sync/strava/status?job_id=`
   (main.py:9780-9805) returns any job row (including user_id and
   error_message) with no ownership check. `/api/sync/history` (:12113)
   checks correctly.
3. **Latent impersonation shim.** `LEGACY_USER_ID_SHIM_ENABLED = False`
   (main.py:458), but the `?user_id=` impersonation path still exists in
   `resolve_user` (:461-481) one flag-flip away.
4. `athlete_id` path params are decorative — endpoints use the session user
   regardless (main.py:11688, 14120, 14393, 14750). No leakage, but requests
   for another athlete silently return your own data instead of 403.

## 4. Caching & state (concept-level)

| Layer | Mechanism | Gap |
|---|---|---|
| Plan bundle | `training_plans.computed_cache` + signature | workout **edits** invisible (no `workouts.updated_at`); checkpoint CRUD outside signature; signature costs 5 aggregate queries even on hit |
| Load snapshots | `training_load_snapshots` table | hot read paths (`current_load`) bypass it and rebuild 180-day series per request; historical edits not back-propagated |
| Readiness | `daily_readiness` upsert | never invalidated by metric edits; only recomputed on explicit POST |
| Summaries | in-process `_SUMMARY_CACHE` | per-worker; lost on restart (by design) |
| Projection | none | full CTL/ATL simulation per request |
| Login lockout, Banister params | in-process dicts | per-worker in multi-worker deploys |

Heavy request-path compute: `GET /api/readiness/range` recomputes each
missing day per request without persisting (main.py:8100-8131);
`_compute_plan_bundle` runs `get_race_readiness` per upcoming race (N+1,
main.py:14974); full-sync reconcile loads all workouts + all activities.

Index note: hot composite indexes (`ix_workouts_user_id_workout_date` etc.)
exist in migrations but are **not declared in models.py** — drift risk for
fresh `create_all` environments. `daily_readiness` declares no indexes.

## 5. Frontend

- **Monsters:** training-log.html 7,187 lines (5,665 of which are ONE inline
  `<style>` block — 79 %); training-log.js 5,308 lines; settings.html 3,951
  lines with 2,385 lines of inline JS and 43 inline fetches beside a 52-line
  settings.js (the inverse of every other page). `/log` ships ~12,000 lines
  of first-party JS per visit; training.js (2,014 lines) is loaded solely for
  its `TrainingEditor` export.
- **Full-history refetch:** `/log` requests `from=2010-01-01` on load AND
  after every sync/edit/delete/restore (15+ `fetchAndRender` call sites) —
  re-downloading multi-year history each time. Volume chart destroyed +
  rebuilt on every fetch (training-log.js:837,867); same destroy/recreate in
  trends.js:1095-1098.
- **Five sync-status pollers** with different intervals (2s/3s/4s) and error
  paths: nav.js:472 (polls on EVERY page load even with no sync running),
  training-log.js:3737 and :3794 (two in one file), settings.html:2613 and
  :3137 (inline near-copies).
- **Duplicate identity fetches:** `/api/auth/me` fetched independently by
  user.js, nav.js, home.js, training-plan.js, projection.js — 2–3 calls per
  page view. `apiGet`/`apiPost` helpers duplicated verbatim
  (projection.js:127 = training-plan.js:170). `esc()` XSS helper defined in
  10 files; Bangkok-"today" helper in 8.
- **Convention breach:** `/trends/summary` route lacks the mandated `/api/`
  prefix (main.py:7837, trends.js:181).
- **Logic split across the boundary:** ACWR computed client-side
  (training-performance.js:459-478) while all sibling metrics are
  backend-computed.
- Good patterns worth spreading: `/api/home/summary` single-bundle fetch
  (home.js:1304); `/api/plan/computed` bundle; lazy sub-tab init on `/log`.
- `_no_cache_frontend` middleware (main.py:132-140) forces revalidation of
  whole pages, so giant inline CSS gets zero caching benefit.

## 6. Dead code inventory

**Frontend — orphans (no route serves them):**
- `frontend/pages/projection.html` (835) + `frontend/js/projection.js` (875)
  — `/projection` is a 302 → `/log#plan` since #1226 (main.py:5121). Fully dead.
- `frontend/pages/weekly-check-in.html` (358) + `weekly-check-in.js` (311) —
  no route.
- `frontend/pages/index.html` — `/` redirects to `/home`.
- Orphan JS: `home-habits.js`, `habit-adherence.js`, `lib/habit-voice.js`,
  `lib/weight-voice.js`.
- `mock-data.js` (541 lines) ships to production `/trends` with live
  mock-fallback render paths (trends.js:789-870).
- Dead functions: ~200+ lines of pre-bundle loaders in training-plan.js
  (:321,1074-1157) superseded by `/api/plan/computed`; 8 dead functions in
  training-log.js; 6 in home.js; more in weight.js/habits.js/training.js.

**Backend:**
- `backend/routers/sessions.py` — dead router (never mounted).
- `backend/services/weight_what_if_caller.py` — zero importers.
- Prod-dead (test-only): `monthly_summary.py`, `rolling_intensity.py`,
  `weekly_check_in.py`, `strength_tss.py`, `refit_scheduler.py` +
  `model_refit.py`, `backfill_economy.py`, `per_workout_curves.py`,
  `ea_proxy.py`, `fit_data_collector.py`, `focus_coaching.py`,
  `habit_focus.py`, `habit_breakdown.py`, `habit_slipping.py`,
  `habit_voice.py`, `channel_select.py`, `banister_validation.py`,
  `running_tss_power_caller.py`, `suggest_thresholds.py`.
- Near-duplicates both alive: `duration_curve.py` (live) vs
  `duration_curves.py` (dead); `threshold_suggestions.py` (live) vs
  `suggest_thresholds.py` (dead) — both define `suggest_thresholds`;
  `reconcile.py` (live, rich) vs `workout_reconcile.py` (weaker, one
  System-B endpoint); `lap_classifier.py` vs `lap_classify.py`.
- Dead features in live code: sync cancel flag; System B Strava sync stack;
  LEGACY_USER_ID_SHIM path.

## 7. Duplicated / conflicting logic (see docs/calculations/ for detail)

1. Two Banister stacks (`training_load.py` vs `fitness_model.py`+`projection.py`)
   with different TSB day-conventions — same date, different TSB per tab.
2. Calibration writes `ctl_days/atl_days` prefs nothing reads — loop never closes.
3. Four readiness formulas (readiness.md).
4. Two TSS paths with different default-threshold behavior — source-dependent
   TSS calibration.
5. Decoupling computed 3 ways; two of three call sites broken (wrong-arity
   call swallowed by except) — durability adjustment silently off for log-card
   and as-of scores (main.py:5480, :5606).
6. Riegel exponent + score→pace map each defined in 2–3 places.
7. Score-as-of run-assembly logic duplicated 3× in main.py.
8. Two taper models; generated `planned_load` schedule not consumed by
   projection (flat average used instead).

## 8. Docs staleness (summary of inventory)

- **Good/fresh:** root `SCHEMA.md` (the one true schema doc), `docs/sync.md`,
  release/render docs, CHANGELOG.
- **Stale:** `docs/api-reference.md` (pinned to 2026-05-31 commit, ~9 sprints
  behind); `docs/data-model.md` (16 of ~38 tables); CLAUDE.md schema list
  (18 of ~38 tables; also claims "ALL endpoints in main.py" — routers exist);
  `docs/training-load.md` (documents removed `?user_id` params).
- **Redundant/dead:** `backend/db/SCHEMA.md` (duplicate), `docs/STATUS.md`,
  three loose `sprint-N-summary.md` files.
- **Stranded:** `services/readiness/README.md` — the readiness formula doc
  lives outside `docs/` next to the only code in a top-level `services/` dir.
- New in this review: `docs/calculations/` (formula docs, this review's main
  deliverable), this file, and the questions file.
