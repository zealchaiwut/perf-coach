# Changelog

## Sprint 95 — Bodyweight EWMA trend, energy-availability proxy, and body-composition modifier

- #1153: Add daily bodyweight logging by date
- #1154: Compute bodyweight trend via EWMA smoothing
- #1155: Compute weekly percent bodyweight rate of change from EWMA
- #1157: Compute energy availability proxy and flag low state
- #1158: Model body-modifier sign-flip around deficit threshold
- #1159: Wire body modifier into power-to-weight score term
- #1160: Build weight-trend view with EWMA and weekly rate
- #1161: Surface guardrail warning when loss is excessive or EA is low

## Sprint 94 — Strength & plyo session logging and the economy ceiling model

- #1142: Add strength session logging table and model
- #1143: Add plyometric session logging with foot-contacts
- #1144: Add strength and plyo session CRUD API
- #1145: Build strength and plyo session entry UI
- #1146: Compute economy stimulus from strength and plyo load
- #1147: Model delayed ceiling lift via lagged stimulus ramp
- #1148: Wire economy ceiling bonus into projection score-ceiling hook
- #1149: Backfill economy model across historical sessions
- #1150: Show economy contribution in projection/score view
- #1151: Make economy priors tunable via config

## Sprint 93 — Intensity-band classification, distribution chart, and polarized-split check

- #1128: Classify each lap by intensity band
- #1129: Aggregate session time-in-band into low/moderate/high percentages
- #1130: Add rolling intensity distribution over trailing windows
- #1131: Add polarized-split target-band deviation check
- #1133: Build intensity-distribution stacked bar chart
- #1134: Add polarized-check indicator for on-target vs grey-zone

## Sprint 92 — Training plan model, projection engine, and race time-curve chart

- #1099: Add migration for races_checkpoints and planned_load tables
- #1100: Add races/checkpoints CRUD API to plan router
- #1101: Add ramp and taper parameters to plan model
- #1102: Generate planned-load schedule from ramp/taper params
- #1103: Build plan editor UI for races and checkpoints
- #1104: Add ramp/taper controls with schedule preview to plan editor
- #1105: Scaffold projection.py and roll CTL/ATL/TSB forward
- #1106: Map projected CTL to Endurance/Speed score ceiling
- #1107: Derive expressible score from TSB form factor
- #1108: Convert expressible score to estimated race finish time
- #1109: Add Riegel cross-distance equivalence for race entries
- #1110: Add widening confidence band to projection horizon
- #1111: Add B-race tightening hook to confidence band
- #1112: Expose training projection via plan API endpoint
- #1113: Render projected time-curve chart with confidence band
- #1114: Assemble projection screen with markers and scores
## Sprint 91 — Weekly/monthly summaries, rate guardrail, and summary digest card

- #1055: Add weekly summary aggregation endpoint
- #1056: Add monthly summary endpoint with supercompensation detection
- #1057: Add rate guardrail and stressor ramp check
- #1058: Add summary digest card to Log tab with weekly/monthly toggle
- #1060: Surface guardrail warning in summary cards

## Sprint 89 — Google Drive / Health Sync sleep file import

- #1032: Add sleep_records table and idempotent Alembic migration
- #1034: Parse Health Sync sleep CSV into sleep_records
- #1035: Add scheduled and on-demand sleep file sync from Google Drive
- #1038: Backfill historical sleep data on first Google Drive connect

## Sprint 88.1 — Lap classification order, frontend four-state rendering, and thresholds editor polish

- #1019: Classify laps before scoring in performance endpoint (fixes classification order so band is assigned before score computation)
- #1021: Render four explicit performance states in frontend (scored / needs_thresholds / building_baseline / error driven by top-level state field)
- #1022: Settings thresholds editor writes FTP, threshold heart rate, threshold pace (pace input now accepts numeric sec/km; blank inputs when no value stored)

## Sprint 88 — Performance state field, diagnostic logging, backfill pipeline, and fitness chart fix

