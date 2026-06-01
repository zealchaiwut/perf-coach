# Database Schema

Neon Postgres. Migrations managed by Alembic (`alembic/versions/`).

## Tables

### users

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default `gen_random_uuid()` |
| name | VARCHAR(100) | NOT NULL, UNIQUE |
| created_at | TIMESTAMPTZ | default `now()` |

### weight_entries

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default `gen_random_uuid()` |
| user_id | UUID | FK → users.id, NOT NULL |
| weight_kg | NUMERIC(5,2) | NOT NULL |
| recorded_date | DATE | NOT NULL |
| created_at | TIMESTAMPTZ | default `now()` |

Unique constraint: `(user_id, recorded_date)` — one entry per user per day.

### habits

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default `gen_random_uuid()` |
| user_id | UUID | FK → users.id, NOT NULL |
| name | VARCHAR(100) | NOT NULL |
| display_order | INT | NOT NULL, default 0 |
| created_at | TIMESTAMPTZ | default `now()` |
| archived_at | TIMESTAMPTZ | nullable — soft delete |

### habit_logs

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default `gen_random_uuid()` |
| habit_id | UUID | FK → habits.id, NOT NULL |
| user_id | UUID | FK → users.id, NOT NULL |
| logged_date | DATE | NOT NULL |
| created_at | TIMESTAMPTZ | default `now()` |

Unique constraint: `(habit_id, logged_date)` — one log per habit per day.

### workouts

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default `gen_random_uuid()` |
| user_id | UUID | FK → users.id, NOT NULL, ON DELETE CASCADE |
| workout_date | DATE | NOT NULL |
| name | VARCHAR(200) | NOT NULL |
| workout_type | VARCHAR(50) | NOT NULL — e.g. "strength", "running", "race", "yoga" |
| remarks | TEXT | nullable |
| tss | FLOAT | nullable, CHECK `tss >= 0` if present |
| tss_source | VARCHAR(20) | nullable, CHECK `tss_source IN ('manual', 'calculated')` if present |
| distance_km | NUMERIC(7,3) | nullable, CHECK `distance_km >= 0` if present |
| duration_seconds | INT | nullable, CHECK `duration_seconds >= 0` if present |
| avg_hr | INT | nullable, CHECK `avg_hr BETWEEN 20 AND 250` if present |
| max_hr | INT | nullable, CHECK `max_hr BETWEEN 20 AND 250` if present |
| elevation_m | INT | nullable |
| created_at | TIMESTAMPTZ | default `now()` |

Index: `(user_id, workout_date DESC)`

#### tss_source contract

`tss_source` is **server-managed** — the client never sets it directly.

- When a workout is created or updated with a `tss` value, the server sets `tss_source = 'manual'`.
- When `tss` is explicitly sent as `null`, the server clears both `tss` and `tss_source` to `NULL`.
- If the client sends a `tss_source` field it is silently ignored.
- Future auto-calculation will set `tss_source = 'calculated'`, allowing the auto-calc to overwrite only calculated rows while preserving user-entered values.

### workout_exercises

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default `gen_random_uuid()` |
| workout_id | UUID | FK → workouts.id, NOT NULL, ON DELETE CASCADE |
| display_order | INT | NOT NULL, default 0 — sort order within workout |
| name | VARCHAR(200) | NOT NULL |
| sets | INT | nullable, CHECK `sets > 0` if present |
| reps | VARCHAR(50) | nullable — accepts "10", "10,8,6", "AMRAP" |
| weight | VARCHAR(50) | nullable — accepts "20kg", "BW", "DB 12kg" |
| duration | VARCHAR(50) | nullable — accepts "30 min", "5km", "120s" |
| rpe | INT | nullable, CHECK `rpe BETWEEN 1 AND 10` if present |
| created_at | TIMESTAMPTZ | default `now()` |

Index: `(workout_id, display_order)`

Free-text `reps`, `weight`, and `duration` are intentional — real training data uses mixed
formats. Strict typing would complicate historical data entry and sprint-5 TSS parsing.

### daily_metrics

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default `gen_random_uuid()` |
| user_id | UUID | FK → users.id (CASCADE), NOT NULL |
| metric_date | DATE | NOT NULL |
| resting_hr | INT | nullable, CHECK `resting_hr BETWEEN 20 AND 200` |
| hrv | INT | nullable, CHECK `hrv BETWEEN 0 AND 300` |
| sleep_hours | NUMERIC(3,1) | nullable, CHECK `sleep_hours BETWEEN 0 AND 24` |
| sleep_quality | INT | nullable, CHECK `sleep_quality BETWEEN 1 AND 5` |
| energy | INT | nullable, CHECK `energy BETWEEN 1 AND 5` |
| mood | INT | nullable, CHECK `mood BETWEEN 1 AND 5` |
| notes | TEXT | nullable |
| created_at | TIMESTAMPTZ | default `now()` |
| updated_at | TIMESTAMPTZ | default `now()`, updated automatically via trigger |

Unique constraint: `(user_id, metric_date)` — one row per user per day.

### daily_readiness

