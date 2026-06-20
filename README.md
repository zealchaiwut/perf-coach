# perf-coach

Personal performance dashboard. Tracks weight, habits, readiness, training log, and performance trends.

## Features

- **Weight tracking** — daily log; gradient-design weight page with two-card hero (current weight + log-today); custom SVG trend chart (v8) with three-zone BMI axes, moving average, range tabs (7D / 30D / 90D / 6M / 1Y / All); plan overlay, milestones, projected goal-hit date (7-day pace), and slide-in target-edit panel; `/weight/targets` removed — target editing is now inline on the weight page; logging streak badge and 14-day adherence counter shown below the hero; mobile touch: tap-to-reveal tooltip on chart, persistent labels for current weight, plan, gap, and milestone values
- **Habit tracking** — redesigned habits page with gradient design language; 7-segment week wheel, tap-to-check daily grid with day-score footer row, weekly habits progress bars with auto-sync badges; auto-fill sources, weekly targets, archive/restore, and drag-to-reorder; edit existing habits (tracking type locked after creation); 35-icon library organised by category; v2 schema adds `habit_type` (`binary`/`count`/`duration`), `schedule_type` (`daily`/`weekly`/`times_per_week`), `schedule_target`, `target_value`, and `active` columns; `GET /api/habits/summary` returns each active habit with `current_streak`, `longest_streak`, and `consistency_percent` (30-day window)
- **Zone 2 tracking** — `zone2_minutes` on workouts auto-fills Zone 2 habit progress
- **Weekly habits widget** — Mon–Sun progress grid on home page with streak badges; week boundary computed in Bangkok timezone (Asia/Bangkok)
- **Habits streaks** — per-habit current streak and best-streak counters; today-pending does not break a streak
- **Mobile-first daily flow** — mobile workout logging form and quick daily-metrics entry, optimised for 390px
- **Daily wellness metrics** — HRV, resting HR, sleep, energy, mood
- **Readiness score** — computed from wellness metrics with contextual interpretation
- **Training log** — workout log with type badges, TSS, distance, HR, and pace; three sub-tabs (Log / Plan / Performance) with Log as the default active panel; Readiness widget (CTL/ATL/TSB Fitness/Fatigue/Form tiles with recovery hint, or "building baseline" state when fewer than 7 scored workout days exist in the past 42 days); Weekly Volume & Load bar chart with gradient fill, current-week emphasis, and Lift TSS stacked; mobile week-strip (horizontal Mon–Sun pill row) tapping a day scrolls the log list to the nearest matching date rather than filtering it; workout metrics and source badges visible on mobile viewports; Strava source badges consistent across list and detail views; friendly empty state for new users; nav bar label shortened to "Training"; Log Workout opens as a slide-over panel (Strength body: exercise list + sets/reps/weight/RPE; Running body)
- **Run View** — per-workout run detail page (`/run-view`) with redesigned header and load block; shows session profile, laps (with intensity bands), route strip (GPS altitude/pace sparkline), pace, power, HR, cadence, and stride-length per km split; supports both auto (1-km) and manually-entered lap rows (`lap_type`)
- **Strength View** — per-workout strength detail page (`/strength-view`) showing exercise list, sets/reps/weight/RPE, and a redesigned header matching the Run View design language; reached from the training log detail panel
- **Run Builder** — run planning page (`/run-builder`) for composing structured runs with Stryd aggregate fields (avg power, max power, normalized power, cadence, stride)
- **Running TSS** — `compute_running_tss` service computes TSS automatically via three priority-ordered fallback methods: Power (NP/FTP), Pace (per-lap threshold pace), or HR (avg HR / threshold HR); result persisted to the `workouts` record on POST/PATCH workout and PUT splits; `tss_method` stored alongside `tss` and exposed in the workout dict; updating FTP/threshold preferences triggers a bulk recompute for all user workouts; result also surfaced on `GET /api/workouts/{id}/full` as `tss`, `tss_method`, `tss_partial`, and `computed_tss`
- **Session profile detection** — `detect_session_profile` classifies workout intent from lap data through a pipeline of pure functions: `classify_laps` in `backend/services/lap_classifier.py` (lap intensity bands; basis chosen once per call from prefs — power → pace → hr — applied to all laps), `group_laps_into_phases` (phase grouping), `detect_intervals` / `detect_sets` (interval and set recognition; `detect_sets` output includes `reps_per_set` list); result exposed on `GET /api/workouts/{id}/full` as `detected_profile`
- **Normalized power** — `compute_normalized_power` pure function computes NP from a 1-second power stream; stored on the workout record (`np` column) at ingest time
- **Activity streams** — Strava and Stryd syncs now fetch and store per-sample time-series data (power, HR, pace, cadence, altitude, GPS) in the `activity_streams` table; used for NP calculation and Run View charting
- **Race targets** — CRUD for user target races (`POST/GET/PUT/PATCH/DELETE /api/races`); each race stores distance, goal time, priority (A/B/C), status (planned/done/abandoned), race type (race/checkpoint), and recorded finish time (`actual_time_seconds`); goal pace is derived automatically from goal time and distance; race dict includes a computed `met_status` field (met/missed/upcoming)
- **Race checkpoints** — intermediate milestones within a target race (`POST/GET/PATCH/DELETE /api/races/{id}/checkpoints`); each checkpoint stores optional targets for distance, pace, and duration; auto-detection marks a checkpoint `met` when a new run workout satisfies its targets; `met_override` freezes the state against future auto-detection
- **Speed PR detection** — `backend/services/pr_detection.py` pure function `detect_speed_records` identifies fastest times for six standard distances (1 km, 1 mile, 5 km, 10 km, half marathon, marathon) from the pace duration curve and completed runs; `detect_power_records` identifies best 1-min, 5-min, and 20-min power efforts
- **Strength PR storage** — `strength_personal_records` table stores current best weight per `(user, exercise_key, rep_band_label)`; `strength_record_achievements` table is an append-only log of each PR-beating event written at workout-ingest time
- **Training Plan sub-tab** — Training page now includes a Plan sub-tab showing race plan timeline with race/checkpoint entries, countdown, goal pace, and met-status badges; race entries are editable inline with type (race vs checkpoint) toggle
- **Race readiness** — `GET /api/races/{id}/readiness` returns a combined readiness report: 180-day form curve with zone labels (accumulated_fatigue / optimal / freshness), projected form to race day, taper start recommendation, on-track assessment versus the planned taper trajectory, and specificity progress (recent run distances vs race distance); all thresholds configurable via AppConfig
- **Performance curve** — `performance_curve` pure function in `training_load.py` produces a CTL/ATL/TSB projection from a historical TSS series
- **Form projection** — `project_form` projects CTL/ATL/TSB forward to a target date given a constant daily TSS assumption
- **Taper recommendation** — `taper_recommendation` computes the optimal taper start date to hit a target TSB range on race day
- **Peak tracking** — `peak_tracking` compares current TSB to the planned taper curve and returns an on-track / ahead / behind status with gap
- **Race specificity progress** — `specificity_progress` service compares the athlete's recent long-run distances to the target race distance to assess training specificity
- **Strength TSS** — `backend/services/strength_tss.py` provides two pure calculation paths: `calculate_strength_tss` (session-RPE method — SI² × duration/60 × 100, using configurable `strength_rpe_max` from `user_preferences`) and `calculate_strength_tss_per_set` (per-set method — reps × (rpe/10)² per set, scaled and clamped); `calculate_strength_tss_per_set_with_prefs` and `compute_strength_tss` in `tss.py` consolidate per-set and session-RPE methods with user-preference-driven scale and max TSS; `strength_rpe_max` stored in `user_preferences` configures the RPE scale ceiling (e.g. 10 for standard RPE, 20 for Borg)
- **Duration curves** — `backend/services/per_workout_curves.py` computes best-average power and pace for a configurable duration ladder (1 s to 90 min) within each individual workout using a rolling-window algorithm on per-second streams, falling back to lap then workout-level aggregates; `backend/services/duration_curve_best_effort.py` merges per-workout curves into a per-athlete best-effort curve stored in `athlete_duration_curves`
- **Auto-threshold suggestions** — `backend/services/threshold_suggestions.py` derives suggested FTP (95 % of best 20-min power, or fallback window at low confidence), threshold HR, and threshold pace from a user's duration curve and recent run history; each suggestion includes a `high_confidence` (bool) field and a `formula` string (human-readable derivation, e.g. "best 20-minute power multiplied by 0.95"); manually set preferences are excluded from suggestions; `GET /api/thresholds/suggestions` returns only pending suggestions (those not yet accepted)
- **Accept-suggestion flow** — `POST /api/thresholds/suggestions/accept` writes accepted threshold values to `user_preferences` with `source = "user_accepted"` and stamps the corresponding `*_updated_at` timestamp; returns 422 when a requested key has no pending suggestion; accepted suggestions are suppressed from future GET calls; the Settings UI shows inline suggestion banners (with formula text and an Accept button) that write directly to preferences on click without requiring a separate Save
- **Unified daily training load series** — `backend/services/daily_load.py` pure function aggregates workout TSS by calendar day; exposed via `GET /api/training/daily-load` (session-user) and `GET /api/athletes/{athlete_id}/daily-load` (by athlete UUID)
- **Strava sync** — OAuth connection to Strava; pulls activities and reconciles them into workouts with source badges and TSS computation; compact sync controls with last-sync timestamps in Settings → Integrations
- **Stryd integration** — encrypted credential storage; workouts merged from both Strava and Stryd show both source badges simultaneously in the training log (`has_strava` / `has_stryd` fields on list and detail responses)
- **Fitness / fatigue / form model** — `backend/services/fitness_model.py` pure function `compute_fitness_series` computes CTL (42-day EWMA), ATL (7-day EWMA), and TSB from a unified daily-load series; no SQL or side effects; consumed by the readiness endpoint and the performance chart
- **ACWR training-load guidance** — `backend/services/acwr.py` pure function `compute_acwr` classifies acute:chronic workload ratio into detraining / productive / elevated / high-risk bands; requires ≥ 28 days of history; zone thresholds: <0.8 detraining, 0.8–1.3 productive, 1.3–1.5 elevated, >1.5 high-risk
- **Running performance scores** — `backend/services/running_performance.py` derives endurance and speed scores from per-run efficiency and aerobic decoupling; normalised to the athlete's own historical range with no hardcoded external thresholds; zone constants provided by `backend/services/zone_constants.py`; exposed via `GET /api/athletes/{athlete_id}/performance`
- **Training > Performance sub-tab** — the Performance tab in the Training page is now fully implemented (replaces the "coming soon" placeholder): shows Endurance and Speed score rings (0–100) with direction label and trend sparkline, a CTL/ATL/TSB fitness chart with 30D/90D/6M/1Y date-range selector and today marker, ACWR guidance computed client-side from the daily-load series, and a personal-records strip; `building_baseline` states are handled gracefully; powered by `frontend/js/training-performance.js`; mockup committed to `docs/mockups/performance-tab.md`
- **Settings — Zones section** — a new "Zones" section in Settings displays device-sourced power zones (critical power and per-zone wattages) read-only from the most recent Stryd activity via `GET /api/thresholds/device-zones`; updates automatically after a Stryd sync
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
| `GET /api/readiness` | Dual-mode readiness endpoint. **Without params:** returns training-load readiness — `{building_baseline, ctl, atl, tsb, readiness_label, series}` derived from `compute_fitness_series` over the last 180 days; `building_baseline: true` when fewer than the minimum scored workout days exist in the baseline window. **With `from`/`to` params:** legacy mode — returns daily wellness readiness scores as `[{date, score}]` or `null` per day in the range. |
| `POST /api/readiness/compute` | Computes and stores today's readiness score |
| `GET /api/readiness/current` | Returns current CTL/ATL/TSB fitness state for the Readiness widget; returns `{building_baseline: true}` when fewer than 7 workout days with non-zero TSS exist in the past 42 days, otherwise returns `{building_baseline: false, ctl, atl, tsb, recovery_hint}` |
| `GET /api/athletes/{athlete_id}/performance` | Returns endurance and speed running performance scores for an athlete. Both scores are normalised to the athlete's own historical range. Returns `{endurance, speed}` where each key is either a score object or `{state: "building_baseline", reason: "..."}` when insufficient runs exist, or `{score: null, reason: "..."}` when preferences are unavailable. Returns 404 if the athlete does not exist. |
| `GET /api/performance/chart` | Returns aligned CTL/ATL/TSB/endurance/speed time-series for a performance chart. Params: `athlete_id` (UUID), `start_date`, `end_date` (YYYY-MM-DD). Always returns HTTP 200; error cases return empty arrays with a machine-readable `reason` field (`athlete_not_found`, `invalid_date_range`, `no_data_in_range`). Response: `{dates, ctl, atl, tsb, endurance_score, speed_score, building_baseline, reason}`. |
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
| `GET /api/training/daily-load` | Unified daily training load series; params: `athlete_id` (UUID), `start`, `end` (ISO dates); returns one entry per calendar day with `daily_load` (sum TSS), `workout_count`, `has_unscored`, and a `debug.contributing_workouts` list |
| `GET /api/athletes/{athlete_id}/daily-load` | Per-athlete daily training load series; path param `athlete_id` (UUID); query params `start_date` and `end_date` (ISO dates, both required); returns a JSON list of per-day objects (`date`, `daily_load`, `workout_count`, `has_unscored`, `debug.contributing_workouts`); 400 on missing/invalid/inverted dates, 404 when athlete does not exist |
| `GET /api/thresholds/suggestions` | Returns pending threshold suggestions (`ftp_w`, `threshold_hr`, `threshold_pace_seconds_per_km`) derived from the user's duration curve and recent runs; each suggestion includes `value`, `confidence` ("high"/"low"), `high_confidence` (bool), and `formula` (human-readable derivation string); empty when none are pending or data is insufficient |
| `POST /api/thresholds/suggestions/accept` | Accept a subset of threshold suggestions; body: `{"keys": [...]}` — writes values to `user_preferences` with `source = "user_accepted"` and stamps corresponding `*_updated_at` timestamp; returns `{"written": {...}, "skipped": []}`; 422 when any requested key has no pending suggestion |
| `GET /api/thresholds/device-zones` | Returns device-sourced power zones for the authenticated user from the most recent Stryd activity containing power zone data; response: `{"source": "stryd", "critical_power_w": int\|null, "zones": {...}, "activity_date": "YYYY-MM-DD"}`; returns `{"source": null, "zones": {}}` when no Stryd activity with power zone data exists |
| `PATCH /api/races/{race_id}` | Update any subset of mutable race fields (name, date, distance_km, goal_time_seconds, priority, status, race_type); goal pace recomputed automatically |
| `DELETE /api/races/{race_id}` | Delete a race target (204); 404 if not found or not owned by session user |
| `POST /api/races/{race_id}/checkpoints` | Create a checkpoint for a race; body: `name` (required), at least one of `target_distance_km`, `target_pace_seconds_per_km`, `target_duration_seconds`; returns 201 |
| `GET /api/races/{race_id}/checkpoints` | List all checkpoints for a race, ordered by creation time |
| `GET /api/races/{race_id}/checkpoints/{checkpoint_id}` | Return a single checkpoint |
| `PATCH /api/races/{race_id}/checkpoints/{checkpoint_id}` | Update mutable checkpoint fields; setting `met` also sets `met_override = true` to block future auto-detection |
| `DELETE /api/races/{race_id}/checkpoints/{checkpoint_id}` | Delete a checkpoint (204) |

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