- #1018: Add diagnostic INFO logging to performance endpoint (runs_considered, laps_with_band, threshold flags per request)
- #1020: Return explicit top-level state field from performance endpoint (scored / needs_thresholds / building_baseline / error)
- #1023: Add POST /api/performance/backfill and full backfill pipeline to recompute historical run TSS and duration curve
- #1024: Fix Fitness Fatigue Form chart building_baseline propagation from endurance/speed score readiness

## Sprint 86 — Habits timezone fix, weight validation, range-token clarity, and test coverage

- #450: Memoize autofill computation per source in GET /api/habits/week
- #451: Fix Bangkok timezone in best_streak() for consistency
- #452: Extract backfill window validation as reusable FastAPI dependency
- #453: Extract habits.html inline CSS to frontend/css/habits.css
- #470: Document habit tracking_type immutability constraint in slide-over PATCH path
- #471: Add comprehensive date parsing validation tests for habit log endpoint
- #472: Add type-safe weight computation tests for project_hit_date
- #473: Replace magic-number timedeltas with RANGE_OFFSETS constant in weight-chart endpoint
- #474: Verify WeightEntry.entry_date index exists for range=ALL queries
- #475: Document --accent WCAG contrast and add verification tests for log button
- #477: Validate goal vs start weight before saving target in _saveEditPanel
- #503: Remove dead user_id query param from calendar.js weight-entries GETs
- #504: Remove user_id from calendar.js weight-entries POST body
- #476: Add visual regression tests for progress card bar positioning

## Sprint 85 — Performance score states, PR reason strings, logging observability, and duration-curve gap fix

- #927: Add observability to diagnose null performance scores
- #928: Classify laps before scoring in performance endpoint
- #929: Surface needs_thresholds state when athlete has no thresholds set
- #930: Render four distinct score-card states on Performance tab
- #984: Add structured INFO logging to PR endpoint caller
- #985: Fix duration curve data gap: lap classification and threshold population
- #986: Return explicit reason string for uncomputable personal records
- #987: Add unit tests for PR endpoint caller: logging and empty-curve branch

## Sprint 83 — Performance observability, needs-thresholds state, auto-detected PRs, and lap-classification backfill

- #910: Add observability to diagnose null performance scores
- #911: Classify laps before scoring in performance endpoint
- #912: Surface needs_thresholds state in performance endpoint
- #913: Fix empty Personal Records for athletes with run history
- #914: Backfill lap classification and trigger recompute on threshold save

## Sprint 80 — Weight goal projection and what-if simulation

- #874: Add pure function compute_planned_series(plan, as_of_date)
- #876: Add pure function to project goal arrival date
- #877: Add simulate_what_if pure function for weight projection
- #878: Add projection endpoint for arrival date and rate
- #879: Add what-if simulation endpoint for goal rate preview
## Sprint 81 — Habit-outcome alignment function

- #881: Add align_habit_and_outcome pure function with lag support

## Sprint 79 — Weight plans table, plan-line recompute, and CRUD endpoints

- #861: Add weight_plans table: migration and SQLAlchemy models
- #863: Add recompute_plan_from_progress pure function
- #864: Add CRUD endpoints for user weight plan

## Sprint 78.1 — Create and Edit Habit form

- #832: Build Create and Edit Habit Form (Slide-Over/Modal)

## Sprint 78 — Habits page shell, Today quick-log, and history calendar

- #827: Build Habits page shell and Today quick-log surface
- #828: Wire Today quick-log writes with upsert and streak refresh
- #829: Add Habits history calendar with day-status cells
- #830: Add habit filter to history calendar view


## Sprint 77 — Habits v2 schema, streak/consistency services, and summary endpoint

- #821: Add habits and habit_logs migrations and SQLAlchemy models
- #822: Add is_period_met pure function for habit completion logic
- #823: Add compute_streak pure function for habit streaks
- #824: Add compute_consistency pure function for habit schedule adherence
- #826: Add habits summary endpoint with streaks and consistency

## Sprint 76 — Training > Performance sub-tab and settings thresholds/zones enhancements

- #810: Add Settings section for training thresholds and zones
- #811: Implement Training > Performance sub-tab with real data

## Sprint 75 — Performance curve, form projection, taper guidance, race readiness summary, and post-race calibration

