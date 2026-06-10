# MVP Investigation: Habits, Workouts, and Daily Metrics

Investigation of existing codebase for habits, workouts, and daily metrics
features. Source of truth: `backend/models.py` (schema) and `backend/main.py`
(endpoints). Findings inform subsequent sprint tickets — they are not decisions.

---

## Quick Answers

| Question | Answer |
|---|---|
| Does `workouts.zone2_minutes` column exist? | **No** — not in `backend/models.py` or any migration |
| Does a `habits` table exist? | **Yes** — `habits` and `habit_logs` tables both exist |
| Do habits support weekly aggregation today? | **No** — no weekly rollup column or endpoint; stats are daily-resolution only |
| What `tracking_type` values currently exist? | `tracking_type` does **not** exist on habits. The similar column `track_type` on `personal_records` has values `'time'` and `'weight'` (check constraint) |
| What is the column name and shape of existing habits data? | See Data Model section below |

---

## Data Model

### `habits`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | NOT NULL | PK, `gen_random_uuid()` |
| `user_id` | UUID | NOT NULL | FK → `users.id` |
| `name` | String(100) | NOT NULL | |
| `display_order` | Integer | NOT NULL | Default 0 |
| `created_at` | DateTime(tz) | nullable | `now()` |
| `archived_at` | DateTime(tz) | nullable | Non-null = soft-deleted / archived |

No `tracking_type` column. Archiving via `archived_at` (soft delete pattern).

### `habit_logs`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | NOT NULL | PK |
| `habit_id` | UUID | NOT NULL | FK → `habits.id` |
| `user_id` | UUID | NOT NULL | FK → `users.id` |
| `logged_date` | Date | NOT NULL | |
| `created_at` | DateTime(tz) | nullable | `now()` |

Unique constraint: `(habit_id, logged_date)` — one log per habit per day.

No `habit_completions` or `habit_history` tables exist. `habit_logs` is the
only log table.

### `workouts`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | NOT NULL | PK |
| `user_id` | UUID | NOT NULL | FK → `users.id` (CASCADE delete) |
| `workout_date` | Date | NOT NULL | |
| `name` | String(200) | NOT NULL | |
| `workout_type` | String(50) | NOT NULL | |
| `remarks` | Text | nullable | |
| `tss` | Float | nullable | ≥ 0 |
| `tss_source` | String(20) | nullable | `'manual'` or `'calculated'` |
| `source` | String(20) | nullable | `'manual'`, `'strava'`, `'stryd'`, `'strava,stryd'`, `'stryd,strava'`, `'both'` |
| `strava_activity_url` | Text | nullable | |
| `distance_km` | Numeric(8,3) | nullable | ≥ 0 |
| `duration_seconds` | Integer | nullable | ≥ 0 |
| `avg_hr` | Integer | nullable | 20–250 |
| `max_hr` | Integer | nullable | 20–250 |
| `elevation_m` | Integer | nullable | |
| `start_time` | DateTime(tz) | nullable | |
| `strava_activity_pk` | UUID | nullable | FK → `strava_activities.id` (SET NULL) |
| `stryd_activity_pk` | UUID | nullable | FK → `stryd_activities.id` (SET NULL) |
| `manual_overrides` | JSONB | nullable | |
| `created_at` | DateTime(tz) | nullable | `now()` |

**No `zone2_minutes` column.** The column does not exist in `backend/models.py`
or any Alembic migration.

Relationships: `exercises` (→ `workout_exercises`, cascade delete),
`splits` (→ `workout_splits`, cascade delete).

