# Compute worker

`backend/worker_app.py` is a standalone FastAPI app for the RAM/CPU-heavy
paths that don't need to live inside the main webapp process: Strava/Stryd
sync (pull + reconcile + stream ingest), performance backfill, and the
weekly Banister parameter refit. It runs on a separate machine (zeal-server),
listening on port 9100, and shares the same Neon Postgres as the webapp.

## Architecture

- The worker and the webapp are two independent processes hitting the same
  Neon database. There is no webapp -> worker RPC call yet — Render's UI
  still triggers the webapp's own manual sync endpoints for now. The worker
  is an additional, separately-scheduled writer.
- `backend/worker_app.py` never imports `backend.main` (which starts daemon
  threads — sleep sync, banister refit — at import time). It only imports
  `backend.db`, `backend.models`, and `backend.services.*`, and does so
  lazily inside functions/startup so importing the module never requires
  those symbols to exist yet.
- Every job run (sync, backfill, banister refit) is recorded in the
  `worker_job_runs` table via `DbRecorder`, which is the audit trail for
  what the worker has done, when, and with what result.

## Endpoints

All `/internal/*` endpoints require an `X-Worker-Secret` header matching the
`WORKER_SHARED_SECRET` env var. If that env var is unset, they return 503.
A mismatched header returns 401. `/internal/health` is unauthenticated, for
liveness probes.

### `GET /internal/health`

```bash
curl http://zeal-server:9100/internal/health
```

```json
{"status": "ok", "time": "2026-07-05T12:00:00+00:00"}
```

### `POST /internal/sync/run`

Triggers a sync for one user, or all users with the relevant credentials on
file. Runs in a background thread pool and returns immediately (202-style
body; the pool submission itself never blocks the request).

```bash
curl -X POST http://zeal-server:9100/internal/sync/run \
  -H "X-Worker-Secret: $WORKER_SHARED_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"user_id": null, "sources": ["strava", "stryd"], "full": false, "triggered_by": "manual"}'
```

```json
{"started": true, "users": 4}
```

Body fields (all optional):

| field | default | notes |
|---|---|---|
| `user_id` | `null` | sync one user; omit/null to sync all users who have a `strava_tokens` / `stryd_credentials` row for the given source |
| `sources` | `["strava", "stryd"]` | which integrations to sync |
| `full` | `false` | full resync vs incremental |
| `triggered_by` | `"manual"` | recorded on the job row (`manual` or `schedule`) |

A single-flight stale guard skips (and logs) a user+source pair if a
`worker_job_runs` row for it is already `status='running'` and started within
the last 2 hours.

### `GET /internal/jobs?limit=50`

Recent `worker_job_runs`, newest first.

```bash
curl -H "X-Worker-Secret: $WORKER_SHARED_SECRET" \
  "http://zeal-server:9100/internal/jobs?limit=20"
```

```json
[
  {
    "id": "b1f6...",
    "job_type": "strava_sync",
    "user_id": "a2c9...",
    "status": "success",
    "phase": "reconciling",
    "items_synced": 12,
    "error": null,
    "triggered_by": "schedule",
    "started_at": "2026-07-05T06:00:00+00:00",
    "finished_at": "2026-07-05T06:01:32+00:00"
  }
]
```

### `POST /internal/performance/backfill`

Runs the full performance backfill pipeline for one athlete, in the
background thread pool.

```bash
curl -X POST http://zeal-server:9100/internal/performance/backfill \
  -H "X-Worker-Secret: $WORKER_SHARED_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "a2c9..."}'
```

```json
{"started": true}
```

## Schedule

A daemon thread started on FastAPI startup drives two schedules:

- **Sync sweep**: at each `HH:MM` in `WORKER_SYNC_TIMES` (comma-separated,
  default `06:00,18:00`, interpreted in Asia/Bangkok), runs an incremental
  (`full=false`) sync for all users with Strava/Stryd credentials,
  `triggered_by="schedule"`.
- **Banister refit**: if `WORKER_BANISTER_ENABLED=1` (default), every 7 days
  runs `backend.services.banister_pipeline.run_banister_refit_pipeline` for
  all active users, wrapped in a single `worker_job_runs` row
  (`job_type='banister_refit'`, `user_id=null`, `stats` holding the
  per-user result summary). This mirrors the pattern in
  `backend/main.py`'s `_banister_refit_scheduler_loop`, but the worker owns
  it going forward — set `BANISTER_REFIT_ENABLED=0` on the webapp (Render)
  once the worker's refit is confirmed running, to avoid double-running it.

## Deploy on zeal-server

1. Clone the repo (or `git pull` an existing clone) and check out the branch
   containing this worker.
2. **Never copy a `venv/`/`.venv/` from another machine** — it hardcodes
   absolute paths and will fail with `ModuleNotFoundError: No module named
   'encodings'` or similar. Create a fresh venv per project convention:
   ```bash
   python3.12 -m venv .venv
   uv pip install --python .venv/bin/python -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in `DATABASE_URL_UAT` /
   `DATABASE_URL_PRD`, `WORKER_SHARED_SECRET`, `WORKER_PORT`,
   `WORKER_SYNC_TIMES`, `WORKER_BANISTER_ENABLED`, plus any integration
   secrets the sync/backfill/refit code paths need (Strava, Stryd, etc. —
   see the main `.env.example` sections).
4. Run migrations against the same database the webapp uses, before first
   start: `.venv/bin/alembic upgrade head`.
5. Start the worker: `bash start_worker.sh` (reads `.env`, sets
   `ENVIRONMENT`/`DATABASE_URL`, then execs uvicorn on
   `backend.worker_app:app`, port `${WORKER_PORT:-9100}`).
6. Verify: `curl http://localhost:9100/internal/health`.

## Audit trail

`worker_job_runs` (see `backend/models.py`) is the source of truth for every
job the worker has run: `job_type` (`strava_sync` / `stryd_sync` /
`backfill` / `banister_refit`), `user_id` (null for batch jobs like the
banister refit), `status` (`running` / `success` / `error`), `phase`,
`items_synced`, `error`, `triggered_by` (`manual` / `schedule`), `stats`
(JSONB, free-form per-job-type summary), `started_at`, `finished_at`. Query
it directly for ops visibility, or via `GET /internal/jobs`.
