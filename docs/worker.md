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
| `WORKER_TIMEOUT_SECONDS` | `10` | HTTP timeout (seconds) for worker calls in `http` mode. Raise on slow home-server links to avoid spurious 503s on long backfill / sync-delegation calls. Non-integer values fall back to `10`. |
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

## Sync routing, queue visibility & Garmin (Phase 3)

**Sync routing.** Full / stream-heavy syncs always go to the worker. Light
incremental syncs run in-process on the web tier by default; set
`WEB_INCREMENTAL_SYNC_ENABLED=0` to route those to the worker too (fully offload
sync from the web dyno). In http mode with no worker reachable, an incremental
falls back to in-process rather than failing.

**Queue visibility.** `GET /api/sync/status` now also reports a queued/running
pull-queue job as `pending` / `running` (source `queue`) — so the nav bar
reflects a full sync that is waiting for the worker to claim it, not just jobs
already executing. `GET /api/queue` returns the signed-in user's recent queue
rows (job type, status, attempts, timestamps, error) for the **Settings → Queue**
tab. Both are user-isolated by `payload->>'user_id'` — a user never sees another
user's rows, and batch jobs (banister_refit, no user_id) are excluded.

**Garmin scaffold.** `backend/services/garmin.py` + the worker `garmin_sync`
handler + `GET /api/garmin/status` are a placeholder for a future Garmin Connect
source. Off by default (`GARMIN_SYNC_ENABLED`); `sync_garmin` raises until the
integration is built, and every call site guards on `is_enabled()`, so a stray
`garmin_sync` job is a clean no-op while the flag is off.

Web-tier flags (Render):

| Var | Default | Purpose |
|-----|---------|---------|
| `WEB_INCREMENTAL_SYNC_ENABLED` | `1` | Run light incremental syncs in-process. `0` routes them to the worker too. |
| `GARMIN_SYNC_ENABLED` | `0` | Turn on the Garmin source (scaffold — not implemented yet). |

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
- **Daily Home Coach**: if `WORKER_DAILY_COACH_ENABLED=1` (default; falls
  back to legacy `WORKER_WEEKLY_COACH_ENABLED`), the scheduler enqueues a
  `daily_coach` job (dedupe key `daily_coach:YYYY-MM-DD`) at the same wake
  times as the sync sweep. The handler runs
  `weekly_coach_message.generate_for_user` for every active user — the warmth
  rephrase uses `LLM_COACH_ENABLED` and the provider API keys in `.env`
  (see `docs/llm-coaching.md`). After each per-user Strava/Stryd sync the
  worker also enqueues `daily_coach` for that user (dedupe per day+user).
  Render webapps only **read** `GET /api/coach/daily-message`
  (weekly-message is a compat alias). Manual:
  `POST /internal/daily-coach/run` with `X-Worker-Secret`
  (`/internal/weekly-coach/run` remains an alias).

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

### Live UAT runbook (zeal-server / Mac Mini)

The UAT stack runs on the Mac Mini (`zeal-server@100.103.104.41`, Tailscale
`zeals-mac-mini`) out of the clone at `~/dev/perf-coach/uat`, tracking `develop`
against the UAT Neon branch. Both processes read the same `.env`
(`ENVIRONMENT=uat`, `DATABASE_URL_UAT`).

| Process | Cmd | Port | Managed by | Logs |
|---|---|---|---|---|
| Webapp (`backend.main`) | `.venv/bin/uvicorn backend.main:app --port 9001` | 9001 | launchd `com.perfcoach.uat` (`RunAtLoad`, `KeepAlive` on non-zero exit) | `~/Library/Logs/com.perfcoach.uat/{stdout,stderr}.log` |
| Worker (`backend.worker_app`) | `bash start_worker.sh` | 9100 | foreground/background process (no launchd job yet) | `~/dev/perf-coach/uat/logs/worker-uat.log` |

Redeploy after a merge to develop:

```bash
ssh zeal-server@100.103.104.41
cd ~/dev/perf-coach/uat
# stop the worker
kill "$(lsof -tiTCP:9100 -sTCP:LISTEN)" 2>/dev/null
# sync + migrate
git checkout develop && git pull --ff-only
set -a; source .env; set +a; export ENVIRONMENT=uat DATABASE_URL="$DATABASE_URL_UAT"
.venv/bin/alembic upgrade head
# restart webapp (launchd) + worker
launchctl kickstart -k "gui/$(id -u)/com.perfcoach.uat"
nohup bash start_worker.sh > logs/worker-uat.log 2>&1 &
```

Health checks: `curl http://127.0.0.1:9100/internal/health` (worker) and
`curl -so/dev/null -w '%{http_code}' http://127.0.0.1:9001/api/queue` (webapp;
`401` = up and auth-gated). A healthy worker log shows `queue poll started` and
`sync scheduler started`.

The worker is **not yet a launchd service** — it does not survive a reboot or
logout. To make it persistent, add a `com.perfcoach.uat-worker` LaunchAgent
mirroring the webapp's plist (same `WorkingDirectory`, `ENVIRONMENT=uat`,
`KeepAlive`, `RunAtLoad`, `ProgramArguments` pointing at
`.venv/bin/uvicorn backend.worker_app:app --port 9100`) plus `caffeinate -s` to
keep it polling through sleep.

### Live PRD runbook (zeal-server / Mac Mini)

The PRD stack runs on the same Mac Mini as UAT but against the PRD Neon branch,
out of a **separate clone** at `~/dev/perf-coach/prd`, tracking `master`. Use a
different port (9101) so UAT and PRD workers coexist without conflict.

Both processes read the same `.env` (`ENVIRONMENT=prd`, `DATABASE_URL_PRD`).

| Process | Cmd | Port | Managed by | Logs |
|---|---|---|---|---|
| Worker (`backend.worker_app`) | `ENVIRONMENT=prd WORKER_PORT=9101 bash start_worker.sh` | 9101 | launchd `com.perfcoach.prd-worker` (target) | `~/dev/perf-coach/prd/logs/worker-prd.log` |

**Initial setup (one-time):**

```bash
ssh zeal-server@100.103.104.41
git clone https://github.com/zealchaiwut/perf-coach.git ~/dev/perf-coach/prd
cd ~/dev/perf-coach/prd
git checkout master

python3.12 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt

# Copy UAT .env and update for PRD:
cp ~/dev/perf-coach/uat/.env .env
# Edit .env: set ENVIRONMENT=prd (start_worker.sh reads this)
# The script auto-selects DATABASE_URL_PRD when ENVIRONMENT=prd.
# Set WORKER_PORT=9101 to avoid clash with UAT worker on 9100.

# Run PRD migrations (requires DATABASE_URL_PRD in .env):
set -a; source .env; set +a
export ENVIRONMENT=prd DATABASE_URL="$DATABASE_URL_PRD"
.venv/bin/alembic upgrade head
```

**Redeploy after a merge to master:**

```bash
ssh zeal-server@100.103.104.41
cd ~/dev/perf-coach/prd
# stop the worker
kill "$(lsof -tiTCP:9101 -sTCP:LISTEN)" 2>/dev/null
# sync + migrate
git checkout master && git pull --ff-only
set -a; source .env; set +a; export ENVIRONMENT=prd DATABASE_URL="$DATABASE_URL_PRD"
.venv/bin/alembic upgrade head
# restart worker
mkdir -p logs
nohup bash start_worker.sh > logs/worker-prd.log 2>&1 &
```

Health check: `curl http://127.0.0.1:9101/internal/health`
A healthy log shows `queue poll started` and `sync scheduler started`.

**After confirming the PRD worker is running:**

Switch `BANISTER_REFIT_ENABLED` from `"1"` to `"0"` in the Render dashboard
under **perf-coach-prd → Environment** (do **not** commit "0" to `render.yaml`
until the PRD worker is a persistent launchd service). This prevents the
in-process fallback and the worker from double-running the weekly refit.

To make the worker persistent across reboots, add a `com.perfcoach.prd-worker`
LaunchAgent plist (same structure as `com.perfcoach.uat-worker` but with
`WorkingDirectory ~/dev/perf-coach/prd`, `ENVIRONMENT=prd`, and
`--port 9101`) with `KeepAlive=true` and `caffeinate -s`.

## Read API (Hermes)