### `workout_exercises`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | NOT NULL | PK |
| `workout_id` | UUID | NOT NULL | FK → `workouts.id` (CASCADE delete) |
| `display_order` | Integer | NOT NULL | Default 0 |
| `name` | String(200) | NOT NULL | |
| `sets` | Integer | nullable | > 0 |
| `reps` | Integer | nullable | |
| `weight_kg` | Numeric(6,2) | nullable | |
| `duration` | String(50) | nullable | Human-readable string |
| `rpe` | Integer | nullable | 1–10 |
| `distance_km` | Numeric(8,3) | nullable | ≥ 0 |
| `duration_seconds` | Integer | nullable | ≥ 0 |
| `avg_hr` | Integer | nullable | 20–250 |
| `created_at` | DateTime(tz) | nullable | `now()` |

### `workout_splits`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | NOT NULL | PK |
| `workout_id` | UUID | NOT NULL | FK → `workouts.id` (CASCADE delete) |
| `split_index` | Integer | NOT NULL | |
| `distance_km` | Numeric(6,3) | NOT NULL | |
| `duration_seconds` | Integer | NOT NULL | |
| `avg_hr` | Integer | nullable | |
| `created_at` | DateTime(tz) | nullable | `now()` |
| `updated_at` | DateTime(tz) | nullable | `now()` |

Unique constraint: `(workout_id, split_index)`.

### `daily_metrics`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | NOT NULL | PK |
| `user_id` | UUID | NOT NULL | FK → `users.id` (CASCADE delete) |
| `metric_date` | Date | NOT NULL | |
| `resting_hr` | Integer | nullable | 20–200 |
| `hrv` | Integer | nullable | 0–300 |
| `sleep_hours` | Numeric(3,1) | nullable | 0–24 |
| `sleep_quality` | Integer | nullable | 1–5 |
| `energy` | Integer | nullable | 1–5 |
| `mood` | Integer | nullable | 1–5 |
| `notes` | Text | nullable | |
| `created_at` | DateTime(tz) | nullable | `now()` |
| `updated_at` | DateTime(tz) | nullable | `now()` |

Unique constraint: `(user_id, metric_date)` — one row per user per day.

---

## Endpoints

All routes use session auth (`resolve_user` dependency) unless noted. All
dates are ISO `YYYY-MM-DD`. Range params use aliases `from` / `to`.

### `/api/habits`

#### `GET /api/habits`
- Auth: session
- Query params: none
- Response: `[{id, name, display_order, created_at}]` — active (non-archived) habits only, ordered by `display_order`, then `created_at`

#### `POST /api/habits`
- Auth: session
- Body: `{name: string}`
- Response 201: `{id, name, display_order, created_at}`
- Errors: 422 if name blank

#### `PATCH /api/habits/{habit_id}`
- Auth: session
- Body: `{name?: string}`
- Response: `{id, name, display_order}`
- Errors: 400 invalid UUID, 403 wrong user, 404 not found

#### `DELETE /api/habits/{habit_id}`
- Auth: session
- Soft-deletes: sets `archived_at = now()`
- Response: 204 No Content
- Errors: 400 invalid UUID, 403 wrong user, 404 not found

#### `GET /api/habits/logs`
- Auth: session
- Query params: `from` (YYYY-MM-DD, required), `to` (YYYY-MM-DD, required)
- Response: `[{id, habit_id, user_id, logged_date}]`
- Errors: 400 invalid date

#### `POST /api/habits/logs`
- Auth: session
- Body: `{habit_id: string, logged_date: string}`
- Response 201: `{id, habit_id, user_id, logged_date}`
- Errors: 400 invalid UUID, 404 habit not found, 409 already logged

#### `DELETE /api/habits/logs/{log_id}`
- Auth: session
- Response: 204 No Content
- Errors: 400 invalid UUID, 403 wrong user, 404 not found

#### `GET /api/habits/stats`
- Auth: session
- Query params: `habit_id?` (UUID string), `days` (int 1–365, default 30)
- Response (single habit): `{streak, completion_rate, days_completed, days_total}`
- Response (all habits, when `habit_id` omitted): `[{habit_id, habit_name, streak, completion_rate, days_completed, days_total}]`
- **No weekly aggregation** — stats are daily-resolution; `completion_rate` = days_completed / days over a rolling window

### `/api/workouts`