- #709: Add performance_curve pure function to fitness model
- #710: Add forward form projection to target date
- #711: Add taper_recommendation function for race date guidance
- #712: Add peak-tracking and race-specificity progress functions
- #713: Add race-readiness summary endpoint with timeline_markers
- #714: Add post-race calibration of personal fitness constants

## Sprint 74 — Strength PR detection, race checkpoints, and run auto-detection

- #704: Add personal-record detection from run history
- #705: Add PR storage, on-ingest comparison, and records feed
- #706: Add races table, Alembic migration, and SQLAlchemy model
- #707: Add race_checkpoints table and SQLAlchemy model
- #708: Add CRUD and auto-detection for races and checkpoints

## Sprint 73 — Fitness model, ACWR, running performance scores, and performance chart

- #697: Add readiness endpoint exposing CTL, ATL, TSB tiles
- #698: Add fitness, fatigue, and form (CTL/ATL/TSB) model
- #701: Add Endurance and Speed Running Performance Scores
- #702: Add compute_acwr training-load guidance function
- #703: Add performance chart time-series API endpoint

## Sprint 72 — Per-workout duration curves, athlete daily load, and threshold accept-flow

- #692: Suggest thresholds automatically from duration curve
- #693: Add unified daily training load series endpoint
- #694: Compute power and pace duration curves per workout
- #695: Aggregate and expose per-athlete best-effort duration curve
- #696: Add accept-suggestion flow for thresholds

## Sprint 71 — Lap classifier rewrite, session profile improvements, and strength TSS with configurable RPE max

- #678: Add lap intensity classification for session-profile detection
- #681: Add interval and set detection to session-profile
- #682: Implement detect_session_profile with precedence and data-quality gate
- #683: Expose detected session profile on full workout endpoint
- #688: Add strength TSS via session-RPE method
- #689: Add per-set RPE refinement method for strength TSS

## Sprint 70 — Activity streams, normalized power, running TSS, and golden test fixture

- #665: Add power, cadence, stride, and lap-type columns via Alembic migration
- #667: Ingest activity streams on Strava and Stryd sync
- #668: Select stream channels when workout merges two sources
- #669: Add compute_normalized_power pure function
- #671: Compute and store normalized power during workout ingestion
- #672: Add golden test fixture for workout metric calculations
- #673: Add pure function for TSS calculation via power
- #674: Add pure running TSS pace calculation function
- #675: Add pure HR-based TSS calculation function

## Sprint 69 — Run view redesign, Strength detail, Training Plan tab, and Settings UI

- #643: Convert Log Workout to slide-over panel
- #644: Build STRENGTH body for Log-workout slide-over
- #646: Redesign Run detail view header and load block
- #647: Add Session Profile and Laps to Run Detail View
- #648: Add route strip to Run view and redesign Strength detail
- #650: Build Training > Plan Sub-Tab with Race Plan UI
- #651: Add Settings UI for Training Thresholds and Zone Ranges

## Sprint 68.1 — Mobile week-strip and close button polish

- #639: Add mobile week-strip to Training Log sub-tab
- #642: Change Training Log close button to grey

## Sprint 68 — Training page sub-tabs, Readiness widget, and Weekly Volume chart

- #636: Add Log/Plan/Performance sub-tabs to Training page
- #637: Build Training Log sub-tab with filter and search
- #640: Add Readiness Widget to Training Log Sub-Tab
- #641: Add Weekly Volume & Load Chart to Training Log

## Sprint 67 — Race targets, fitness projections, and race readiness endpoint

- #604: Add races table and SQLAlchemy model
- #605: Add CRUD endpoints for user race targets
- #606: Add performance_curve pure function to fitness model
- #607: Add forward form projection to a target date
- #608: Add taper_recommendation function for race-day form targeting
- #609: Add peak-line on-track assessment to form tracking
- #610: Add race specificity progress tracker function
- #611: Add GET /api/races/{id}/readiness combined endpoint

## Sprint 66.1 — Dual source badges, compact sync controls, and weight chart redesign

