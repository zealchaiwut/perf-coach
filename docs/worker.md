# Compute worker

`backend/worker_app.py` is a standalone FastAPI app for the RAM/CPU-heavy
paths that don't need to live inside the main webapp process: Strava/Stryd
sync (pull + reconcile + stream ingest), performance backfill, and the
weekly Banister parameter refit. It runs on a separate machine (zeal-server),
listening on port 9100, and shares the same Neon Postgres as the webapp.

## Architecture

- The worker and the webapp are two independent processes hitting the same
  Neon database. Heavy paths (full syncs, backfill) are **delegated** from
  the webapp to the worker. As of the pull-queue migration (Phase 1), the
  default trigger is a **Neon-backed job queue**: the webapp inserts a `queued`
  row and the worker claims it — no HTTP from Render to zeal-server. See
  [Trigger mode](#trigger-mode-pull-queue-vs-http-push) below. The legacy HTTP
  push (`/internal/sync/run`, `/internal/performance/backfill`) is still present
  behind `WORKER_TRIGGER_MODE=http` for local dev / rollback.
  Incremental syncs still run in-process (bounded, fast).
- `backend/worker_app.py` never imports `backend.main` (which starts daemon
  threads — sleep sync, banister refit — at import time). It only imports
  `backend.db`, `backend.models`, and `backend.services.*`, and does so
  lazily inside functions/startup so importing the module never requires
  those symbols to exist yet.
- Every job run (sync, backfill, banister refit) is recorded in the
  `worker_job_runs` table via `DbRecorder`, which is the audit trail for
  what the worker has done, when, and with what result.
- The webapp's `GET /api/sync/status` checks `worker_job_runs` (shared DB) for
  recent delegated jobs when no in-process job is active, so the nav sync
  status bar shows progress for worker-delegated syncs without new infra.

## Trigger mode: pull queue vs HTTP push

`WORKER_TRIGGER_MODE` (webapp env) selects how heavy paths reach the worker:

- **`queue` (default)** — the webapp `enqueue()`s a row in the Neon `job_queue`
  table (`backend/services/job_queue.py`); the worker's poll loop claims it with
  `SELECT … FOR UPDATE SKIP LOCKED`. **Both machines only connect OUTBOUND to
  Neon**, so the worker can sit behind home NAT with no inbound port, no tunnel,
  no `WORKER_BASE_URL`. Enqueue is a cheap DB insert, so an offline worker no
  longer fails the request — the job just waits in `queued` and runs when the
  worker wakes.
- **`http`** — the legacy push path (`worker_client._post` → `/internal/*`).
  Requires `WORKER_BASE_URL` + `WORKER_SHARED_SECRET` and inbound reachability.
  Kept for local dev and rollback.

The `job_queue` table is separate from `worker_job_runs`: the queue is the
**work list** (queued → running → done/failed, with lease + attempts), while
`worker_job_runs` stays the **execution audit trail**. A claimed queue row is
linked to its audit row via `worker_job_run_id`.

### Lifecycle & recovery

- **Claim + lease**: `claim_next` flips one `queued` row to `running`, stamps
  `claimed_by` + `lease_expires_at` (now + `QUEUE_LEASE_SECONDS`), and bumps
  `attempts`. A 60s heartbeat extends the lease while a long job runs.
- **Crash / sleep recovery**: `requeue_stale` (run at the top of every poll)
  returns any `running` row whose lease has expired to `queued` (if attempts
  remain) or marks it terminally `failed`. This is what makes killing the worker
  mid-job safe — on restart the job is reclaimed and re-run. Because every
  upsert in the sync/backfill code is idempotent (`ON CONFLICT DO UPDATE`), a
  re-run is safe.
- **Dedupe**: `enqueue(dedupe_key=…)` skips insertion when an active
  (queued/running) row already shares the key, mirroring the worker's existing
  single-flight intent (`<source>_sync:<user_id>`). Double-clicking Sync does
  not double-enqueue.
- **Retries**: `fail(retryable=True)` requeues until `attempts == max_attempts`
  (default 3), then terminal `failed`. No-handler jobs fail non-retryably.

## Webapp delegation config

Set these env vars on the Render webapp service (not the worker):

| Var | Default | Purpose |
|-----|---------|---------|
| `WORKER_TRIGGER_MODE` | `queue` | `queue` = enqueue a `job_queue` row (default, NAT-friendly). `http` = POST to the worker (needs `WORKER_BASE_URL`). |
| `WORKER_BASE_URL` | _(unset)_ | Worker base URL for `http` mode, e.g. `http://zeal-server:9100`. Not needed in `queue` mode. |
| `WORKER_SHARED_SECRET` | _(unset)_ | Same secret as the worker's `WORKER_SHARED_SECRET` (`http` mode only). |
| `ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS` | `0` | Set `1` to allow in-process fallback when the worker is down (`http` mode). **Off by default** — an unreachable worker returns 503. In `queue` mode there is nothing to fall back from: enqueue always succeeds. |
| `ROUTE_BACKFILL_FALLBACK_TO_INPROCESS` | `0` | Same for backfill. |
| `LEGACY_SYNC_STRAVA_ENABLED` | `0` | Set `1` to re-enable the deprecated `POST /api/sync/strava` BackgroundTasks endpoint. Disabled (410) by default. |

Worker-side poll config (set on the worker, not Render):

| Var | Default | Purpose |
|-----|---------|---------|
| `QUEUE_POLL_ENABLED` | `1` | Set `0` to stop the worker claiming queued jobs (HTTP push still works). |
| `QUEUE_POLL_INTERVAL_SECONDS` | `5` | Sleep between polls when the queue is empty (drains back-to-back while jobs remain). |
| `QUEUE_LEASE_SECONDS` | `600` | Lease length per claim; the heartbeat re-extends it every 60s. A crashed worker's jobs are reclaimed once the lease lapses. |

### Worker-unreachable behavior

In `queue` mode this section does not apply: enqueue is a DB insert that always
succeeds, and an offline worker just leaves the job `queued` until it wakes. The
following is `http` mode only.

When `WORKER_BASE_URL` is set but the worker is unreachable:
- `POST /api/strava/sync?full=true` and `POST /api/stryd/sync?full=true` → **503**
- `POST /api/performance/backfill` → **503**
- Background threshold-save trigger → logs a warning and skips (does not block the HTTP response)

Set `ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS=1` or `ROUTE_BACKFILL_FALLBACK_TO_INPROCESS=1`
only as a temporary safety net — it runs the heavy path in the web dyno, which defeats
the purpose of the worker.

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

## Precompute: warm caches on the worker (Phase 2)

The heaviest recompute on the web path is `training_load.daily_update()` — a
180-day EWMA rebuild — run both when a workout is written and, as a fallback,
when `current_load()` reads a missing/stale `training_load_snapshots` row. Phase 2
moves that work to the worker via a `precompute` queue job so the web request
stays fast:

- **On workout write** (create / edit / delete / duplicate), the web tier calls
  `worker_client.delegate_precompute(user_id, dates=[...])`, which enqueues a
  `precompute` job (deduped `precompute:<user_id>`) instead of recomputing
  inline. Gated by `PRECOMPUTE_ON_WRITE_ENABLED` (default on). In http mode, or
  if enqueue fails, it falls back to the inline `daily_update` (prior behavior).
- **After a sync**, each per-user `*_sync` handler enqueues a `precompute` for
  that user (`PRECOMPUTE_AFTER_SYNC_ENABLED`, default on), so the first
  post-sync dashboard load is a pure cache hit rather than paying the recompute.
- **The worker** runs `backend/services/precompute.py::precompute_user`, warming
  today + yesterday (+ any edited dates) in `training_load_snapshots`.

Safety: `current_load()` still falls back to an inline recompute when it reads
before the worker has caught up, so a brief lag is correct, just slightly slower.
`LOAD_READ_FROM_SNAPSHOT` (default on) can force `current_load` to always
recompute inline (debug / rollback) — always safe, since inline is the same path
taken on a cache miss. Performance scores and the weekly/monthly summaries keep
their existing inline-on-miss `summary_cache` (signature-invalidated); the
form/weight projections are cheap once the load snapshot is warm, so neither
grew a new snapshot table.

Web-tier flags (Render):

| Var | Default | Purpose |
|-----|---------|---------|
| `PRECOMPUTE_ON_WRITE_ENABLED` | `1` | Offload the workout-write load recompute to the worker (queue mode). `0` = recompute inline. |
| `LOAD_READ_FROM_SNAPSHOT` | `1` | `current_load()` reads the snapshot cache. `0` = always recompute inline. |

Worker-tier flag:

| Var | Default | Purpose |
|-----|---------|---------|
| `PRECOMPUTE_AFTER_SYNC_ENABLED` | `1` | Enqueue a `precompute` after each per-user sync so the snapshot is warm before the user looks. |

## Poll loop & schedule

On FastAPI startup the worker starts **two** daemon threads:

- **`worker-queue-poll`** (queue mode) — every `QUEUE_POLL_INTERVAL_SECONDS`
  it runs `requeue_stale()` then `claim_next()`; a claimed job is dispatched
  through the same handlers as the HTTP path (`strava_sync` / `stryd_sync` /
  `backfill` / `banister_refit`) on the thread pool, then `complete()`/`fail()`.
  It drains back-to-back while jobs remain, then sleeps.
- **Scheduler** — drives the timed sweeps below. In queue mode the scheduler
  **enqueues** rows (it no longer calls the sync code directly), so scheduled and
  on-demand work flow through the one queue and share its dedupe + lease.

Timed schedules:

- **Sync sweep**: at each `HH:MM` in `WORKER_SYNC_TIMES` (comma-separated,
  default `06:00,18:00`, interpreted in Asia/Bangkok), enqueues an incremental
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

### Reliability on zeal-server (queue mode)

The pull queue only self-heals if the worker process is actually alive to poll,
so keep it running across logouts and sleep:

- **launchd, not a login shell.** Run the worker as a `launchd` LaunchAgent (or
  LaunchDaemon) with `KeepAlive=true` so macOS restarts it on crash or reboot.
  A `tmux`/terminal session dies on logout and won't come back — use it only for
  attended debugging.
- **Stop the Mac sleeping the process.** Under `caffeinate -s` (or Energy Saver
  "Prevent automatic sleeping"/"Wake for network access") the poll loop keeps
  ticking. If the Mac does sleep mid-job, the lease lapses and `requeue_stale`
  re-queues the job on wake — correct, just delayed.
- **`QUEUE_POLL_ENABLED=1`** must be set on the worker (default) or it will never
  claim queued jobs. `WORKER_BASE_URL` is **not** required in queue mode.
- **Neon scale-to-zero.** A free/scale-to-zero Neon branch parks the compute
  after idle; the first poll after a park pays a cold-start (a few hundred ms to
  low seconds) and may transiently error — the loop simply retries next tick, so
  it's harmless. On the busy shared UAT/PRD branch this rarely triggers. If cold
  starts become noticeable, raise `QUEUE_POLL_INTERVAL_SECONDS` (fewer wakeups)
  or disable scale-to-zero on that branch.
- **One worker per environment.** `SKIP LOCKED` makes multiple workers safe (no
  two claim the same row), but run a single worker per DB unless you deliberately
  want horizontal fan-out.

## Audit trail

`worker_job_runs` (see `backend/models.py`) is the source of truth for every
job the worker has run: `job_type` (`strava_sync` / `stryd_sync` /
`backfill` / `banister_refit`), `user_id` (null for batch jobs like the
banister refit), `status` (`running` / `success` / `error`), `phase`,
`items_synced`, `error`, `triggered_by` (`manual` / `schedule`), `stats`
(JSONB, free-form per-job-type summary), `started_at`, `finished_at`. Query
it directly for ops visibility, or via `GET /internal/jobs`.