#### `GET /api/workouts`
- Auth: session
- Query params: `from` (YYYY-MM-DD, required), `to` (YYYY-MM-DD, required)
- Response: `[workout_list_dict]` where each item includes: `id, workout_date, name, workout_type, remarks, tss, tss_source, strava_activity_url, distance_km, duration_seconds, avg_hr, max_hr, elevation_m, exercise_count, created_at, best_*`

#### `GET /api/workouts/{workout_id}`
- Auth: session
- Response: `workout_dict` — full workout with `exercises[]` array
- Errors: 400 invalid UUID, 403 wrong user, 404 not found

#### `POST /api/workouts`
- Auth: session
- Body: `{name, workout_date, workout_type, remarks?, tss?, distance_km?, duration_seconds?, avg_hr?, max_hr?, elevation_m?, source?, strava_activity_url?, exercises?: [{name, sets?, reps?, weight_kg?, duration?, rpe?, distance_km?, duration_seconds?, avg_hr?}]}`
- Response 201: full `workout_dict`
- Errors: 422 invalid fields, date in future, out-of-range HR

#### `PATCH /api/workouts/{workout_id}`
- Auth: session
- Body: same fields as POST (all optional, only provided fields updated)
- Response: updated `workout_dict`

#### `DELETE /api/workouts/{workout_id}`
- Auth: session
- Response: 204 No Content

#### `POST /api/workouts/{workout_id}/exercises/reorder`
- Auth: session
- Body: `{ordered_ids: [uuid_string, ...]}`
- Response 200: updated `workout_dict`

#### `POST /api/workouts/{workout_id}/exercises`
- Auth: session
- Body: `{name, sets?, reps?, weight_kg?, duration?, rpe?, distance_km?, duration_seconds?, avg_hr?}`
- Response 201: `exercise_dict`

#### `PATCH /api/workouts/{workout_id}/exercises/{exercise_id}`
- Auth: session
- Body: same fields as POST exercises (all optional)
- Response: updated `exercise_dict`

#### `DELETE /api/workouts/{workout_id}/exercises/{exercise_id}`
- Auth: session
- Response: 204 No Content

#### `GET /api/workouts/{workout_id}/splits`
- Auth: session
- Response: `[{id, split_index, distance_km, duration_seconds, avg_hr}]`

#### `POST /api/workouts/{workout_id}/splits`
- Auth: session
- Body: `{splits: [{split_index, distance_km, duration_seconds, avg_hr?}]}`
- Response 201: list of created splits

#### `DELETE /api/workouts/{workout_id}/splits`
- Auth: session
- Deletes all splits for the workout
- Response: 204 No Content

### `/api/daily-metrics`

#### `GET /api/daily-metrics`
- Auth: session
- Query params: `from?` (default: 30 days ago), `to?` (default: today)
- Response: `[daily_metric_dict]` ordered by `metric_date` desc
- daily_metric_dict shape: `{id, user_id, metric_date, resting_hr, hrv, sleep_hours, sleep_quality, energy, mood, notes, created_at, updated_at}`

#### `GET /api/daily-metrics/{uid}/{metric_date}`
- Auth: session (uid must match session user)
- Response: `daily_metric_dict`
- Errors: 400 invalid UUID or date, 403 wrong user, 404 not found

#### `POST /api/daily-metrics`
- Auth: session
- Body: `{metric_date, resting_hr?, hrv?, sleep_hours?, sleep_quality?, energy?, mood?, notes?}`
- Response 201: `daily_metric_dict`
- Errors: 422 invalid date/fields, 409 already exists (use PATCH)

#### `PATCH /api/daily-metrics/{uid}/{metric_date}`
- Auth: session
- Body: partial `{resting_hr?, hrv?, sleep_hours?, sleep_quality?, energy?, mood?, notes?}`
- Response: updated `daily_metric_dict`
- Errors: 400, 403, 404, 422

