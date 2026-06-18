# perf-coach

Personal performance dashboard. Tracks weight, habits, readiness, training log, and performance trends.

## Features

- **Weight tracking** — daily log; gradient-design weight page with two-card hero (current weight + log-today); custom SVG trend chart with range tabs (7D / 30D / 90D / 6M / 1Y / All); plan overlay, milestones, projected goal-hit date (7-day pace), and slide-in target-edit panel; `/weight/targets` removed — target editing is now inline on the weight page; logging streak badge and 14-day adherence counter shown below the hero; mobile touch: tap-to-reveal tooltip on chart, persistent labels for current weight, plan, gap, and milestone values
- **Habit tracking** — redesigned habits page with gradient design language; 7-segment week wheel, tap-to-check daily grid with day-score footer row, weekly habits progress bars with auto-sync badges; auto-fill sources, weekly targets, archive/restore, and drag-to-reorder; edit existing habits (tracking type locked after creation); 35-icon library organised by category
- **Zone 2 tracking** — `zone2_minutes` on workouts auto-fills Zone 2 habit progress
- **Weekly habits widget** — Mon–Sun progress grid on home page with streak badges; week boundary computed in Bangkok timezone (Asia/Bangkok)
- **Habits streaks** — per-habit current streak and best-streak counters; today-pending does not break a streak
- **Mobile-first daily flow** — mobile workout logging form and quick daily-metrics entry, optimised for 390px
- **Daily wellness metrics** — HRV, resting HR, sleep, energy, mood
- **Readiness score** — computed from wellness metrics with contextual interpretation
- **Training log** — workout log with type badges, TSS, distance, HR, and pace; training load (CTL/ATL/TSB) widget and weekly volume bar chart on the log page; workout metrics and source badges visible on mobile viewports; Strava source badges consistent across list and detail views; friendly empty state for new users
- **Run View** — per-workout run detail page (`/run-view`) showing pace, power, HR, cadence, and stride-length per km split; supports both auto (1-km) and manually-entered lap rows (`lap_type`)
- **Run Builder** — run planning page (`/run-builder`) for composing structured runs with Stryd aggregate fields (avg power, max power, normalized power, cadence, stride)
- **Running TSS** — `compute_running_tss` service computes TSS automatically via three fallback methods: Power (NP/FTP), Pace (per-lap threshold pace), or HR (avg HR / threshold HR); result surfaced on `GET /api/workouts/{id}/full` as `tss`, `tss_method`, and `tss_partial`
- **Normalized power** — `compute_normalized_power` pure function computes NP from a 1-second power stream; stored on the workout record (`np` column) at ingest time
- **Activity streams** — Strava and Stryd syncs now fetch and store per-sample time-series data (power, HR, pace, cadence, altitude, GPS) in the `activity_streams` table; used for NP calculation and Run View charting
- **Strava sync** — OAuth connection to Strava; pulls activities and reconciles them into workouts with source badges and TSS computation
- **Stryd integration** — encrypted credential storage; Stryd-matched workouts show a dual badge in the training log
- **Performance trends** — CTL/ATL/TSB (training load) and personal records
- **Multi-user** — session-based auth, per-user data isolation
- **Health check** — `GET /api/healthz` returns `{ok, version, env}` for Render health probes

## Canonical working directory

**Use a single clone of this repository.** Environment selection is branch-based:

| Branch | Environment | Port | Neon branch | Purpose |
|--------|-------------|------|-------------|---------|
| `develop` | UAT | 9001 | `uat` | Testing / staging |
| `main` | PRD | 9000 | `main` (prd) | Production data |

> **Warning:** Do not maintain parallel checkouts (e.g. `perf-coach/uat/` and
> `perf-coach/main/` as separate directories). Changes in one directory are
> invisible to the other, causing config drift, missed fixes, and migration
> conflicts. Use `git checkout develop` / `git checkout main` in a single clone
> to switch environments.

## Setup