Stores pre-computed readiness scores derived from `daily_metrics` by the readiness job.

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default `gen_random_uuid()` |
| user_id | UUID | FK → users.id (CASCADE), NOT NULL |
| date | DATE | NOT NULL |
| score | NUMERIC(5,2) | NOT NULL, CHECK `score BETWEEN 0 AND 100` |
| components | JSONB | NOT NULL — per-signal additive contributions (see below) |
| computed_at | TIMESTAMPTZ | NOT NULL, default `now()` |
| daily_metric_id | UUID | FK → daily_metrics.id (SET NULL on delete), nullable |

Unique constraint: `(user_id, date)` — one readiness row per user per day.

#### `components` JSONB structure

```json
{
  "hrv_contribution":    12.3400,
  "rhr_contribution":    10.0000,
  "sleep_contribution":  25.0000,
  "energy_contribution": 18.7500
}
```

Each field is the signal's additive share of `score`; the four values sum to `score` (within floating-point tolerance). A value of `0.0` means either the signal was absent/had insufficient baseline data, or it was present but scored at the minimum.

#### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/readiness/today` | Readiness record for today (server timezone). 404 if none exists. |
| GET | `/api/readiness?from=YYYY-MM-DD&to=YYYY-MM-DD` | Readiness records for a date range, one entry per day (null for days with no data), ordered ascending. |

### training_load_snapshots

Pre-computed daily training load values (CTL/ATL/TSB) written by the load snapshot job.

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default `gen_random_uuid()` |
| user_id | UUID | FK → users.id (CASCADE), NOT NULL |
| snapshot_date | DATE | NOT NULL |
| tss_for_day | INT | NOT NULL |
| ctl | FLOAT | NOT NULL — Chronic Training Load |
| atl | FLOAT | NOT NULL — Acute Training Load |
| tsb | FLOAT | NOT NULL — Training Stress Balance (`ctl - atl`) |
| computed_at | TIMESTAMPTZ | NOT NULL, default `now()` |

Unique constraint: `(user_id, snapshot_date)` — one snapshot per user per day.
Index: `(user_id, snapshot_date)`.

### Training Log

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/training-log` | Returns workout and optional rest-day entries for a date range, plus a top-level `load_context` block. Query params: `user_id`, `from` (default: 30 days ago), `to` (default: today), `types` (workout_type filter), `search` (name/remarks text search), `include_rest` (default: true). Each workout entry includes `duration_seconds`, `duration_minutes`, `distance_km`, `avg_hr`, `elevation_m`, `average_pace_seconds_per_km` (run/bike only), `tss`, `source`, and `notes`. |

#### `load_context` response field

Present when the user has ≥ 7 days of training data; `null` otherwise.

```json
{
  "ctl": 55.0,
  "atl": 60.0,
  "tsb": -5.0,
  "interpretation": "Productive — carrying fatigue but building fitness",
  "as_of": "2026-06-01"
}
```

Values are read from `training_load_snapshots` for today when a snapshot exists; computed on-demand otherwise. Interpretation thresholds: Fresh (TSB > 5), Neutral (−5 to 5), Productive (−20 to −5), Overreached (TSB < −20). See `docs/training-load.md` for the full model.

Both endpoints require `user_id` as a query parameter and return:

```json
{
  "date": "2026-05-27",
  "score": 66.25,
  "hrv_contribution": 12.3400,
  "rhr_contribution": 10.0000,
  "sleep_contribution": 25.0000,
  "energy_contribution": 18.7500,
  "missing_data": {
    "hrv": false,
    "rhr": false,
    "sleep": false,
    "energy": true
  }
}
```

`missing_data` flags indicate which source signals in `daily_metrics` were `NULL` on the date the score was computed (true = signal was absent; false = signal was present).

## Cascade behaviour

- Deleting a **user** cascades to their workouts, then to all workout_exercises of those workouts.
- Deleting a **workout** cascades to all its workout_exercises rows.
- Deleting a **user** also cascades to their `daily_metrics` and `daily_readiness` rows.
- Deleting a **daily_metrics** row sets `daily_readiness.daily_metric_id` to NULL (score is preserved).

## Migrations

| Revision | Description |
|----------|-------------|
| a1b2c3d4e5f6 | Create users and weight_entries |
| b2c3d4e5f6a7 | Create habits and habit_logs |
| c3d4e5f6a7b8 | Create workouts table |
| d4e5f6a7b8c9 | Create workout_exercises table |
| e5f6a7b8c9d0 | Fix FK cascade, CHECK constraints, and indexes on workout tables |
| f6a7b8c9d0e1 | Add tss and tss_source columns to workouts |
| 38a0b1c2d3e4 | Create daily_metrics table |
| 59a1b2c3d4e5 | Create daily_readiness table |
| a1b2c3d4e5f7 | Add distance_km, duration_seconds, avg_hr, max_hr, elevation_m to workouts |

Run `alembic upgrade head` to apply all migrations.
Run `alembic downgrade -1` to roll back one step.
Run `alembic downgrade -2` to roll back both workout-related tables.
