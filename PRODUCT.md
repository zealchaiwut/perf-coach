# Perf Coach — Product Overview

Personal performance dashboard for a solo athlete. Tracks fitness, recovery, and daily habits in one place.

## Core Purpose

Give a single user a clear daily picture of their physical readiness by combining training load, sleep, HRV, weight, and habit data.

## Primary User

Solo athlete / self-coached individual who wants data-driven decisions about training intensity and recovery.

## Key Features

- **Home dashboard** — daily readiness score, weight trend, recent workouts, PR widget, weekly summary
- **Training log** — grouped workout list by week, detail panel, CSV export, Strava/Stryd sync
- **Calendar** — month grid with energy/sleep dots, day-detail modal, daily metrics entry
- **Weight tracker** — entries, targets, chart, inline edit/delete
- **Habits tracker** — daily toggles, stats, streak
- **Settings** — profile, security, Strava/Google OAuth connect

## Tech Stack

- FastAPI + SQLAlchemy + Alembic (Python 3.12)
- Vanilla JS frontend (no framework), Neon/Postgres
- Strava and Stryd integrations for workout data
- Deployed on Render (PRD on `main`, UAT on `develop`)

## Data Model Highlights

- `workouts` — merged from Strava + Stryd, with TSS, pace, HR, elevation
- `daily_metrics` — RHR, HRV, sleep quality/duration, energy, mood per day
- `training_load_snapshots` — EWMA-based CTL/ATL/TSB per day
- `weight_entries` + `weight_targets` — body weight tracking
- `users` — single user, password-hashed, optional Google/Strava OAuth