#### `PUT /api/daily-metrics/{uid}/{metric_date}`
- Auth: session
- Body: same as PATCH (full replacement)
- Upserts: creates if not exists, replaces if exists
- Response: `daily_metric_dict`

#### `GET /api/daily-metrics/trend`
- Auth: session
- Query params: `days` (int 1–90, default 7)
- Response: `[{date, sleep_hours, energy, mood}]` — one entry per day in window, nulls for missing days

#### `DELETE /api/daily-metrics/{uid}/{metric_date}`
- Auth: session
- Response: 204 No Content

### `/api/home`

#### `GET /api/home/weight-summary`
- Auth: session
- Query params: none
- Response: `{current_weight, avg_7d, delta_week, delta_month, target: {direction, target_weight_kg, target_date, progress_pct, status_label}|null, ma30: [{date, value}]}`

#### `GET /api/home/recent-workouts`
- Auth: query param `user_id` (UUID string, required)
- Query params: `user_id`, `limit` (1–10, default 5)
- Response: `{workouts: [{id, workout_date, workout_type, name, distance_km?, duration_seconds?, avg_hr?, tss?, source?, is_stryd_synced, relative_date}], count, has_more}`
- Note: uses legacy `user_id` query param (not session auth)

#### `GET /api/home/personal-records`
- Auth: query param `user_id` (UUID string)
- Query params: `user_id`, `tracks?` (comma-separated keys, default `half_marathon,10k,squat_1rm`)
- Response: `{tracks: [{track_key, track_name, track_type, current_value, current_value_formatted, achieved_on, predicted_value, predicted_value_formatted, predicted_method, trend}]}`

#### `GET /api/home/readiness`
- Auth: query param `user_id?`
- Query params: `user_id?`, `date?` (YYYY-MM-DD, default today)
- Response: `{date, score: int|null, score_label, contributors: [{factor, value, weight, impact}], rolling_baseline: {hrv_7d_avg, rhr_7d_avg, sleep_7d_avg_hours}}`
- Score formula: sleep_hours 30%, HRV 25%, RHR 20%, mood 15%, energy 10%

#### `GET /api/home/weekly-summary`
- Auth: query param `user_id?`
- Query params: `user_id?`, `week_start?` (YYYY-MM-DD, default current Mon in Asia/Bangkok)
- Response: weekly workout totals bucketed by type (`run`, `lift`, `wod`, `bike`), TSS, distances; current week vs previous week comparison

---

## Frontend Pages

### `home.html` — `/home` route

- **Script:** `frontend/js/home.js`
- **Layout:** greeting bar (h1 + date), then JS-rendered rows injected into `#row-1` through `#row-5` and `#row-log`. Entirely JS-driven layout (no static section markup).
- **Widget rows:**
  - Row 1–2: readiness card, performance card, recent-workouts card, weekly-summary card
  - Row 3: trend-card-weight (weight widget with sparkline)
  - Row log: log-today card (daily metrics quick entry)
  - Rows 4–5: habits card (week grid), habits stats card
  - Separate: sleep card

- **API calls:**
  - `GET /api/auth/me`
  - `GET /api/home/readiness?user_id=…`
  - `GET /api/home/weight-summary`
  - `GET /api/home/weekly-summary?user_id=…`
  - `GET /api/home/recent-workouts?user_id=…&limit=4`
  - `GET /api/daily-metrics/{uid}/{date}` (log-today card)
  - `PUT /api/daily-metrics/{uid}/{date}` (log-today save)
  - `GET /api/habits`
  - `GET /api/habits/logs?from=…&to=…`
  - `GET /api/habits/stats?days=30`
  - `POST/DELETE /api/habits/logs` (toggle)
  - `GET /api/workouts/{id}` (workout detail flyout)
  - `GET /api/workouts?from=…&to=…`
  - `GET /api/personal-records`
  - `GET /api/strava/status`, `POST /api/strava/sync`
  - `GET /api/sync/strava/latest`
  - `GET /api/user-preferences`

