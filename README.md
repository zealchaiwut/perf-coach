# perf-coach

Personal performance dashboard. Tracks weight, habits, readiness, training log, and performance trends.

## Features

- **Weight plans** — structured goal plans per user (`weight_plans` table); phase (`cut`/`bulk`/`maintain`), start/goal weights, optional target rate and goal date; one active plan per user enforced; `recompute_plan_from_progress(plan, actual_trend, today)` pure function anchors a new forward plan segment at today's actual trend weight while preserving the original segment, enabling charts to show a plan line grounded in current reality; CRUD endpoints: `POST /api/weight-plans`, `GET /api/weight-plans/active`, `PATCH /api/weight-plans/{id}`, `DELETE /api/weight-plans/{id}` (soft-deactivates)
- **Weight tracking** — daily log; gradient-design weight page with two-card hero (current weight + log-today); custom SVG trend chart (v8) with three-zone BMI axes, moving average, range tabs (7D / 30D / 90D / 6M / 1Y / All); plan overlay, milestones, projected goal-hit date (7-day pace), and slide-in target-edit panel; `/weight/targets` removed — target editing is now inline on the weight page; logging streak badge and 14-day adherence counter shown below the hero; mobile touch: tap-to-reveal tooltip on chart, persistent labels for current weight, plan, gap, and milestone values
- **Habit tracking** — redesigned habits page with gradient design language; 7-segment week wheel, tap-to-check daily grid with day-score footer row, weekly habits progress bars with auto-sync badges; auto-fill sources, weekly targets, archive/restore, and drag-to-reorder; **Create and Edit Habit slide-over form** — gradient-themed slide-over panel (mobile: full-screen overlay) for creating new habits and editing existing ones; fields: name (required), habit type (binary / count / duration — locked after creation), target value/unit and schedule type (conditional on habit type), icon picker (35-icon library organised by category); client-side validation with inline error messages; archive action available on edit; calls `POST /api/habits` (create) or `PATCH /api/habits/{id}` (edit); **Today quick-log card** — per-habit row with type-specific controls (toggle for daily checkmarks, steppers for quantities/minutes, duration input) that POST to `/api/habits/{id}/log` with upsert semantics and refresh the streak badge inline; **History calendar** — monthly/weekly calendar on the Habits page showing per-day completion status with a per-habit filter bar; v2 schema adds `habit_type` (`binary`/`count`/`duration`), `schedule_type` (`daily`/`weekly`/`times_per_week`), `schedule_target`, `target_value`, and `active` columns; `GET /api/habits/summary` returns each active habit with `current_streak`, `longest_streak`, and `consistency_percent` (30-day window)
- **Habit adherence analytics** — `backend/services/habit_breakdown.py` `compute_adherence_breakdown` pure function computes per-weekday adherence breakdown (met/scheduled counts, strongest/weakest day) for any habit and date window; `backend/services/habit_slipping.py` `detect_slipping_habits` pure function compares a recent vs. prior window and flags habits whose adherence rate has dropped by ≥ 20 pp; `backend/services/habit_nudges.py` `build_nudges` pure function translates weekday-dip and slipping-habit signals into up to 5 coaching nudges using plain-language percentage words (no raw digits or `%`), tone is non-judgmental; `backend/services/habit_adherence.py` `build_adherence_payload` assembles the full per-habit payload consumed by `GET /api/habits/adherence`; **Adherence & Nudges panel** on the Habits page (`#adherence-panel`) renders a card per habit with a progress bar colour-coded high/mid/low, best-day / worst-day chips, coaching nudge copy, and a declining-habit amber accent; skeleton shimmer on load; graceful hide on fetch error; populated by `frontend/js/habit-adherence.js`
- **Zone 2 tracking** — `zone2_minutes` on workouts auto-fills Zone 2 habit progress
- **Weekly habits widget** — Mon–Sun progress grid on home page with streak badges; week boundary computed in Bangkok timezone (Asia/Bangkok)
- **Habits streaks** — per-habit current streak and best-streak counters; today-pending does not break a streak
- **Habit-outcome alignment** — `align_habit_and_outcome(habit_logs, outcome_series, lag_days)` pure function in `backend/services/habit_outcome_alignment.py` pairs daily habit-completion records with any daily outcome metric (readiness, TSB, weight trend, etc.), optionally shifting the outcome forward by a configurable number of days; returns a `(pairs, debug)` tuple where `pairs` is a list of matched records (habit date/value + outcome date/value) and `debug` reports input counts, pairs before/after dropping unmatched days, and a human-readable reason string; performs no DB queries, file I/O, or network calls — a thin caller supplies the mappings
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
- **Speed PR detection** — `backend/services/pr_detection.py` pure function `detect_speed_records` identifies fastest times for six standard distances (1 km, 1 mile, 5 km, 10 km, half marathon, marathon) from the pace duration curve and completed runs; `detect_power_records` identifies best 1-min, 5-min, and 20-min power efforts; exposed via `GET /api/athletes/{athlete_id}/run-personal-records` (speed, power, and volume records) and `GET /api/athletes/{athlete_id}/detected-prs`; the endpoint enriches uncomputable record categories with per-slot `{"reason": "..."}` objects (e.g. `"insufficient data: no GPS pace data available for this athlete"`) so consumers can show slot-specific messaging instead of a single top-level error; the endpoint also auto-rebuilds the athlete's duration curve if no curve row exists yet; the Performance sub-tab PR strip now fetches from these auto-detection endpoints instead of the manual personal-records table
- **Strength PR storage** — `strength_personal_records` table stores current best weight per `(user, exercise_key, rep_band_label)`; `strength_record_achievements` table is an append-only log of each PR-beating event written at workout-ingest time
- **Training Plan sub-tab** — Training page now includes a Plan sub-tab showing race plan timeline with race/checkpoint entries, countdown, goal pace, and met-status badges; race entries are editable inline with type (race vs checkpoint) toggle
- **Training plan model** _(Sprint 92)_ — `training_plans` table stores per-user plan configuration; fields: `name`, `ramp_rate`, `taper_start`, `taper_length`, `taper_shape` (`linear`/`step`/`exponential`); CRUD endpoints: `POST /api/plans` (201), `GET /api/plans/{id}`, `PATCH /api/plans/{id}`; all ramp/taper fields are nullable
- **Plan races/checkpoints API** _(Sprint 92)_ — `backend/routers/plan.py` provides a nested REST API for managing race entries and intermediate checkpoints within a plan: `GET/POST /api/plans/{plan_id}/races`, `GET/PATCH/DELETE /api/plans/{plan_id}/races/{race_id}`, `GET/POST /api/plans/{plan_id}/races/{race_id}/checkpoints`, `PATCH/DELETE /api/plans/{plan_id}/races/{race_id}/checkpoints/{checkpoint_id}`; plan ownership is enforced (plan_id must match session user id)
- **Plan editor UI** _(Sprint 92)_ — `frontend/js/training-plan.js` and `frontend/pages/training-log.html` updated with a full plan editor panel for creating and editing races and checkpoints within a training plan; the editor also exposes ramp-rate and taper controls (taper start / length / shape) with a live planned-load schedule preview that updates as the parameters change
- **Planned-load schedule generation** _(Sprint 92)_ — `generate_planned_load_schedule` in `backend/services/plan_service.py` builds a per-date planned-TSS schedule from a plan's ramp rate and taper parameters (start / length / `linear`/`step`/`exponential` shape); `persist_planned_load_schedule` writes it to the `planned_load` table for the projection engine to consume
- **Fitness projection engine** _(Sprint 92)_ — `backend/services/projection.py` rolls CTL/ATL/TSB forward from current state over a planned-load schedule with a widening confidence band (band widens proportionally to projection horizon; B-race checkpoints tighten the band when encountered); `backend/services/score_ceiling.py` maps projected CTL to endurance/speed score ceiling via `projected_ctl_to_score_ceiling`; `backend/services/race_finish_estimator.py` converts an expressible score (derived from TSB form factor in `compute_expressible_score`) to an estimated race finish time via Riegel-based pacing model
- **Plan projection endpoint** _(Sprint 92)_ — `GET /api/plans/{plan_id}/projection` returns CTL/ATL/TSB projection series, per-race estimated finish times, and a fitness confidence band for the plan's horizon; uses 28-day trailing average load as the default planned load; threshold pace from user preferences drives finish-time estimates
- **Projection screen** _(Sprint 92)_ — new `/projection` page (`frontend/pages/projection.html` + `frontend/js/projection.js`, reached from the **Projection** nav item) renders the form curve, projected form toward the A-race, A/B/C race markers, and current Endurance/Speed scores; backed by `GET /api/projection`, which combines the 180-day form curve, projected form, priority race markers (with a `recalibrates_here` flag on the earliest upcoming B-race), and endurance/speed scores
- **Riegel cross-distance equivalence** _(Sprint 92)_ — `backend/services/riegel.py` implements the Riegel formula (`T2 = T1 * (D2/D1) ^ 1.06`) as pure functions; `riegel_half_equivalent` expresses any race time as a half-marathon-equivalent time so entries at different distances can be compared apples-to-apples. Race serialization (`_race_dict`) now includes `half_marathon_equivalent_seconds`
- **Race readiness** — `GET /api/races/{id}/readiness` returns a combined readiness report: 180-day form curve with zone labels (accumulated_fatigue / optimal / freshness), projected form to race day, taper start recommendation, on-track assessment versus the planned taper trajectory, specificity progress (recent run distances vs race distance), and a `time_curve` block (added Sprint 92) with `history` (last 90 days of estimated finish times derived from TSB expressible score) and `projection` (zero-load taper projection to race day with `confidence_band_seconds`, `upper_seconds`, `lower_seconds`); all thresholds configurable via AppConfig
- **Performance curve** — `performance_curve` pure function in `training_load.py` produces a CTL/ATL/TSB projection from a historical TSS series
- **Form projection** — `project_form` projects CTL/ATL/TSB forward to a target date given a constant daily TSS assumption
- **Taper recommendation** — `taper_recommendation` computes the optimal taper start date to hit a target TSB range on race day
- **Peak tracking** — `peak_tracking` compares current TSB to the planned taper curve and returns an on-track / ahead / behind status with gap
- **Race specificity progress** — `specificity_progress` service compares the athlete's recent long-run distances to the target race distance to assess training specificity
- **Strength TSS** — `backend/services/strength_tss.py` provides two pure calculation paths: `calculate_strength_tss` (session-RPE method — SI² × duration/60 × 100, using configurable `strength_rpe_max` from `user_preferences`) and `calculate_strength_tss_per_set` (per-set method — reps × (rpe/10)² per set, scaled and clamped); `calculate_strength_tss_per_set_with_prefs` and `compute_strength_tss` in `tss.py` consolidate per-set and session-RPE methods with user-preference-driven scale and max TSS; `strength_rpe_max` stored in `user_preferences` configures the RPE scale ceiling (e.g. 10 for standard RPE, 20 for Borg)
- **Duration curves** — `backend/services/per_workout_curves.py` computes best-average power and pace for a configurable duration ladder (1 s to 90 min) within each individual workout using a rolling-window algorithm on per-second streams, falling back to lap then workout-level aggregates; `backend/services/duration_curve_best_effort.py` merges per-workout curves into a per-athlete best-effort curve stored in `athlete_duration_curves`
- **Auto-threshold suggestions** — `backend/services/threshold_suggestions.py` derives suggested FTP (95 % of best 20-min power, or fallback window at low confidence), threshold HR, and threshold pace from a user's duration curve and recent run history; each suggestion includes a `high_confidence` (bool) field and a `formula` string (human-readable derivation, e.g. "best 20-minute power multiplied by 0.95"); manually set preferences are excluded from suggestions; `GET /api/thresholds/suggestions` returns only pending suggestions (those not yet accepted)
- **Accept-suggestion flow** — `POST /api/thresholds/suggestions/accept` writes accepted threshold values to `user_preferences` with `source = "user_accepted"` and stamps the corresponding `*_updated_at` timestamp; returns 422 when a requested key has no pending suggestion; accepted suggestions are suppressed from future GET calls; the Settings UI shows inline suggestion banners (with formula text and an Accept button) that write directly to preferences on click without requiring a separate Save; both this endpoint and `PATCH /api/users/me/preferences` now trigger a background full performance backfill via `backend/services/backfill_performance.py` (`backfill_performance_for_athlete` — recomputes running TSS for all historical runs then rebuilds the best-effort duration curve) so that performance scores, the fitness/fatigue/form chart, and PR detection reflect up-to-date values immediately after thresholds change
- **Unified daily training load series** — `backend/services/daily_load.py` pure function aggregates workout TSS by calendar day; exposed via `GET /api/training/daily-load` (session-user) and `GET /api/athletes/{athlete_id}/daily-load` (by athlete UUID)
- **Google Drive / Health Sync sleep import** _(added Sprint 89)_ — connects to Google Drive via OAuth and imports nightly sleep records exported by the Health Sync app (CSV format) into the `sleep_records` table; `POST /api/integrations/drive-sleep/sync` triggers an immediate import for the authenticated user; a background daemon thread runs a scheduled sync for all connected users every hour; on first Google connect a fire-and-forget backfill imports all pre-existing sleep files from Drive automatically; sleep stage columns (`deep_minutes`, `rem_minutes`, `light_minutes`, `awake_minutes`) are nullable to support CSV exports that omit stage breakdown; rows are idempotent-upserted on `(user_id, external_id)` so re-runs are safe
- **Strava sync** — OAuth connection to Strava; pulls activities and reconciles them into workouts with source badges and TSS computation; compact sync controls with last-sync timestamps in Settings → Integrations
- **Stryd integration** — encrypted credential storage; workouts merged from both Strava and Stryd show both source badges simultaneously in the training log (`has_strava` / `has_stryd` fields on list and detail responses)
- **Fitness / fatigue / form model** — `backend/services/fitness_model.py` pure function `compute_fitness_series` computes CTL (42-day EWMA), ATL (7-day EWMA), and TSB from a unified daily-load series; no SQL or side effects; consumed by the readiness endpoint and the performance chart
- **ACWR training-load guidance** — `backend/services/acwr.py` pure function `compute_acwr` classifies acute:chronic workload ratio into detraining / productive / elevated / high-risk bands; requires ≥ 28 days of history; zone thresholds: <0.8 detraining, 0.8–1.3 productive, 1.3–1.5 elevated, >1.5 high-risk
- **Per-run speed signal** — `backend/services/speed_signal.py` pure function `compute_speed_signal` scans all 1–6 min splits, classifies them via `classify_laps`, and returns the best effort ratio vs the athlete's threshold (power/pace/HR basis); four nullable columns persisted to `workouts` (`speed_signal`, `speed_signal_basis`, `speed_signal_window_seconds`, `speed_signal_source`); DB caller `compute_and_store_speed_signal` handles all I/O; computed on ingest and on threshold change
- **Per-run endurance signal** — `backend/services/endurance_signal.py` pure function `compute_endurance_signal` measures aerobic decoupling (first-half vs second-half efficiency) for runs ≥ 40 min; five nullable columns persisted to `workouts` (`endurance_signal`, `decoupling_percent`, `efficiency_first_half`, `efficiency_second_half`, `endurance_signal_source`); `endurance_signal = 100 - decoupling_percent` floored at 0
- **Signal backfill** — `backend/services/backfill_signals.py` function `backfill_signals_for_athlete` recomputes both signals for every historical run of an athlete; idempotent; auto-triggered after threshold saves (chains after the M0 TSS backfill); manual runs via `scripts/backfill_signals.py --user-id <UUID> [--env uat|prd]`
- **Running performance scores** — `backend/services/running_performance.py` derives endurance and speed scores from per-run signals using a duration-weighted EWMA (90-day trailing window); when runs carry a stored `speed_signal` the scoring uses it directly; without it, falls back to the lap-based efficiency path for backward compatibility; response includes `qualifying_session_count`; normalised to the athlete's own historical range with no hardcoded external thresholds; zone constants provided by `backend/services/zone_constants.py`; exposed via `GET /api/athletes/{athlete_id}/performance`; every response carries an explicit top-level `state` field (one of `scored`, `needs_thresholds`, `building_baseline`, `error`) alongside `endurance`, `speed`, and `generated_at` — when the state is not `scored` the endurance and speed values are null; HTTP 200 for scored/needs_thresholds/building_baseline, HTTP 500 with `state=error` on unexpected failures; user-facing message strings are centralised in `backend/services/performance_constants.py`; structured observability: INFO-level diagnostic log on every request via `_build_performance_diagnostic` (8 flat keys: runs_considered, runs_with_laps, laps_total, laps_with_band, thresholds_present, ftp_present, threshold_hr_present, threshold_pace_present) and DEBUG-level full log entry via `_build_performance_log_entry`; `POST /api/performance/backfill` triggers the full backfill pipeline via `backend/services/backfill_performance.py` to recompute running TSS for all historical runs and rebuild the athlete's best-effort duration curve; idempotent and safe to call multiple times
- **Session signal panel** — run detail panel now includes a "This session signal" card showing the persisted `endurance_signal` and `speed_signal` values with a `contributes_to` hint sentence; null signals show a note explaining why (e.g. "run under 40 min", "no hard effort"); rendered by `frontend/js/lib/run-detail-view.js` from fields added to the `/api/workouts/{id}` response by `_compute_session_signals` in `backend/main.py`
- **Training > Performance sub-tab** — the Performance tab in the Training page is now fully implemented (replaces the "coming soon" placeholder): shows Endurance and Speed score rings (0–100) with direction label and trend sparkline, a CTL/ATL/TSB fitness chart with 30D/90D/6M/1Y date-range selector and today marker, ACWR guidance computed client-side from the daily-load series, and a personal-records strip; score cards render four discrete states — `scored` (ring + sparkline), `needs_thresholds` (CTA to set thresholds in Settings), `building_baseline` (reason text from the API), and an error state for fetch failures; powered by `frontend/js/training-performance.js`; mockup committed to `docs/mockups/performance-tab.md`
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
| `GET /api/athletes/{athlete_id}/performance` | Returns endurance and speed running performance scores for an athlete. Both scores are normalised to the athlete's own historical range. Response always includes a top-level `state` field (one of: `scored`, `needs_thresholds`, `building_baseline`, `error`), plus `endurance`, `speed`, and `generated_at`. When state is not `scored` the endurance and speed values are null. HTTP 200 for scored/needs_thresholds/building_baseline; HTTP 500 with `state=error` on unexpected failures. Returns 404 if the athlete does not exist. |
| `POST /api/performance/backfill` | Trigger the full performance backfill pipeline for the authenticated athlete: recomputes running TSS for all historical run workouts and rebuilds the best-effort duration curve. Idempotent. Returns `{thresholds_found, runs_processed, tss_recomputed, curve_rebuilt, reason}`; when `thresholds_found` is false no writes are made. |
| `GET /api/performance/chart` | Returns aligned CTL/ATL/TSB/endurance/speed time-series for a performance chart. Params: `athlete_id` (UUID), `start_date`, `end_date` (YYYY-MM-DD). Always returns HTTP 200; error cases return empty arrays with a machine-readable `reason` field (`athlete_not_found`, `invalid_date_range`, `no_data_in_range`). Response: `{dates, ctl, atl, tsb, endurance_score, speed_score, building_baseline, reason}`. The `building_baseline` flag reflects CTL/ATL/TSB history only and is not affected by endurance/speed score readiness. |
| `POST /api/weight-plans` | Create a new weight plan for the authenticated user; deactivates any previously active plan; body: `start_weight`, `goal_weight`, `start_date` (required), optional `goal_date`, `rate` (kg/week), `phase` (`cut`/`bulk`/`maintain`); returns 201 |
| `GET /api/weight-plans/active` | Return the current active weight plan for the authenticated user; 404 if none exists |
| `PATCH /api/weight-plans/{plan_id}` | Update mutable fields (`goal_weight`, `goal_date`, `rate`, `phase`) on a plan owned by the session user; 403 if not the owner |
| `DELETE /api/weight-plans/{plan_id}` | Soft-deactivate a weight plan (`active → false`); does not delete the row; 403 if not the owner |
| `POST /api/weight-entries` | Create a weight entry; body: `user_id`, `entry_date`, `weight_kg`, optional `entry_time`, `notes`, `source` |
| `GET /api/weight-entries` | List weight entries; `user_id` required; `from`/`to` (YYYY-MM-DD) range (default last 90 days, max 365) |
| `PATCH /api/weight-entries/{entry_id}` | Update `weight_kg`, `entry_date`, `entry_time`, or `notes` on a single entry |
| `DELETE /api/weight-entries/{entry_id}` | Delete a single weight entry (204) |
| `POST /api/weight-targets` | Create a new weight target; sets any existing active target to `replaced`; body: `user_id`, `start_weight_kg`, `start_date`, `target_weight_kg`, `target_date` |
| `GET /api/weight-targets/active` | Get the active weight target with computed fields: `progress_pct`, `kg_to_go`, `days_remaining`, `required_pace_kg_per_week`, `current_pace_kg_per_week`, `projected_end_date`, `status_label`, `plan_today_kg`, `gap_kg`, `gap_direction`, `gap_basis`, `milestones`, `projected_hit_date` (extrapolated from 7-day pace; `null` if pace is zero or moving away from goal) |
| `GET /api/weight-targets/arrival-projection` | Return projected arrival date and weekly rate for the session user's active weight goal; response: `{projected_arrival_date, projected_rate, recent_rate, reason}` — `reason` is `null` on success or one of `no_active_plan`, `no_active_goal`, `insufficient_data`, `not_trending_toward_goal` |
| `POST /api/weight-targets/{goal_id}/what-if` | Simulate a what-if weight projection for an active goal at a caller-supplied rate; body: `{"assumed_rate": float}` (kg/week, signed); response: `{simulated_line: [{date, weight}], arrival_date: YYYY-MM-DD\|null}`; 422 on zero/non-finite/wrong-direction/out-of-bounds rates or missing weight entries |
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
| `GET /api/habits/adherence` | Returns per-habit adherence (7-day window), trend (`stable`/`declining`), best/worst day of week, and coaching nudge copy. Response: `{building (bool), reason (str\|null), habits (list)}`. `building: true` when all habits have fewer than 7 distinct logged days. HTTP 200 always. |
| `GET /api/habits/week` | Single-batch habits week view: `daily_habits` (checkmark grid), `weekly_habits` (progress bars), `day_scores`, `week_totals`, `wheel` (7-segment arc states), `streaks`, and `last_week` summary. Optional `week_start` param (YYYY-MM-DD Monday); defaults to current Bangkok week. |
| `GET /api/habits/summary` | Returns all active habits for the session user (ordered by `sort_order`) with each habit's standard fields plus `current_streak` (int — days; 0 for non-`daily_checkmark` tracking types). Used by the Today quick-log card on the Habits page. |
| `POST /api/habits/{habit_id}/log` | Log a habit entry; body: optional `log_date`, `value`, `notes`, `mode` (`set` replaces / `add` increments existing value; default `set`). Backfill window enforced: only dates within the current Bangkok week are writable. |
| `GET /api/about` | Returns app version, git SHA, environment, and changelog availability |
| `POST /api/integrations/drive-sleep/sync` | Trigger an immediate Drive/Health Sync sleep file import for the authenticated user; returns `{files_seen, rows_imported, rows_updated, rows_skipped}`; 422 if no Google Drive integration is connected |
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
| `POST /api/plans` | Create a training plan for the session user; body: `name` (required), optional `ramp_rate`, `taper_start`, `taper_length`, `taper_shape` (`linear`/`step`/`exponential`); returns 201 |
| `GET /api/plans/{plan_id}` | Return a single training plan; 403 if not owned by session user |
| `PATCH /api/plans/{plan_id}` | Update mutable plan fields; 403 if not owned by session user |
| `GET /api/plans/{plan_id}/races` | List all races for the plan ordered by date |
| `POST /api/plans/{plan_id}/races` | Create a race entry; body: `date` (YYYY-MM-DD), `distance` (km), `type` (`race`/`checkpoint`), optional `name`, `goal_time_seconds`; returns 201 |
| `GET /api/plans/{plan_id}/races/{race_id}` | Return a single race entry; 404 if not found |
| `PATCH /api/plans/{plan_id}/races/{race_id}` | Update mutable race fields; 404 if not found |
| `DELETE /api/plans/{plan_id}/races/{race_id}` | Delete a race entry (204) |
| `GET /api/plans/{plan_id}/races/{race_id}/checkpoints` | List checkpoints for a race ordered by target date |
| `POST /api/plans/{plan_id}/races/{race_id}/checkpoints` | Create a checkpoint; body: `type` (required), optional `distance` (km); returns 201 |
| `PATCH /api/plans/{plan_id}/races/{race_id}/checkpoints/{checkpoint_id}` | Update checkpoint `type` or `distance` |
| `DELETE /api/plans/{plan_id}/races/{race_id}/checkpoints/{checkpoint_id}` | Delete a checkpoint (204) |
| `GET /api/plans/{plan_id}/projection` | Return CTL/ATL/TSB projection series, per-race estimated finish times, and confidence band for the plan's horizon; uses 28-day trailing average load; threshold pace from user preferences drives finish-time estimates |
| `GET /api/projection` | Aggregated data for the `/projection` screen: 180-day form curve, projected form toward the A-race, A/B/C race markers (with `recalibrates_here` on the earliest upcoming B-race), and current Endurance/Speed scores |
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