The worker exposes a small HTTP API on port 9100 for local consumption by
Hermes (the Mac Mini voice assistant). These routes are **not deployed to
Render** and must never be reachable from the public internet — the tailnet /
localhost binding is the security boundary.

Most routes are read-only (GET), with one authenticated write route
(`POST /feel-entry`) for Hermes to log session-feel/RPE data.

### Shared conventions

**User resolution** — every endpoint accepts an optional `?user=<username>`
query param. Resolution order:
1. Explicit `?user=<username>` → that user (by username)
2. `WORKER_READ_API_USER` env var → that user
3. Exactly one active user exists → use it
4. Else → **400**

**Date defaults** — `?date=` params default to today in Asia/Bangkok
(matching the existing worker scheduler timezone). Pass `YYYY-MM-DD`.

**All GET routes require `Authorization: Bearer $WORKER_API_TOKEN`** — the same
token the write routes use. Requests without it get `401`; if the variable is
unset on the worker the API answers `503` rather than serving anything.

> **Changed 2026-07-31 (issue #1601).** These routes previously required no auth
> at all, justified as "the tailnet/localhost binding is the access boundary".
> That was not what shipped: this document reaches the service at
> `http://zeal-server:9100`, a hostname on the tailnet rather than loopback, so
> anyone able to route to the port could read any athlete's weight, training
> load and plan by passing `?user=<username>`.
>
> **Hermes must now send the bearer header on GETs as well as POSTs.** It will
> receive 401s until updated.
>
> Still open: the token is a *service* credential. It proves the caller is
> Hermes, never which athlete — a token holder can still select any user via
> `?user=`. Per-user tokens are tracked in #1601's remaining scope.

### `POST /feel-entry`

Insert a feel/RPE entry into `workout_feel`. Guarded by a static bearer token
so external orchestrators (Hermes) can write feel data without touching the
webapp's own auth flow.

**Auth:** `Authorization: Bearer <token>` where `<token>` is the value of the
`WORKER_API_TOKEN` environment variable on the worker. Requests with a missing
or incorrect token receive **401**.

**User resolution:** same chain as the read API — optional `?user=<username>`
query param, then `WORKER_READ_API_USER` env var, then single active user.

**Request body (JSON):**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `feel_date` | string (YYYY-MM-DD) | **yes** | Date of the session feel |
| `rpe_1_to_10` | integer 1–10 | no | Perceived exertion; out-of-range → 400 |
| `notes` | string ≤ 10,000 chars | no | Free-text note; exceeding cap → 400 |

At least one of `rpe_1_to_10` or `notes` must be present; omitting both → 400.

**Auto-link:** after insert the handler runs the same `auto_link_feel_entries`
logic as the webapp — if exactly one workout exists for the user on `feel_date`,
the new row is linked to it automatically. If no same-day workout exists the
row is still inserted successfully with `workout_id: null`.

**Responses:**
- `201` — row inserted; body contains the full record (at minimum `id`)
- `400` — validation error (`feel_date` missing, RPE out of range, notes too long, neither field supplied)
- `401` — missing or wrong bearer token
- `503` — `WORKER_API_TOKEN` env var not configured on the worker

**Example:**

```bash
curl -X POST http://localhost:9100/feel-entry \
  -H "Authorization: Bearer $WORKER_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"feel_date": "2026-07-14", "rpe_1_to_10": 7, "notes": "Felt strong on intervals"}'
```

```json
{
  "id": "b1f62c3d-...",
  "user_id": "a2c9...",
  "feel_date": "2026-07-14",
  "workout_id": "d3e8...",
  "rpe_1_to_10": 7,
  "notes": "Felt strong on intervals",
  "created_at": "2026-07-14T11:30:00+00:00"
}
```

### `POST /weight-entry`

The lean program's daily floor — a morning weigh-in replied over Discord. Same
bearer-token auth and user-resolution chain as `/feel-entry`.

Body: `weight_kg` (required, 20–300), `entry_date` (optional ISO, defaults to
today in Bangkok, must not be in the future), `notes` (optional, ≤ 500 chars).

**Upserts on `(user, date)`** with a null `entry_time`, so replying twice in one
morning corrects the number rather than creating a second row — `created` in the
response says which happened. Entries are stored with `source='imported'`, and
the weigh-in habit (`auto_fill_source='weight.logged'`) is recomputed for that
week so it ticks with no tap. That autofill is best-effort: a habit that failed
to tick never costs the athlete the weigh-in.

```bash
curl -X POST http://localhost:9100/weight-entry \
  -H "Authorization: Bearer $WORKER_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"weight_kg": 87.6}'
```

```json
{
  "id": "9c41ab77-...",
  "user_id": "a2c9...",
  "entry_date": "2026-07-30",
  "weight_kg": 87.6,
  "notes": null,
  "created": true
}
```

### `GET /api/weight/nudge`

The morning weight nudge for Hermes to deliver over Discord. Read-only, no token
(same boundary as the other `/api/weight/*` reads).

**perf-coach never talks to Discord** — Hermes polls this and delivers only when
`deliver_now` is true, mirroring the `plan_draft_notify` contract above.
`deliver_now` requires the BKK morning window (06:00–08:00, deliberately earlier
than the 07:00–09:00 draft window), today not already logged, and the tracking
state's cadence: daily while ACTIVE, Mondays only once PAUSED.

There is exactly **one message type and it is weight-only** — never food. Silence
is the correct output most mornings and the endpoint says so rather than
inventing something to say. `ack` is accepted for symmetry with the draft notify;
the weight nudge needs no pending flag because "already logged today" is the
natural, self-clearing acknowledgement.

```json
{
  "tracking_state": "active",
  "paused_since": null,
  "nudge_cadence": "daily",
  "logged_today": false,
  "last_weigh_in": "2026-07-29",
  "days_since_last": 1,
  "in_window": true,
  "deliver_now": true,
  "message": "morning — what's the number?",
  "acked": false
}
```

**Worker env var:**

| Var | Default | Purpose |
|-----|---------|---------|
| `WORKER_API_TOKEN` | _(unset)_ | Static bearer token for the ENTIRE Hermes API — all six `/api/*` GET routes plus `POST /feel-entry` and `POST /weight-entry`. Requests fail with 503 if unset (fails closed). |

### `GET /api/training/load`

CTL/ATL/TSB/ACWR + persisted verdict for the day. Reads from
`training_load_snapshots` and `verdict_history` — no recomputation.
If no snapshot exists for the requested date, returns the latest row ≤
that date (with its actual `snapshot_date`); 404 only if the user has no
snapshots at all. Verdict is `null` if no row exists for the date.

```bash
curl "http://localhost:9100/api/training/load?date=2026-07-13"
```

```json
{
  "date": "2026-07-13",
  "snapshot_date": "2026-07-13",
  "ctl": 54.2,
  "atl": 61.8,
  "tsb": -7.6,
  "acwr": 1.14,
  "verdict": "hold",
  "verdict_date": "2026-07-13"
}
```

### `GET /api/scores`

Current Endurance and Speed scores with a 7-day trend (`up` / `flat` /
`down`) for Hermes. Reads from `performance_score_history` only — never
recomputes. Returns HTTP 404 when the user has no score history rows.

Restored 2026-08 (the earlier "never implemented" strike was wrong once the
route landed in `worker_app.py`).

```bash
curl -H "Authorization: Bearer $WORKER_API_TOKEN" \
  "http://localhost:9100/api/scores"
```

```json
{
  "as_of": "2026-07-13",
  "formula_version": "2026-06-endurance-v1",
  "endurance": {"value": 62.4, "trend": "up"},
  "speed": {"value": 55.1, "trend": "flat"}
}
```

### `GET /api/plan/today`

Today's planned session(s) from `planned_sessions`, or an explicit empty
state. Date defaults to today (Asia/Bangkok). Returns HTTP 200 in all
cases — `"planned": false` when no row exists so Hermes always gets a
narratable answer. Multiple sessions on one date are returned as a list
under `"sessions"`.

```bash
curl "http://localhost:9100/api/plan/today"
```

Example — planned run day:

```json
{
  "plan_date": "2026-07-13",
  "planned": true,
  "sessions": [
    {
      "session_type": "run",
      "name": "Easy aerobic run",
      "target": { "distance_km": 8.0, "duration_min": 50, "intensity": "easy" },
      "note": "Keep HR in zone 2",
      "status": "pending"
    }
  ]
}
```

Example — no session planned:

```json
{
  "plan_date": "2026-07-13",
  "planned": false,
  "session_type": null,
  "sessions": []
}
```

### `GET /api/weight/recent`

Last N weigh-ins (default 14, clamped 1–90) from `weight_entries`, newest
first. Includes the latest EWMA value and a trend over the window
(`up`/`flat`/`down`, ±0.1 kg dead-band). EWMA computed via the shared
`backend/services/weight_ewma.py` helper — same smoothing as the dashboard
weight chart. Returns HTTP 200 with `entries: []` when the user has no
weigh-ins (`last_logged` and `ewma` are null).

```bash
curl "http://localhost:9100/api/weight/recent?n=7"
```

```json
{
  "entries": [
    { "date": "2026-07-13", "time": "07:12", "weight_kg": 68.4 },
    { "date": "2026-07-12", "time": "07:08", "weight_kg": 68.6 },
    { "date": "2026-07-11", "time": "07:15", "weight_kg": 68.5 }
  ],
  "count": 3,
  "last_logged": "2026-07-13",
  "ewma": 68.47,
  "trend": "down"
}
```

### `GET /api/weight/status`

The weight block consumed by the Hermes coaching brief exporter
(`scripts/export_brief.py`) in a single round trip — deliberately more than
`/api/weight/recent` above, which is a raw recent-entries view. All
computation lives in `backend/services/weight_plan.py`
(`compute_weight_status`, `compute_current_pace_kg_per_week`,
`compute_required_pace_kg_per_week`, `compute_on_track`) — DB-read, no LLM/
model calls anywhere in this path.

**`current_kg` is always a 7-day rolling average of `weight_entries.weight_kg`
— never a single day's weigh-in.** It falls back to the average of whatever
readings exist in a wider (~55 day) lookback when fewer than 2 entries fall
in the trailing 7 days, and to `null` when the user has no weigh-ins at all.
`trend_7d` / `trend_28d` are window-average deltas (current N-day average
minus the immediately preceding N-day average, in kg) — same rule, never a
day-over-day delta.

`target_kg` / `target_date` / `pace_kg_per_week` / `on_track` /
`projection_date` all come from the user's active `weight_targets` row (the
same one the webapp's `GET /api/weight-targets/active` reads) and are `null`
when there is no active target. `on_track` compares `pace_kg_per_week`
against the pace required to hit `target_date` on time, direction-aware for
loss vs. gain targets. `projection_date` reuses the existing
`weight_plan.project_hit_date` extrapolation (7-day pace) and is `null` when
pace is flat, insufficient, or moving away from the goal.

Returns HTTP 200 in every case — zero weigh-ins and/or no active target are
unremarkable, expected states for a headless client and must never error.

```bash
curl "http://localhost:9100/api/weight/status?date=2026-07-13"
```

```json
{
  "current_kg": 68.5,
  "trend_7d": -0.3,
  "trend_28d": -1.1,
  "target_kg": 65.0,
  "target_date": "2026-09-01",
  "pace_kg_per_week": 0.32,
  "on_track": true,
  "projection_date": "2026-08-25"
}
```

`pace_kg_per_week` follows the same sign convention as the rest of this
module: positive means losing weight, negative means gaining. For a loss
target (as above), a positive pace at or above the required rate is
`on_track: true`; for a gain target, a sufficiently negative pace is
`on_track: true`.

Example — no weigh-ins and no active target:

```json
{
  "current_kg": null,
  "trend_7d": null,
  "trend_28d": null,
  "target_kg": null,
  "target_date": null,
  "pace_kg_per_week": null,
  "on_track": null,
  "projection_date": null
}
```

## Audit trail

`worker_job_runs` (see `backend/models.py`) is the source of truth for every
job the worker has run: `job_type` (`strava_sync` / `stryd_sync` /
`backfill` / `banister_refit`), `user_id` (null for batch jobs like the
banister refit), `status` (`running` / `success` / `error`), `phase`,
`items_synced`, `error`, `triggered_by` (`manual` / `schedule`), `stats`
(JSONB, free-form per-job-type summary), `started_at`, `finished_at`. Query
it directly for ops visibility, or via `GET /internal/jobs`.
