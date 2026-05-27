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

## Cascade behaviour

- Deleting a **user** cascades to their workouts, then to all workout_exercises of those workouts.
- Deleting a **workout** cascades to all its workout_exercises rows.

## Migrations

| Revision | Description |
|----------|-------------|
| a1b2c3d4e5f6 | Create users and weight_entries |
| b2c3d4e5f6a7 | Create habits and habit_logs |
| c3d4e5f6a7b8 | Create workouts table |
| d4e5f6a7b8c9 | Create workout_exercises table |
| e5f6a7b8c9d0 | Fix FK cascade, CHECK constraints, and indexes on workout tables |
| f6a7b8c9d0e1 | Add tss and tss_source columns to workouts |

Run `alembic upgrade head` to apply all migrations.
Run `alembic downgrade -1` to roll back one step.
Run `alembic downgrade -2` to roll back both workout-related tables.
