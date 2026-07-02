# Prompt: Performance Fixes

> Paste everything below this line into Claude Code, run from the perf-coach
> repo root on a fresh branch off `develop`.

---

You are working on perf-coach (FastAPI + SQLAlchemy + Postgres/Neon,
vanilla-JS frontend, no bundler). Read `CLAUDE.md` first. Source of truth:
`docs/reviews/2026-07-architecture-review.md` §4–§5 and
`docs/calculations/README.md` caching table. Line anchors from branch
`review/architecture-docs-2026-07`; re-locate before editing.

Create branch `perf/hot-paths` off `develop`. One commit per task. Behavior
must not change — same response shapes, same numbers — only cost. Add a test
or measurement note per task.

## Task 1 — `current_load` should read the snapshot cache

`backend/services/training_load.py:175-203` (`current_load`) rebuilds the full
180-day TSS series + EWMA per call, ignoring the `training_load_snapshots`
table that `daily_update` maintains. It is called per-request from
`GET /api/training-load/current` (main.py ~11302), the readiness CTL branch
(~8170, 8229), the plan router projection (`routers/plan.py:~422,435`), and
taper/monthly/projection endpoints (~13258-13327, 15138, 15553).

Fix: make `current_load` read today's (or the latest) row from
`training_load_snapshots` when present and fresh (snapshot_date == today for
that user); fall back to the live recompute when missing, and upsert the
result via the existing `daily_update` path so the next call hits. Keep the
function signature; callers unchanged.

Test: seed snapshots, assert only 1 lightweight query on the hot path;
assert identical values vs the recompute path.

## Task 2 — Persist `readiness/range` recomputes

`GET /api/readiness/range` (main.py ~8100-8131) recomputes every missing day
per request — O(days) computations each with its own history query — and
throws the results away.

Fix: after computing a missing day, persist it through the same upsert the
canonical pipeline uses (`services/readiness/job.py` upsert on
(user_id, date)), so subsequent range calls are pure reads. Batch the
baseline-history query across the range instead of per-day if straightforward.

## Task 3 — Plan bundle: cheaper signature + fix the N+1

`_plan_signature` (main.py ~14788-14840) issues 5 aggregate queries on every
request even on cache hits — combine into one SELECT with scalar subqueries.
`_compute_plan_bundle` (~14902-15021) calls `get_race_readiness` per upcoming
race (~14974), each re-running `current_load`-class work — after Task 1 this
mostly collapses; additionally hoist the shared per-user data (load, prefs)
out of the per-race loop and pass it in.

## Task 4 — Stop refetching full history on `/log`

`frontend/js/training-log.js` requests
`GET /api/training-log?from=2010-01-01...` on load AND re-invokes
`fetchAndRender()` after every sync completion, edit, delete, and restore
(15+ call sites, e.g. ~3726, 3896, 4017, 4205, 4291) — re-downloading
multi-year history each time.

Fix (keep client-side filtering per issue #637 — do NOT paginate the API in
this task): after single-workout mutations, patch the in-memory list from the
mutation response (the API already returns the updated workout dict) and
re-render, instead of full refetch. Keep full refetch ONLY for sync
completion and restore-from-trash. This removes the bulk of the refetches
without changing the API.

## Task 5 — Update charts in place

`training-log.js` ~837/867 destroys and recreates the volume Chart.js
instance on every fetch (including after a single edit); `trends.js`
~1095-1098 tears down four charts on each range change.

Fix: keep chart instances; assign new `chart.data.labels`/`datasets` and call
`chart.update()`. Destroy only on teardown. Verify no duplicate-canvas or
legend-flicker regressions.

## Task 6 — One sync-status poller

Five independent `/api/sync/status` pollers exist: `nav.js:~472` (4s interval,
starts on EVERY page load even when no sync runs), `training-log.js:~3737`
(3s) and ~3794 (a second promise-based 2s loop in the same file),
`settings.html:~2613` and ~3137 (two inline near-copies, 2s).

Fix: extract one shared poller module `frontend/js/lib/sync-poller.js`
(no-bundler pattern — plain script exposing a global, like
`lib/training-format.js`): start-on-demand (only poll while a sync is
running or just started), subscriber callbacks, single interval. Replace all
five call sites. nav.js should subscribe, not poll unconditionally — do one
initial status check on load, then poll only if a job is active.

## Task 7 — Deduplicate `/api/auth/me`

Fetched independently by user.js:~15, nav.js:~513, home.js:~1287,
training-plan.js:~151 (+projection.js if it still exists) — 2–3 identical
calls per page view.

Fix: cache the promise in one shared helper (add to the same `lib/` module or
`user.js` global): first caller fetches, everyone else awaits the same
promise. No TTL needed within a page view.

## Task 8 — Parallelize the home waterfall

`home.js:~1287-1305`: `await /api/auth/me` then `await /api/home/summary`,
but summary doesn't need the user id. Fire both with `Promise.all`.

## Task 9 — Declare hot indexes in models.py

Composite indexes (`ix_workouts_user_id_workout_date`, user+date indexes on
strava/stryd activities, snapshots, metrics) exist only in old migrations,
not in `backend/models.py` `__table_args__` — drift risk for fresh
environments. Add the matching `Index(...)` declarations to models.py (no new
migration needed — they already exist in the DB; verify names match exactly
so autogenerate stays quiet). Add a `(user_id, date)` index declaration+
migration for `daily_readiness`, which has none (models.py ~594-609) and is
queried per-day per-user everywhere.

## Explicitly OUT of scope (separate decisions/branches)

- Splitting main.py into routers (questions file Q15).
- Retiring sync System B / per-activity commits in strava_sync.py (Q14).
- training-log.html inline-CSS extraction and settings.html inline-JS
  externalization (Q19) — big diffs, separate ticket.
- `_DAILY_RECONCILE_LIMIT` raise — touches sync semantics.
- Persisting score history / `/performance` caching — design pending (Q12).

## Finish

- Run full test suite; manually exercise /log (edit a workout — no full
  reload flash), /home, /trends, /settings sync buttons.
- Summary per task: what changed, before/after cost (query counts or payload
  sizes where measurable).
