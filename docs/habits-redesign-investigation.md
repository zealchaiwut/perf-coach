# Habits Redesign Investigation

_Issue #429 — pre-implementation investigation_

## Relevant File Paths

| Layer | Path | Purpose |
|---|---|---|
| Frontend HTML | `frontend/pages/habits.html` | Habits page shell |
| Frontend JS | `frontend/js/habits.js` | All habits UI logic (~854 lines) |
| Backend routes | `backend/main.py` (lines 2251–2840) | All habits API endpoints |
| Habit autofill service | `backend/services/habit_autofill.py` | Bulk recompute autofill logs |
| Models | `backend/models.py` (lines 82–123) | `Habit` and `HabitLog` ORM models |

---

## Existing Endpoint Shapes

### `GET /api/habits`

Query params: `include_archived` (bool, default false)  
Auth: session cookie (`resolve_user`)

```json
[
  {
    "id": "uuid",
    "user_id": "uuid",
    "name": "string",
    "description": "string|null",
    "tracking_type": "daily_checkmark|weekly_count|weekly_minutes|weekly_quantity",
    "weekly_target": 7.0,
    "unit": "string|null",
    "auto_fill_source": "workout.zone2_minutes|...|null",
    "icon": "string|null",
    "color": "string|null",
    "sort_order": 0,
    "is_archived": false,
    "created_at": "ISO datetime",
    "updated_at": "ISO datetime|null"
  }
]
```

### `POST /api/habits/{id}/log` → 201

Body: `{ "log_date": "YYYY-MM-DD" (optional), "value": float (optional), "notes": string (optional) }`  
Defaults: `log_date` = Bangkok today, `value` = 1.0  
Behaviour: upserts (updates if same `habit_id` + `log_date` already exists).

Response shape matches `_habit_log_dict`:
```json
{
  "id": "uuid",
  "habit_id": "uuid",
  "user_id": "uuid",
  "log_date": "YYYY-MM-DD",
  "log_week_start": "YYYY-MM-DD",
  "value": 1.0,
  "notes": null,
  "source": "manual",
  "created_at": "ISO datetime",
  "updated_at": null
}
```

### `GET /api/habits/{id}/progress`

Query params: `week_start` (YYYY-MM-DD, optional — defaults to current Monday in Bangkok TZ)

```json
{
  "habit": { /* full habit dict */ },
  "week_start": "2026-06-08",
  "week_end": "2026-06-14",
  "target": 120.0,
  "current_value": 45.0,
  "percentage": 37.5,
  "manual_logs": [
    { "date": "YYYY-MM-DD", "value": 30.0, "notes": "" }
  ],
  "computed_logs": [
    { "date": "YYYY-MM-DD", "value": 15.0, "source": "workout.zone2_minutes" }
  ],
  "is_complete": false
}
```

---

## Model Fields for Habit & HabitLog

### `Habit` (table: `habits`)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | `gen_random_uuid()` |
| `user_id` | UUID FK → users | Required |
| `name` | String(200) | Required |
| `tracking_type` | String(50) | `daily_checkmark`, `weekly_count`, `weekly_minutes`, `weekly_quantity` |
| `weekly_target` | Numeric(10,2) | Nullable. For `daily_checkmark`: 1–7. For `weekly_*`: > 0. Defaults to 7 in UI. |
| `unit` | String(50) | Nullable (e.g. "min", "sessions") |
| `auto_fill_source` | String(100) | Nullable. One of: `workout.zone2_minutes`, `workout.run_count`, `workout.lift_count`, `workout.total_duration_minutes`, `workout.distance_km` |
| `icon` | String(100) | Nullable |
| `color` | String(20) | Nullable |
| `sort_order` | Integer | Default 0 |
| `is_archived` | Boolean | Default false |

### `HabitLog` (table: `habit_logs`)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `habit_id` | UUID FK → habits CASCADE | |
| `user_id` | UUID FK → users CASCADE | |
| `log_date` | Date | The calendar date of the log |
| `log_week_start` | Date | Monday of the week containing `log_date` (Bangkok TZ) |
| `value` | Numeric(10,4) | Default 1. For `daily_checkmark` = 1 per checked day. For weekly types = contributed amount. |
| `source` | String(50) | `manual`, `manual_override`, `workout_autofill` |

Unique constraint: `(habit_id, log_date)` — one entry per habit per day.  
Index: `(habit_id, log_week_start)` — used by progress queries.

---

## How the Progress Endpoint Computes Weekly Values

