# Changelog

## Sprint 51 — Weight tracking shipping polish

- #411: Add weight entries and weight targets CSV export endpoints
- #412: Build weight page frontend (desktop + mobile)
- #413: Build weight target management page (/weight/targets)
- #414: Wire CSV export buttons on weight and weight-targets pages
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
