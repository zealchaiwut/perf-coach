# 2026-07-08 — Smart worker, lean web (Phases 1–3)

Moved perf-coach's heavy paths off the web request and behind a Neon-backed pull
queue the compute worker claims. Landed on `develop` as merge `52be2ea` (PRs
#1325 → #1326 → #1327). Full reference: `docs/worker.md`.

## Phase 1 — Neon pull queue (#1325)

- New `job_queue` table (migration `458e1a9d8783`) + `backend/services/job_queue.py`.
  The worker claims rows with `SELECT … FOR UPDATE SKIP LOCKED`; both the web tier
  and the worker connect **outbound to Neon only**, so the worker sits behind home
  NAT with no inbound port. Render no longer pushes to zeal-server.
- `WORKER_TRIGGER_MODE` (default `queue`, `http` = legacy push). Enqueue is a DB
  insert, so an offline worker leaves the job `queued` instead of failing the
  request. Lease + heartbeat + `requeue_stale` recover jobs after a crash/sleep;
  `dedupe_key` prevents double-enqueue; retries up to `max_attempts`.

## Phase 2 — worker precompute (#1326)

- The worker warms the training-load snapshot (`precompute` job) so the web request
  never pays the 180-day EWMA `daily_update`. Workout writes and post-sync both
  enqueue a precompute; `current_load()` still falls back to an inline recompute if
  it reads before the worker catches up.
- Reused the existing `training_load_snapshots` cache — no new snapshot tables
  (performance already caches in `summary_cache`; projections are cheap once load
  is warm). Flags `PRECOMPUTE_ON_WRITE_ENABLED`, `PRECOMPUTE_AFTER_SYNC_ENABLED`,
  `LOAD_READ_FROM_SNAPSHOT` (all default on).

## Phase 3 — routing, visibility, Garmin scaffold (#1327)

- Sync routing: full/stream-heavy syncs always go to the worker; incremental runs
  in-process unless `WEB_INCREMENTAL_SYNC_ENABLED=0`.
- `GET /api/sync/status` unions the queue (`pending`/`running`); new `GET /api/queue`
  (user-isolated) backs a **Settings → Queue** tab.
- Garmin source scaffold (`GARMIN_SYNC_ENABLED`, default off; not implemented yet).

## Verification

- 59 tests pass against UAT Postgres (`test_job_queue__pull_queue`,
  `test_precompute__phase2`, `test_queue_endpoints__phase3`, `test_route_heavy_paths_to_worker__1297`).
- Deployed live to zeal-server UAT (webapp :9001 via launchd `com.perfcoach.uat`,
  worker :9100); queue poll loop confirmed active and claiming jobs end-to-end.