- #601: Show both Strava and Stryd badges on merged workouts (has_strava/has_stryd on training-log and workout-list responses)
- #602: Add compact sync controls with real last-sync times to Settings → Integrations
- #633: Redesign weight trend chart with three-zone axes (BMI zones, moving average, custom SVG v8)

## Sprint 66 — Performance Thresholds settings expansion and Zone 2 habit provisioning

- #596: Add Max HR field to Performance Thresholds settings (user_preferences.max_hr, default 190 bpm)
- #597: Add Threshold Pace, Zone 2 HR band, and Weekly Zone 2 Target to Settings (user_preferences)
- #598: Use user-preference HR band for Zone 2 detection in Run view (replaces hardcoded 130–155 bpm)
- #599: Add 'Track Zone 2' opt-in button to provision a Zone 2 habit from Settings (with server-side duplicate guard)

## Sprint 65 — Strength TSS, duration curves, threshold suggestions, and daily load series

- #588: Compute power and pace duration curves per workout
- #590: Add auto-threshold suggestion from duration curve
- #591: Add accept-suggestion flow for threshold values
- #592: Add session-RPE TSS method for strength sessions
- #593: Implement per-set RPE refinement for strength TSS
- #594: Combine Strength TSS Calculation into Single Service
- #595: Add unified daily training load series

## Sprint 64 — Running TSS persistence, lap classification, and session profile detection

- #581: Add compute_running_tss service with priority-based method selection
- #582: Persist and expose computed running TSS on workouts
- #583: Classify lap intensity bands for session-profile detection
- #584: Add phase grouping for session profile detection
- #585: Add interval and set detection to session-profile pipeline
- #586: Implement detect_session_profile with precedence and data-quality gate
- #587: Expose detected session profile on full workout endpoint

## Sprint 63.1 — Activity streams table and channel selection

- #572: Add activity_streams table and SQLAlchemy model
- #574: Select stream channels when merging two workout sources

## Sprint 63 — Activity streams, running TSS, normalized power, Run View/Builder

- #567: Add Run View and Run Builder screens with Stryd/lap support
- #568: Add running TSS computation service
- #573: Ingest activity streams on Strava and Stryd sync
- #575: Add compute_normalized_power pure calculation function
- #576: Store normalized power on workout record at ingest
- #577: Add golden fixture and regression tests for workout metrics
- #578: Add pure power-branch running TSS calculation
- #580: Add HR-based TSS pure function for running

## Sprint 61.1 — Training-log detail panel a11y and dead-UI removal

- #529: Remove dead UI and fix a11y in detail panel

## Sprint 61 — Training log charts, mobile polish, Strava source parity, JS refactor

- #527: Show workout metrics and badges on mobile viewports
- #528: Surface training load and weekly volume chart on log
- #530: Normalize Strava source attribution across list and detail
- #531: Extract shared JS module for training format helpers

## Sprint 60 — Training log UX: quick-add modal, week-strip, duplicate workout, split authoring

- #522: Add inline quick-add modal for workout logging
- #523: Make week-strip day pills interactive and accessible
- #524: Add repeat-last and duplicate workout to log
- #525: Default new workout type to most recent selection
- #526: Add manual split authoring to training log detail panel

## Sprint 59.1 — Weight chart body metrics + CSS cleanup

- #520: Add body metrics and selectable moving average window
- #517: Move inline styles to styles.css, remove dead CSS

## Sprint 59 — Weight page polish: mobile, performance, streak

- #515: Fix weight chart unreadable on mobile touch devices
- #516: Fix dead chart zones and stale width comment
- #518: Fix inline-edit flicker and heavy cancel on weight rows
- #519: Reduce _reload() from 5–6 calls to targeted partial reloads
- #521: Add logging streak and adherence indicator to weight page

## Sprint 56 — Weight page redesign v2 + habits polish

- #454: Allow Users to Edit Habits After Creation
- #455: Fix 500 error when saving today's habit count
- #456: Expand Habit Icon Library and Increase Icon Size
- #457: Extend active-target endpoint with plan math
- #458: Extend weight-chart endpoint with plan, milestones, and coach data
- #459: Rebuild weight-page hero: current + log-today cards
- #460: Rebuild progress card with stat-row and plan-aware milestones
- #461: Add slide-in Edit-target panel, remove /weight/targets page
- #463: Migrate weight page to gradient design language
- #464: Rebuild weight trend chart as custom SVG

