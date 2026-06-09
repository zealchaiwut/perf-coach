# Changelog

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