### `weight.html` — `/weight` route

- **Script:** `frontend/js/weight.js`
- **Layout:** four card sections — chart card (line chart, range selector), progress card (shown when active target exists), milestones panel (shown when target exists), recent entries table (last 14 days).
- **API calls:**
  - `GET /api/weight-chart?user_id=…&from=…&to=…&include_target=true`
  - `GET /api/weight-entries?user_id=…&from=…&to=…`
  - `GET /api/weight-targets/active?user_id=…`
  - `POST /api/weight-entries` (add entry)
  - `PATCH /api/weight-entries` (inline edit)
  - `DELETE /api/weight-entries/{id}`
  - `GET /api/exports/weight-entries?user_id=…`
  - `GET /api/auth/me`

### `habits.html` — `/habits` route

- **Script:** `frontend/js/habits.js`
- **Layout:** toolbar (today's date) + scrollable habit list with toggle checkboxes + add-habit button; modal overlay for create/edit/delete.
- **API calls:**
  - `GET /api/habits` (list)
  - `GET /api/habits/logs?from={today}&to={today}` (today's completions)
  - `GET /api/habits/stats?habit_id=…&days=30` (streak for each)
  - `POST /api/habits/logs` (toggle on)
  - `DELETE /api/habits/logs/{id}` (toggle off)
  - `DELETE /api/habits/{id}` (archive)
  - `POST /api/habits` (create)

### `calendar.html` — `/calendar` route

- **Script:** `frontend/js/calendar.js`
- **Layout:** month grid (Mon–Sun columns), navigation arrows, filter chips; clicking a day opens a modal with weight, workouts, habits, readiness, and daily metrics for that day.
- **API calls:**
  - `GET /api/calendar/month?year=…&month=…`
  - `GET /api/habits`
  - `GET /api/habits/logs?from=…&to=…`
  - `GET /api/workouts?from=…&to=…`
  - `GET /api/weight`
  - `GET /api/readiness?from=…&to=…`
  - `GET /api/daily-metrics/{uid}/{date}` (day modal)
  - `PUT /api/daily-metrics/{uid}/{date}` (day modal save)
  - `POST /api/habits/logs`, `DELETE /api/habits/logs/{id}` (day modal toggle)
  - `POST /api/weight` (day modal weight entry)

### `training-log.html` — `/log` route

- **Script:** `frontend/js/training-log.js`
- **Layout:** page header + date range controls + week-card list (grouped by week, each workout as an entry-row); detail panel slides in on workout click; Strava sync status bar at top.
- **API calls:**
  - `GET /api/training-log?from=…&to=…&include_rest=false`
  - `GET /api/workouts/{id}` (detail panel)
  - `GET /api/workouts/{id}/splits` (detail panel splits tab)
  - `DELETE /api/workouts/{id}` (delete from detail panel)
  - `POST /api/strava/sync`
  - `GET /api/sync/status`

---

## Migration Helpers

**`alembic/helpers.py` exists.**

Four idempotency helper functions, each accepting a SQLAlchemy `op.get_bind()` inspector:

| Function | Signature | Returns | Idempotency guarantee |
|---|---|---|---|
| `table_exists` | `(name: str) -> bool` | True if table exists in DB | Safe to call before `create_table` — returns False if absent |
| `column_exists` | `(table: str, column: str) -> bool` | True if column exists on table | Returns False if table or column absent |
| `index_exists` | `(table: str, name: str) -> bool` | True if named index exists on table | Returns False if table or index absent |
| `fk_exists` | `(table: str, name: str) -> bool` | True if named FK constraint exists on table | Returns False if table or FK absent |

All four functions use `sqlalchemy.inspect(bind)` and return `False` (not raise)
when the table does not exist. Standard migration pattern:

```python
from alembic.helpers import column_exists
if not column_exists("workouts", "zone2_minutes"):
    op.add_column("workouts", sa.Column("zone2_minutes", sa.Integer(), nullable=True))
```