## Sprint 55 — Home redesign v7

- #436: Investigate home page widgets and confirm API readiness
- #437: Build GET /api/home/summary aggregator endpoint
- #438: Add habit quick-check strip and log-today action to home page
- #439: Add home weight widget with stepper quick-log
- #440: Add Readiness tile, Training card, and Sleep card to home page
- #441: Add Performance PRs and Recent Workouts cards
- #442: Assemble home layout with gradient design language
- #443: Home redesign: actionable habit checks + weight quick-log, two-up summary grid, single-call load — docs updated, dead widget code removed, cross-links audited, smoke verification recorded

## Sprint 54 — Habits redesign

- #428: Migrate habits page to gradient design language (Inter Tight / JetBrains Mono, floating cards)
- #429: Add `GET /api/habits/week` single-batch endpoint
- #430: Add streaks and last-week summary to habits week API
- #431: Enforce Bangkok backfill window and add increment-log mode
- #432: Build habits page hero — 7-segment week wheel + stats cards
- #433: Build daily habits grid with tap-to-check, totals, and day score row
- #434: Build weekly habits card with auto-sync badges and manual log chip
- #435: Habits redesign: week wheel, daily grid with day scores, weekly habits with workout auto-sync — polish pass, docs, dead code removal, and smoke verification

## Sprint 53.1 — Weight redesign cleanup

- #427: Weight page redesign: plan-vs-actual tracking, milestone chart, stepper quick-log, coach strip — docs updated, Chart.js dead code removed, purge script added

## Sprint 53 — Weight page redesign

- #420: Investigate Weight Page and Add Plan Math to Active-Target
- #421: Extend weight-chart endpoint with plan series and milestones
- #422: Rebuild weight page hero with 2-card layout
- #423: Rebuild weight trend chart as custom SVG
- #424: Rebuild progress card with stat-row and plan-aware milestones
- #425: Rebuild recent entries as compact side-by-side card
- #426: Migrate weight page to home design language

Features shipped in Sprint 53:
- Weight page migrated to home gradient design language (Inter Tight / JetBrains Mono, gradient background, floating cards)
- Weight page hero rebuilt as 2-card layout: current weight hero + recent-entries side panel
- Custom SVG trend chart replacing Chart.js dependency; renders actuals, 7-day MA, and plan overlay
- Progress card rebuilt with stat-row and plan-aware milestones (25 % / 50 % / 75 % / goal)
- `GET /api/weight-chart` extended with `plan_series`, `future_milestones`, `today_marker`, `logged_today`, `today_delta_kg`
- `GET /api/weight-targets/active` extended with `plan_today_kg`, `gap_kg`, `gap_direction`, `gap_basis`, `milestones`
- `backend/services/weight_plan.py` — plan math service: `plan_at`, `compute_gap`, `generate_milestones`

## Sprint 52 — Mobile fast-log & code quality

- #394: Mobile-optimise daily metrics fast-log flow — new fast-log form on home page with stepper inputs, segmented energy/mood pills, 800ms auto-save debounce, and "Log today" CTA banner
- #397: Fix empty catch blocks in home.js — add inline comments to all bare `catch (_) {}` blocks
- #398: Use parameterised SQL in Alembic migration v5j6k7l8m9n0 — wrap `op.execute()` SQL in `sa.text()`
- #399: Document broad `except Exception` in strava_sync.py — explain why broad catch is required to prevent stuck jobs
- #400: Reduce DOM-coupling in Strava sync controls — extract `_stravaHistoryOpen`, `_stravaSinceDateValue`, `_stravaShowPreview` state variables
- #401: Add `--user_id` argument to `scripts/run_strava_sync.py` CLI runner; falls back to first Strava-token user when omitted
- #402: Rename `sbadge2` to `sbadgeStryd` in training-log.js
- #405: Fix Bangkok timezone in `currentMonday()` in home-habits widget — derive week boundary from Asia/Bangkok date, not browser local timezone

