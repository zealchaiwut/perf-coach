# Sync Architecture

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

The bar polls `GET /api/sync/status` on a 4-second interval while a sync is
running. On success or error it shows the final state for a few seconds then
hides itself.

Individual pages (e.g. Training Log) may run their own poll on a shorter
interval (3 seconds) while the sync dialog is open. Both pollers use the
same endpoint and are independent.

## Polling cadence

| Context | Interval |
|---|---|
| Nav status bar (`nav.js`) | 4 000 ms |
| Training Log page (`training-log.js`) | 3 000 ms |

Polling stops automatically once the job status leaves `running`.