Source: `get_habit_progress` in `backend/main.py` (refactored to use `_aggregate_weekly_progress` in issue #429).

### Step 1 — Determine week range
- `week_start` param parsed; defaults to `_week_start_bangkok(_bangkok_today())`
- `week_end = week_start + 6 days`

### Step 2 — Load manual logs
Query `HabitLog` filtered by `habit_id` and `log_week_start == ws`.

### Step 3 — Compute autofill logs (if `auto_fill_source` set)
`_get_computed_logs(session, user_id, ws, we, auto_fill_source)` queries `Workout` with source-specific filters:
- `workout.zone2_minutes` → sum `zone2_minutes` per date (only workouts with `zone2_minutes > 0`)
- `workout.run_count` → count runs per date (filter by `workout_type ilike '%run%'`, value 1 per row)
- `workout.lift_count` → count lifts per date (filter by `workout_type ilike '%lift%'`, value 1 per row)
- `workout.total_duration_minutes` → sum `duration_seconds / 60` per date
- `workout.distance_km` → sum `distance_km` per date

### Step 4 — Aggregate `current_value` with `manual_override` precedence
For each date that appears in either manual or computed logs:

```
if manual log on date has source == 'manual_override':
    effective_value += manual_value   (computed value is ignored for this date)
else:
    effective_value += manual_value + computed_value
```

This is implemented in `_aggregate_weekly_progress` (shared helper added in issue #429).

### Step 5 — Derive target, percentage, is_complete
- `target = habit.weekly_target` (null if unset)
- `percentage = min(100, current_value / target * 100)` — null if no target
- `is_complete = current_value >= target`

---

## What the Current Habits Page Renders

The page is split into several cards, all fed by a `loadData()` fan-out in `frontend/js/habits.js`:

```
loadData()
  ├── GET /api/habits                     → activeHabits
  ├── GET /api/habits?include_archived=true → archivedHabits
  ├── GET /api/habits/logs?from=…&to=…   → daily log entries
  ├── GET /api/habits/stats?days=30       → streak / stats data
  └── N × GET /api/habits/{id}/progress  → weekly progress per habit (waterfall)
```

### Rendered Components

| Component | Data dependency |
|---|---|
| **Hero row** — habit count subtitle | `activeHabits.length` |
| **Day-grid card** — 7-column grid showing per-habit per-day checkmarks | `activeHabits`, daily logs from `/api/habits/logs` |
| **Weekly habits card** — progress rings / bars per weekly-type habit | Per-habit `/progress` responses (`progressMap`) |
| **Habit management section** — edit/archive/reorder panel | `activeHabits`, `archivedHabits` |
| **Starter state** — onboarding when no habits exist | None |
| **Wheel / day scores** — `renderHeroRow` computes done/total per day | Derived from logs + `activeHabits` in JS |

### Performance Problem Being Solved

The N separate `progress` calls are sequential per habit (JavaScript `Promise.all` makes them concurrent, but still N round-trips). On a user with 8 habits, this is 8 additional HTTP requests after the initial 4 parallel calls. The `/api/habits/week` endpoint collapses this into a single call, returning `daily_habits`, `weekly_habits`, `day_scores`, `wheel`, and `week_totals` in one response.

---

## Post-ship verification

_Sprint 54, issue #435 — manual smoke suite executed on UAT, 2026-06-11_

| # | Flow | Result | Notes |
|---|---|---|---|
| 1 | **Fresh user — starter suggestions** | PASS | Created net-new account; wheel and grid render without errors; starter habit suggestions shown; no JS console exceptions |
| 2 | **Check today's habit via the grid** | PASS | Tapped today's cell on a daily habit; wheel arc updated percentage; streak and day-score row updated; stats tile refreshed |
| 3 | **Backfill Monday** | PASS | Clicked Monday's cell on a daily habit mid-week; cell marked done; wheel and totals recalculated; state persisted after navigating away and back |
| 4 | **Log a workout with `zone2_minutes` → Zone 2 bar moves** | PASS | Logged a run with zone2_minutes > 0 via the training log; Strava/zone2 auto-sync reflected in Zone 2 weekly habit bar after sync; wheel updated on next load |
| 5 | **Manually log 15 min on a weekly habit → accumulates** | PASS | Opened `+ log` chip on a manual weekly_minutes habit; added 15 min twice in same week; total showed 30 min accumulated; percentage updated correctly; no reset between logs |
| 6 | **Navigate to last week → read-only** | PASS | Used week navigator `‹` to go to previous week; grid showed past data; all day cells were non-interactive; no write calls fired on click attempts; no error toast |

Tester: zealchaiwut · Environment: UAT (develop branch)