## Sprint 51 — Weight tracking shipping polish

- #407: Add weight_targets table and WeightTarget model
- #408: Add CRUD endpoints for weight entries
- #409: Add weight target management endpoints with state transitions
- #410: Add /api/weight-chart endpoint with 7-day moving average
- #412: Build weight page frontend (desktop + mobile)
- #413: Build weight target management page (/weight/targets)
- #414: Add CSV export endpoints and wire Export buttons
- #415: Final polish — weight tracking docs, links, empty states

Features shipped in Sprint 51:
- Weight tracking end-to-end: log weigh-ins, 7-day moving average chart, progress toward goal target, milestone timeline, CSV export
- Weight target management: set/edit/end targets, pace tracking, projected completion date, history with filter pills
- `docs/features/weight-tracking.md` reference — data model, all API endpoints, moving-average math, status_label thresholds, projection math, known limitations
- Visual mockups committed at `docs/mockups/weight-tracking-*.html` and `docs/mockups/weight-target-management-desktop.html`
- Empty-state hardening: no NaN/undefined on zero entries; graceful no-history state on /weight/targets
- Chart.js CDN loading placeholder; date validation rejects future dates >1 day ahead

## Sprint 50 — MVP daily-use foundation

- #383: MVP investigation and root-cause analysis of daily-use friction
- #384: zone2_minutes tracking on workouts
- #385: Unified habits schema (auto-fill sources, weekly targets, archive)
- #386: Habit logs table and API
- #387: Habits CRUD API
- #388: Habit log progress API
- #389: Auto-fill linked habits on workout save
- #390: Mobile workout logging form (390px, touch-friendly)
- #391: Weekly habits-and-targets progress widget on home page
- #392: Habits management page with CRUD, reorder, archive, and starter habits
- #393: MVP polish — Bangkok time, /api/healthz, docs

Features shipped in Sprint 50:
- Habits unified system: auto-fill from zone2_minutes and workouts, weekly targets, archive/restore
- zone2_minutes tracking: workout field, API, auto-fill to Zone 2 habit
- Mobile workout logging form: full 390px flow for runs, lifts, and other workouts
- Mobile daily metrics: quick-entry card on home, mobile-optimised form
- Weekly habits home widget: Mon–Sun grid, streak badges, Bangkok-timezone week boundary
- Bangkok timezone: all day-boundary and week-start calculations use Asia/Bangkok
- `/api/healthz` endpoint for Render health checks

## Sprint 49

### Strava activity sync

Full Strava sync pipeline delivered across sprint 49:

- #370: Strava OAuth connect / callback / disconnect / token-refresh flow
- #371: `strava_activities` cache table and pull worker
- #372: Reconcile Strava activities into `workouts` rows
- #373: `GET /api/sync/strava/dry-run` preview endpoint
- #374: `sync_jobs` table and SyncJob model
- #375: Strava activity sync orchestrator service (`sync_strava_activities`)
- #376: Background sync job registry and in-memory state machine
- #377: `GET /api/sync/strava/dry-run` integration (phase 2)
- #378: Stryd power data — TSS formula routing and workout enrichment
- #379: Strava sync controls UI — settings panel, preview, polling, home banner
- #380: Sync-status visibility, history UI, CLI runner, scheduled-sync placeholder, docs
- #381: Strava E2E polish — training-log `is_stryd_synced`, data-quality endpoint, settings panel docs
- #382: `POST /api/sync/strava` trigger endpoint with job tracking and polling URL

Features included in this sprint:
- Manual sync from Settings → Integrations → Strava (date picker, preview, run)
- Real-time sync-progress polling in the settings panel and nav status bar
- `GET /api/sync/history` endpoint returning paginated SyncJob history with duration
- Collapsible sync history panel in Settings (last 5 jobs, status badges, counters)
- Scheduled sync placeholder (coming soon) in Settings
- `scripts/run_strava_sync.py` CLI runner for cron or ad-hoc use
- Deduplication via upsert on `strava_activity_id` (idempotent re-runs)
- Sync history docs at `docs/integrations/strava.md`

## Sprint 48