1. Create a project on [neon.tech](https://neon.tech) named `perf-coach`.
2. Create two branches: one called `main` (or whatever you name the default) for PRD and one called `uat`.
3. Copy the connection strings for each branch from Neon → Connection Details.
4. Populate a single `.env` at the project root with **both** connection strings:

**.env:**

    DATABASE_URL_PRD=<your prd branch connection string>
    DATABASE_URL_UAT=<your uat branch connection string>

5. Install Python dependencies:

       pip install -r requirements.txt

## Starting each environment

Check out the branch for the environment you want, then run the matching script:

**UAT** (`develop` branch):

    git checkout develop
    ./start_uat.sh

Visits: http://localhost:9001

**PRD** (`main` branch):

    git checkout main
    ./start_prd.sh

Visits: http://localhost:9000

Each script:
- Sources `.env` for database credentials (`DATABASE_URL_UAT` / `DATABASE_URL_PRD`)
- Sets `ENVIRONMENT` and `PORT` explicitly (overrides anything in `.env`)
- Logs the target DB **host** (not password) before running migrations
- Verifies the Neon DB is reachable (exits with "DB unreachable" if not)
- Runs `alembic upgrade head` against the correct Neon branch
- Starts uvicorn on the configured port

## What each environment is for

- **PRD** — real data, the source of truth. Treat it carefully.
- **UAT** — for testing new features before promoting to PRD. Data here can be wiped freely. Because Neon branches are completely isolated, data written to UAT never appears in PRD.

## API

| Endpoint | Description |
|---|---|
| `GET /api/environment` | Returns `{"environment": "PRD"\|"UAT", "version": "0.1.0"}` |
| `GET /api/health` | Returns DB connection status |
| `GET /api/users` | Returns list of users |
| `GET /api/training-log` | Returns training log entries with workout details (distance, duration, HR, elevation, pace, source, strava_activity_url); supports `from`, `to`, `types`, `search`, `include_rest` query params. Response includes a top-level `load_context` block (CTL/ATL/TSB + interpretation) when user has ≥7 days of data. |
| `GET /api/exercises/names` | Returns sorted list of distinct exercise names for the session user; used for autocomplete in the workout log form |
| `GET /trends/summary` | Returns trend aggregations (readiness, HRV, RHR, sleep, energy, mood, TSS) for a date range |
| `GET /api/readiness/today` | Returns today's computed readiness score for a user |
| `GET /api/readiness` | Returns readiness scores over a date range |
| `POST /api/readiness/compute` | Computes and stores today's readiness score |
| `POST /api/weight-entries` | Create a weight entry; body: `user_id`, `entry_date`, `weight_kg`, optional `entry_time`, `notes`, `source` |
| `GET /api/weight-entries` | List weight entries; `user_id` required; `from`/`to` (YYYY-MM-DD) range (default last 90 days, max 365) |
| `PATCH /api/weight-entries/{entry_id}` | Update `weight_kg`, `entry_date`, `entry_time`, or `notes` on a single entry |
| `DELETE /api/weight-entries/{entry_id}` | Delete a single weight entry (204) |
| `POST /api/weight-targets` | Create a new weight target; sets any existing active target to `replaced`; body: `user_id`, `start_weight_kg`, `start_date`, `target_weight_kg`, `target_date` |
| `GET /api/weight-targets/active` | Get the active weight target with computed fields: `progress_pct`, `kg_to_go`, `days_remaining`, `required_pace_kg_per_week`, `current_pace_kg_per_week`, `projected_end_date`, `status_label`, `plan_today_kg`, `gap_kg`, `gap_direction`, `gap_basis`, `milestones`, `projected_hit_date` (extrapolated from 7-day pace; `null` if pace is zero or moving away from goal) |
| `GET /api/weight-targets/history` | List all weight targets for a user; optional `status` filter (`active`/`achieved`/`abandoned`/`replaced`) |
| `PATCH /api/weight-targets/{target_id}` | Update `target_weight_kg`, `target_date`, or `notes` on the active target |
| `POST /api/weight-targets/{target_id}/end` | End the active target; body: `status` (`achieved`/`abandoned`), optional `end_weight_kg` and `notes` |
| `GET /api/weight-chart` | Weight entries and 7-day moving average trend; `user_id`, optional `from`/`to` date params or `range` shorthand (`7D`, `30D`, `90D`, `6M`, `1Y`, `ALL`; `ALL` resolves from earliest entry); optional `include_future_zone=true`; response: `actuals`, `trend`, `stats`, `future_milestones` (always an array), `today_marker`, `logged_today`, `today_delta_kg`; `plan_series` (daily plan points from plan-start date) and `target` block included only when an active target exists |
| `GET /api/exports/weight-entries` | Download weight entries as CSV; `user_id`, optional `from`/`to` date range |
| `GET /api/exports/weight-targets` | Download weight target history as CSV; `user_id`, optional `status` filter |
| `GET /api/home/weight-summary` | Returns current weight, 7-day moving average, week/month deltas, 30-day sparkline, and active target progress for the home dashboard weight widget |
| `GET /api/home/recent-workouts` | Returns up to 10 recent workouts with relative dates and a `has_more` flag for the home dashboard training-log preview widget; `limit` param (default 5, max 10) |
| `GET /api/home/personal-records` | Returns current PR values, formatted display strings, and trend signal for configurable tracks (default: `half_marathon,10k,squat_1rm`) |
| `GET /api/home/readiness` | Returns daily readiness score (0–100), label, 5-factor contributor breakdown, and 7-day rolling baseline; `date` param defaults to today |
| `GET /api/home/weekly-summary` | Returns Mon–Sun workout counts by type, distance/duration/TSS/elevation sums, rest-day count, prior-week deltas, and per-day TSS for sparkline; week computed in Asia/Bangkok timezone |
| `GET /api/home/summary` | Single-call aggregator for the home page: returns all seven data blocks (habits, weight, readiness, training-week, performance/PRs, recent workouts, sleep) in one response; each block is computed independently and returns `null` on error without failing the whole request; all boundaries use Asia/Bangkok (UTC+7) |
| `GET /api/user-preferences` | Returns per-user preferences (FTP, thresholds, timezone, display name, etc.) |
| `PATCH /api/user-preferences` | Updates editable preference fields (ftp_w, threshold_hr, threshold_pace_seconds_per_km, display_name, week_start_day, timezone) |
| `GET /api/personal-records/tracks` | Lists canonical PR tracks (running times and strength 1RMs) |
| `GET /api/personal-records/history` | Returns history for a single track with improvement deltas; params: `user_id`, `track_key` |
| `POST /api/personal-records/bulk` | Bulk-inserts multiple PR entries in one request; returns created count and IDs |
| `GET /api/habits/week` | Single-batch habits week view: `daily_habits` (checkmark grid), `weekly_habits` (progress bars), `day_scores`, `week_totals`, `wheel` (7-segment arc states), `streaks`, and `last_week` summary. Optional `week_start` param (YYYY-MM-DD Monday); defaults to current Bangkok week. |
| `POST /api/habits/{habit_id}/log` | Log a habit entry; body: optional `log_date`, `value`, `notes`, `mode` (`set` replaces / `add` increments existing value; default `set`). Backfill window enforced: only dates within the current Bangkok week are writable. |
| `GET /api/about` | Returns app version, git SHA, environment, and changelog availability |
| `POST /api/sync/strava` | Trigger a Strava activity sync; returns 202 with `job_id` and `polling_url`; 409 if already running |
| `GET /api/sync/strava/status` | Poll status of a sync job by `job_id`; returns full SyncJob record |
| `GET /api/sync/strava/latest` | Return info about the most recent completed Strava sync |
| `GET /api/sync/strava/dry-run` | Read-only preview of what a Strava reconcile would produce; no DB writes |
| `GET /api/sync/strava/data-quality` | Return data quality counts for a user's Strava/workout sync state |
| `POST /api/sync/strava/reconcile` | Reconcile unlinked `strava_activities` into `workouts` rows; returns counts |
| `GET /api/sync/history` | Return paginated SyncJob history for the session user (last 5 by default) |

The frontend reads `/api/environment` on every page load to display the environment badge in the header. No hostname/port heuristic is used.

## Database migrations (Alembic)

Migrations live in `alembic/versions/`. The connection string is chosen from `DATABASE_URL_PRD` or `DATABASE_URL_UAT` based on the `ENVIRONMENT` env var.

All migrations are idempotent — each `op.create_table`, `op.create_index`,
`op.add_column`, and corresponding drop is guarded by an existence check, so
running `alembic upgrade head` on a database that is already at head (or
partially ahead) exits 0 without error.

**Apply migrations manually:**

    ENVIRONMENT=UAT alembic upgrade head   # against uat branch
    ENVIRONMENT=PRD alembic upgrade head   # against prd branch

The startup scripts run `alembic upgrade head` automatically, so you normally don't need to run this by hand.

**Generate a new migration after editing `backend/models.py`:**

    make migrate MSG="your description here"

**Roll back the last migration:**

    alembic downgrade -1

**Test migration idempotency** (requires a throwaway Postgres DB):

    TEST_DATABASE_URL=postgresql://... bash scripts/test_migrations.sh

## Deployment

perf-coach is deployed on [Render](https://render.com) using the `render.yaml` blueprint in this repo. Two web services are defined: `perf-coach-uat` (auto-deploys from `develop`) and `perf-coach-prd` (manually promoted from `master`).

### Connect the repo to Render via Blueprint

1. Log in to the [Render dashboard](https://dashboard.render.com).
2. Click **New** → **Blueprint**.
3. Connect your GitHub account if prompted, then select the `perf-coach` repository.
4. Render detects `render.yaml` automatically. Review the two services (`perf-coach-uat`, `perf-coach-prd`) and click **Apply**.
5. Both services are created. They will fail their first deploy because `DATABASE_URL` has not been set yet — this is expected. Proceed to the next section.

### Populate DATABASE_URL for each service

`DATABASE_URL` is intentionally absent from `render.yaml`. Set it manually in the Render dashboard after the services are created.

**perf-coach-uat (UAT)**

1. In the [Neon console](https://console.neon.tech), open your `perf-coach` project.
2. Select the `uat` branch → **Connection Details** → copy the connection string.
3. In the Render dashboard, open the `perf-coach-uat` service → **Environment**.
4. Find the `DATABASE_URL` variable and paste the Neon UAT connection string as its value.
5. Click **Save Changes**. Render triggers a new deploy automatically.

**perf-coach-prd (PRD)**

1. In the Neon console, select the `main` (PRD) branch → **Connection Details** → copy the connection string.
2. In the Render dashboard, open the `perf-coach-prd` service → **Environment**.
3. Find the `DATABASE_URL` variable and paste the Neon PRD connection string as its value.
4. Click **Save Changes**.

### Promote to PRD (manual deploy)

PRD does not auto-deploy. To release a new version to production:

1. Merge your changes to the `master` branch.
2. In the Render dashboard, open the `perf-coach-prd` service.
3. Click **Manual Deploy** → **Deploy latest commit on master**.
4. Monitor the deploy log; Render runs `alembic upgrade head` before traffic switches to the new version.
