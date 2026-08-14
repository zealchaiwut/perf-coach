# Sync Architecture

## Heavy-path delegation (issue #1297)

`POST /api/strava/sync` and `POST /api/stryd/sync` with `full=true` are
delegated to the compute worker (`/internal/sync/run`) when `WORKER_BASE_URL`
is set. Incremental syncs (`full=false` or omitted) continue to run in-process.

The worker records job progress in `worker_job_runs` (shared Neon DB).
`GET /api/sync/status` checks `worker_job_runs` when no in-process job exists,
so the nav status bar shows progress for delegated syncs.

See `docs/worker.md` → "Webapp delegation config" for env vars and
worker-unreachable behavior.

## One-job-per-user model

Each user has at most one active sync job at a time. Jobs are stored in an
in-memory dict (`backend/services/sync_jobs.py::_registry`) keyed by
`user_id`. Starting a new job while one is already `running` raises
`SyncInProgress`, which the endpoint converts to a 409 response.

When a job finishes (success or error) it remains in the registry so the
frontend can read the final status. The next sync call replaces it with a
fresh job.

## Job phases

A job moves through up to three phases, written to `job["phase"]`:

| Phase | Description |
|---|---|
| `pulling_strava` | Fetching pages of activities from the Strava API. |
| `pulling_stryd` | Fetching activities from the Stryd API. |
| `reconciling` | Merging raw provider activities into the `workouts` table via `backend/services/reconcile.py`. |

The phase is `None` before the first `set_phase` call and remains at the
last phase after the job completes.

## 409 single-flight guard

`sync_jobs.start()` acquires `_lock` and checks whether an existing job for
that user has `status == "running"`. If so it raises `SyncInProgress` and the
worker thread is never spawned. This prevents duplicate background threads for
the same user.

The guard is in-process only. If the server restarts, all in-memory jobs are
lost (see below).

## Status lost on restart — re-syncing is safe

Job state lives entirely in `_registry` (a plain Python dict). On process
restart the dict is empty, so all in-flight status is gone. A user whose
sync was interrupted mid-run will see `idle` as if no sync ever happened.

Re-running a sync is safe because every upsert uses
`ON CONFLICT DO UPDATE`. Strava activities conflict on `strava_activity_id`;
Stryd activities conflict on `stryd_activity_id`. Running the same sync
twice inserts missing rows and updates changed fields — it never creates
duplicates.

## Global status bar

`frontend/js/nav.js` injects a `#sync-status-bar` element into every page
that loads the nav. The bar is hidden by default and becomes visible when a
sync is running or has recently completed.

The bar polls `GET /api/sync/status` on a 3-second interval while a sync is
`running` or `pending` (queued on the worker). On success or error it shows
the final state for a few seconds then hides itself. Dismiss (`×`) while a
job is in flight hides the bar but **keeps polling**; the bar returns on
error (or success).

Individual pages (e.g. Training Log) subscribe to the same
`frontend/js/lib/sync-poller.js` instance. Do not start a second timer.

## Polling cadence

| Context | Interval |
|---|---|
| Shared poller (`sync-poller.js`) | 3 000 ms |

Polling stops automatically once the job status leaves `running`/`pending`.
`waitForIdle()` also treats `pending` as in-flight, so sequential
Strava → Stryd syncs do not start the second provider early.

## Compute worker (scheduled syncs on zeal-server)

Everything above describes the webapp's user-triggered sync. The same sync
core also runs on the standalone compute worker (`backend/worker_app.py`,
port 9100 on zeal-server) — the shared implementation lives in
`backend/services/sync_runner.py` behind a `SyncRecorder` protocol:

| | Webapp (`main.py`) | Worker (`worker_app.py`) |
|---|---|---|
| Trigger | User clicks sync (`POST /api/strava/sync`) | Schedule (`WORKER_SYNC_TIMES`, default 06:00/18:00 BKK) or manual `POST /internal/sync/run` |
| Job state | In-memory registry (`sync_jobs.py`), lost on restart | `worker_job_runs` DB table (persistent audit trail) |
| Single-flight | 409 per user via registry lock | Lock + 2h stale-guard query on `worker_job_runs` |
| Scope | Session user only | One user or all connected users |

Both paths are safe to overlap because every upsert is idempotent
(`ON CONFLICT DO UPDATE`) — worst case is duplicate work, not duplicate data.
Full worker reference (endpoints, auth, deploy): `docs/worker.md`.