- #356: Add user_preferences table with per-user FTP and thresholds
- #357: Add GET and PATCH user preferences endpoints
- #358: Verify and remediate personal_records table and endpoints
- #359: Add bulk insert and history endpoints for personal records
- #360: Build settings page shell with section navigation
- #361: Build profile section in settings page
- #362: Build performance thresholds settings section
- #363: Build personal records section in settings page
- #364: Settings Integrations and About sections
- #365: Cross-link settings, polish nav, and add integration tests

## Sprint 47

- #347: Audit home page widgets and document data dependencies
- #348: Add GET /api/home/recent-workouts endpoint
- #349: Add GET /api/home/weight-summary endpoint
- #350: Add GET /api/home/personal-records endpoint for PR widget
- #351: Add GET /api/home/readiness daily readiness endpoint
- #352: Add GET /api/home/weekly-summary endpoint
- #353: Wire Home Page Weight Widget to Real API
- #354: Wire PR and Readiness widgets to real API endpoints
- #355: Wire weekly summary widget and polish home page

## Sprint 44

- #339: Build weight page frontend with hero strip, chart, progress, milestones, and recent entries
- #340: Build weight target management page at /weight/targets with active target card, milestone timeline, history, and export
- #341: Add CSV export endpoints for weight entries and targets
- #342: Weight tracking feature polish — docs, empty states, loading placeholder, date validation, home page link, and CHANGELOG

## Sprint 36

- #262: Add load_context to training-log endpoint and load docs

## Sprint 19

- #151: Build training log page shell, week strip, and filter bar
- #152: Render grouped workout list with week summaries and rest days
- #153: Build Training Log detail panel with prev/next nav
- #154: Add CSV export and commit training log mockups

## Sprint 16

- #121: Add distance, duration, heart rate, and elevation to workouts
- #122: Rename /training_log to GET /api/training-log and populate real fields
- #123: Build Training Log page shell and top action bar
- #124: Build week strip navigation on Training Log page
- #125: Add filter bar to Training Log page
- #126: Render grouped workout list with weekly summaries on Training Log
- #127: Add rest-day rows to Training Log
- #128: Add CSV Export to Training Log Page
- #129: Polish Training Log: skeletons, errors, edit actions, mobile
- #130: Add Training Log workout detail side panel

## Sprint 11

- #56: Build Training Log page — shell, week strip, filter bar, and workout list
- #57: Show rest days in Training Log with daily_metrics data
- #66: Add Trends page shell with date-range picker
- #67: Add GET /trends/summary aggregation endpoint
- #68: Add Readiness-Over-Time Chart with 7-Day Rolling Average
- #71: Add TSS and readiness correlation overlay chart
- #72: Add weekly digest summary card to home dashboard
- #73: Add HRV and RHR trend chart with baseline band
- #74: Add Sleep, Energy, and Mood Trend Chart

## Sprint 82.2 — Habit adherence analytics and nudges

- #886: Add build_nudges pure function for habit adherence coaching
- #889: Add compute_adherence_breakdown pure function for habit stats
- #890: Add detect_slipping_habits pure function for trend detection
- #892: Build Habits page adherence and nudges UI









































































































































































































## Sprint 84 — Coaching voice, focus-aware habits, compact run view, and weekly check-in

- #915: Compact run detail view for higher information density
- #916: Add Snapshot mode to Run detail view
- #920: Apply coaching copy to habit logging surfaces; `GET /api/habits/summary` now returns `week_done` and `total_logs` per habit
- #922: Add shared coaching voice module (`backend/services/coaching_voice.py`) for consistent tone across all coaching surfaces
- #923: Apply coaching copy to weight chart surfaces; verdict banner references 7-day trend with concrete next-lever; projection line framed as forward path; what-if panel headline frames scenario as still-winnable; `frontend/js/lib/weight-voice.js` is the single copy source
- #925: Add focus-aware coaching: slipping warnings, minimum version, anchoring, keystone; adds `minimum_version` and `anchor_event` columns to `habits`
- #926: Build standalone weekly check-in view (`/weekly-check-in`); new `GET /api/weekly-check-in` endpoint






























































































