# API Reference

> Verified against `backend/main.py` at commit `7606234300db8aaa2481adda19437d23dfe801ee`.

---

## Quick Reference

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Service health status |
| GET | `/api/env` | Current environment (short) |
| GET | `/api/environment` | Current environment (alias) |
| GET | `/api/users` | List all users |
| POST | `/api/users` | Create a user |
| PATCH | `/api/users/{user_id}` | Rename a user |
| DELETE | `/api/users/{user_id}` | Delete a user and all their data |
| GET | `/api/weight` | List weight entries for a user |
| POST | `/api/weight` | Add a weight entry |
| DELETE | `/api/weight/{entry_id}` | Delete a weight entry |
| GET | `/api/habits` | List active habits for a user |
| POST | `/api/habits` | Create a habit |
| PATCH | `/api/habits/{habit_id}` | Update a habit |
| DELETE | `/api/habits/{habit_id}` | Archive a habit (soft delete) |
| GET | `/api/habits/logs` | Get habit logs for a date range |
| POST | `/api/habits/logs` | Log a habit completion |
| DELETE | `/api/habits/logs/{log_id}` | Delete a habit log entry |
| GET | `/api/habits/stats` | Get habit statistics |
| GET | `/api/stats/active-streak` | Get cross-resource active streak |
| GET | `/api/calendar/month` | Get per-day summary for a calendar month |
| GET | `/api/workouts` | List workouts for a date range |
| GET | `/api/workouts/{workout_id}` | Get a single workout with exercises |
| POST | `/api/workouts` | Create a workout |
| PATCH | `/api/workouts/{workout_id}` | Update workout fields |
| DELETE | `/api/workouts/{workout_id}` | Delete a workout |
| POST | `/api/workouts/{workout_id}/exercises/reorder` | Reorder exercises in a workout |
| POST | `/api/workouts/{workout_id}/exercises` | Append an exercise to a workout |
| PATCH | `/api/workouts/{workout_id}/exercises/{exercise_id}` | Update an exercise |
| DELETE | `/api/workouts/{workout_id}/exercises/{exercise_id}` | Delete an exercise |
| GET | `/api/workouts/{workout_id}/splits` | Get splits for a workout |
| POST | `/api/workouts/{workout_id}/splits` | Replace all splits for a workout |
| DELETE | `/api/workouts/{workout_id}/splits` | Delete all splits for a workout |
| GET | `/api/daily-metrics` | List daily metrics for a date range |
| GET | `/api/daily-metrics/{user_id}/{metric_date}` | Get a single daily metric |
| POST | `/api/daily-metrics` | Create a daily metric |
| PATCH | `/api/daily-metrics/{user_id}/{metric_date}` | Update daily metric fields |
| PUT | `/api/daily-metrics/{user_id}/{metric_date}` | Upsert a daily metric |
| GET | `/api/daily-metrics/trend` | Get trend values for the last N days |
| DELETE | `/api/daily-metrics/{user_id}/{metric_date}` | Delete a daily metric |
| GET | `/trends/summary` | Get trends summary with series and deltas |
| POST | `/api/readiness/compute` | Compute and store a readiness score |
| GET | `/api/readiness/today` | Get today's readiness record |
| GET | `/api/readiness` | Get readiness scores for a date range |
| GET | `/api/training-log` | Get training log grouped by week |
| GET | `/api/personal-records` | List personal records for a user |
| POST | `/api/personal-records` | Create a personal record |
| PATCH | `/api/personal-records/{record_id}` | Update a personal record |
| DELETE | `/api/personal-records/{record_id}` | Delete a personal record |
| GET | `/api/strava/connect` | Initiate Strava OAuth flow |
| GET | `/api/strava/callback` | Strava OAuth redirect callback |
| GET | `/api/strava/status` | Get Strava connection status |
| DELETE | `/api/strava/disconnect` | Disconnect Strava |
| POST | `/api/stryd/connect` | Connect Stryd with email/password |
| GET | `/api/stryd/status` | Get Stryd connection status |
| DELETE | `/api/stryd/disconnect` | Disconnect Stryd |
| POST | `/api/sync/strava` | Trigger Strava sync job; 202 with job_id; 409 if already running |
| GET | `/api/sync/strava/status` | Poll SyncJob by job_id |
| GET | `/api/sync/strava/latest` | Most recent Strava sync info |
| GET | `/api/sync/strava/dry-run` | Read-only reconcile preview |
| GET | `/api/sync/strava/data-quality` | Data quality counts for Strava/workout sync state |
| POST | `/api/sync/strava/reconcile` | Reconcile strava_activities → workouts |
| GET | `/api/sync/history` | Paginated SyncJob history for session user |

---

## Health / System

### GET `/api/health`

Return service health status including DB connectivity, environment, and uptime.

**Query parameters:** none

**Response (200):**
```json
{
  "status": "ok",
  "environment": "uat",
  "version": "7606234300db8aaa2481adda19437d23dfe801ee",
  "db": "ok",
  "uptime_seconds": 142
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | `"ok" \| "degraded"` | Service health |
| `environment` | `"uat" \| "prd" \| "local"` | Active environment |
| `version` | string | Git SHA injected at deploy via `GIT_SHA` env var, `"unknown"` if not set |
| `db` | `"ok" \| "error: <msg>"` | Database reachability |
| `uptime_seconds` | integer | Seconds since process start |

**Status codes:** 200

---

### GET `/api/env`

Return the current environment name.

**Query parameters:** none

**Response (200):**
```json
{"environment": "uat"}
```

**Status codes:** 200

---

### GET `/api/environment`

Alias for `/api/env`.

**Query parameters:** none

**Response (200):**
```json
{"environment": "uat"}
```

**Status codes:** 200

---

## Users

### GET `/api/users`

List all users with summary counts of weight entries, active habits, and integration status.

**Query parameters:** none

**Response (200):**
```json
[
  {
    "id": "b1f3e2d4-0000-0000-0000-000000000001",
    "name": "Alice",
    "created_at": "2024-01-15T10:00:00+00:00",
    "weight_count": 30,
    "habits_count": 4,
    "strava_connected": true,
    "stryd_connected": false
  }
]
```

**Status codes:**
- 200 — success
- 503 — database unavailable

---

### POST `/api/users`

Create a new user.

**Request body:**
```json
{"name": "Alice"}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `name` | string | yes | 1–100 characters |

**Response (201):**
```json
{
  "id": "b1f3e2d4-0000-0000-0000-000000000001",
  "name": "Alice",
  "created_at": "2024-01-15T10:00:00+00:00"
}
```

**Status codes:**
- 201 — created
- 400 — name length invalid
- 409 — name already exists

---

### PATCH `/api/users/{user_id}`

Rename a user.

**Path parameters:**
- `user_id` — UUID string

**Request body:**
```json
{"name": "Alicia"}
```

**Response (200):**
```json
{
  "id": "b1f3e2d4-0000-0000-0000-000000000001",
  "name": "Alicia",
  "created_at": "2024-01-15T10:00:00+00:00"
}
```

**Status codes:**
- 200 — success
- 400 — invalid `user_id` or name length
- 404 — user not found
- 409 — name already taken

---

### DELETE `/api/users/{user_id}`

Delete a user and cascade-delete all their habits, habit logs, and weight entries. Refuses if only one user remains.

**Path parameters:**
- `user_id` — UUID string

**Response:** 204 No Content

**Status codes:**
- 204 — deleted
- 400 — invalid `user_id`
- 404 — user not found
- 409 — cannot delete the last user

---

## Weight

### GET `/api/weight`

List all weight entries for a user, ordered by date ascending.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |

**Response (200):**
```json
[
  {
    "id": "a1b2c3d4-0000-0000-0000-000000000001",
    "weight_kg": 72.5,
    "recorded_date": "2024-06-01",
    "created_at": "2024-06-01T08:00:00+00:00"
  }
]
```

**Status codes:**
- 200 — success
- 400 — invalid `user_id`

---

### POST `/api/weight`

Add a weight entry for a user.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |

**Request body:**
```json
{"weight_kg": 72.5, "recorded_date": "2024-06-01"}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `weight_kg` | float | yes | Body weight in kg |
| `recorded_date` | string | yes | ISO date `YYYY-MM-DD` |

**Response (201):**
```json
{
  "id": "a1b2c3d4-0000-0000-0000-000000000001",
  "weight_kg": 72.5,
  "recorded_date": "2024-06-01",
  "created_at": "2024-06-01T08:00:00+00:00"
}
```

**Status codes:**
- 201 — created
- 400 — invalid `user_id`
- 409 — entry already exists for this date

---

### DELETE `/api/weight/{entry_id}`

Delete a weight entry.

**Path parameters:**
- `entry_id` — UUID string

**Response:** 204 No Content

**Status codes:**
- 204 — deleted
- 400 — invalid `entry_id`
- 404 — entry not found

---

## Habits

### GET `/api/habits`

List active (non-archived) habits for a user, ordered by `display_order` then `created_at`.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |

**Response (200):**
```json
[
  {
    "id": "c1d2e3f4-0000-0000-0000-000000000001",
    "name": "Morning run",
    "display_order": 0,
    "created_at": "2024-01-01T00:00:00+00:00"
  }
]
```

**Status codes:**
- 200 — success
- 400 — invalid `user_id`

---

### POST `/api/habits`

Create a new habit.

**Request body:**
```json
{"user_id": "b1f3e2d4-0000-0000-0000-000000000001", "name": "Morning run"}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | UUID string | yes | Owner user |
| `name` | string | yes | Habit name |

**Response (201):**
```json
{
  "id": "c1d2e3f4-0000-0000-0000-000000000001",
  "name": "Morning run",
  "display_order": 0,
  "created_at": "2024-01-01T00:00:00+00:00"
}
```

**Status codes:**
- 201 — created
- 400 — invalid `user_id`

---

### PATCH `/api/habits/{habit_id}`

Update a habit's name.

> ⚠ schema needs verification: `HabitPatch` declares an `archived` boolean field but the handler does not apply it; only `name` is updated.

**Path parameters:**
- `habit_id` — UUID string

**Request body:**
```json
{"name": "Evening run"}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | no | New habit name |

**Response (200):**
```json
{
  "id": "c1d2e3f4-0000-0000-0000-000000000001",
  "name": "Evening run",
  "display_order": 0
}
```

**Status codes:**
- 200 — success
- 400 — invalid `habit_id`
- 404 — habit not found

---

### DELETE `/api/habits/{habit_id}`

Archive a habit (soft delete — sets `archived_at`; habit disappears from `GET /api/habits` but logs are preserved).

**Path parameters:**
- `habit_id` — UUID string

**Response:** 204 No Content

**Status codes:**
- 204 — archived
- 400 — invalid `habit_id`
- 404 — habit not found

---

### GET `/api/habits/logs`

Get habit completion logs for a date range.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |
| `from` | string | yes | Start date `YYYY-MM-DD` (inclusive) |
| `to` | string | yes | End date `YYYY-MM-DD` (inclusive) |

**Response (200):**
```json
[
  {
    "id": "d1e2f3a4-0000-0000-0000-000000000001",
    "habit_id": "c1d2e3f4-0000-0000-0000-000000000001",
    "user_id": "b1f3e2d4-0000-0000-0000-000000000001",
    "logged_date": "2024-06-01"
  }
]
```

**Status codes:**
- 200 — success
- 400 — invalid `user_id` or date format

---

### POST `/api/habits/logs`

Log a habit completion for a specific date.

**Request body:**
```json
{
  "habit_id": "c1d2e3f4-0000-0000-0000-000000000001",
  "user_id": "b1f3e2d4-0000-0000-0000-000000000001",
  "logged_date": "2024-06-01"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `habit_id` | UUID string | yes | Habit being logged |
| `user_id` | UUID string | yes | User logging the habit |
| `logged_date` | string | yes | Date `YYYY-MM-DD` |

**Response (201):**
```json
{
  "id": "d1e2f3a4-0000-0000-0000-000000000001",
  "habit_id": "c1d2e3f4-0000-0000-0000-000000000001",
  "user_id": "b1f3e2d4-0000-0000-0000-000000000001",
  "logged_date": "2024-06-01"
}
```

**Status codes:**
- 201 — created
- 400 — invalid UUIDs
- 409 — log already exists for this habit on this date

---

### DELETE `/api/habits/logs/{log_id}`

Delete a habit log entry.

**Path parameters:**
- `log_id` — UUID string

**Response:** 204 No Content

**Status codes:**
- 204 — deleted
- 400 — invalid `log_id`
- 404 — log not found

---

### GET `/api/habits/stats`

Get habit statistics. Returns stats for all active habits when `habit_id` is omitted, or a single-habit summary when provided.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |
| `habit_id` | UUID string | no | If provided, return single-habit stats |
| `days` | integer | no | Window size in days (default 30, range 1–365) |

**Response (200) — single habit (`habit_id` provided):**
```json
{
  "streak": 5,
  "completion_rate": 0.8,
  "days_completed": 24,
  "days_total": 30
}
```

**Response (200) — all habits (`habit_id` omitted):**
```json
[
  {
    "habit_id": "c1d2e3f4-0000-0000-0000-000000000001",
    "habit_name": "Morning run",
    "streak": 5,
    "completion_rate": 0.8,
    "days_completed": 24,
    "days_total": 30
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `streak` | integer | Current consecutive-day streak |
| `completion_rate` | float | Fraction of days in window with a log (0–1, 4 decimal places) |
| `days_completed` | integer | Count of logged days in window |
| `days_total` | integer | Window size |

**Status codes:**
- 200 — success
- 400 — invalid `user_id` or `habit_id`

---

## Stats

### GET `/api/stats/active-streak`

Return the current and longest consecutive-day streaks across weight entries, habit logs, and workouts combined.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |

**Response (200):**
```json
{
  "current_streak": 12,
  "longest_streak": 45,
  "last_active_date": "2024-06-01"
}
```

**Status codes:**
- 200 — success
- 400 — invalid `user_id`

---

## Calendar

### GET `/api/calendar/month`

Return per-day summary data for every day in a given calendar month.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |
| `year` | integer | yes | Four-digit year |
| `month` | integer | yes | Month number 1–12 |

**Response (200):** Array of objects, one per calendar day:
```json
[
  {
    "date": "2024-06-01",
    "weight": 72.5,
    "habits_done": 3,
    "workouts": 1,
    "energy": 4,
    "sleep_quality": 3
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | `YYYY-MM-DD` |
| `weight` | float \| null | Weight entry for this day if any |
| `habits_done` | integer | Number of habit logs on this day |
| `workouts` | integer | Number of workouts on this day |
| `energy` | integer \| null | Energy score 1–5 from daily metrics |
| `sleep_quality` | integer \| null | Sleep quality 1–5 from daily metrics |

**Status codes:**
- 200 — success
- 400 — invalid `user_id` or `month` out of range 1–12

---

## Workouts

### Workout object (list form)

Returned by `GET /api/workouts`. Does not embed exercises.

```json
{
  "id": "e1f2a3b4-0000-0000-0000-000000000001",
  "workout_date": "2024-06-01",
  "name": "Morning run",
  "workout_type": "run",
  "remarks": "Easy pace",
  "tss": 55.0,
  "tss_source": "manual",
  "strava_activity_url": "https://www.strava.com/activities/123456",
  "distance_km": 10.0,
  "duration_seconds": 3600,
  "avg_hr": 145,
  "max_hr": 165,
  "elevation_m": 80,
  "exercise_count": 0,
  "created_at": "2024-06-01T08:00:00+00:00",
  "best_distance_km": 10.0,
  "best_duration_seconds": 3600,
  "best_avg_hr": 145,
  "best_avg_power_w": null,
  "best_tss": 55.0,
  "best_name": "manual"
}
```

### Workout object (detail form)

Returned by `GET /api/workouts/{workout_id}`, `POST /api/workouts`, `PATCH /api/workouts/{workout_id}`. Includes `exercises` array and adds `user_id`, `strava_activity_pk`, `stryd_activity_pk`, `source` fields.

```json
{
  "id": "e1f2a3b4-0000-0000-0000-000000000001",
  "user_id": "b1f3e2d4-0000-0000-0000-000000000001",
  "name": "Morning run",
  "workout_date": "2024-06-01",
  "workout_type": "run",
  "remarks": "Easy pace",
  "tss": 55.0,
  "tss_source": "manual",
  "source": "strava",
  "strava_activity_pk": null,
  "stryd_activity_pk": null,
  "strava_activity_url": "https://www.strava.com/activities/123456",
  "distance_km": 10.0,
  "duration_seconds": 3600,
  "avg_hr": 145,
  "max_hr": 165,
  "elevation_m": 80,
  "created_at": "2024-06-01T08:00:00+00:00",
  "exercises": [],
  "best_distance_km": 10.0,
  "best_duration_seconds": 3600,
  "best_avg_hr": 145,
  "best_avg_power_w": null,
  "best_tss": 55.0,
  "best_name": "manual"
}
```

### Exercise object

```json
{
  "id": "f1a2b3c4-0000-0000-0000-000000000001",
  "display_order": 0,
  "name": "Squat",
  "sets": 3,
  "reps": 10,
  "weight_kg": 80.0,
  "duration": "00:30",
  "rpe": 7,
  "distance_km": null,
  "duration_seconds": null,
  "avg_hr": null,
  "created_at": "2024-06-01T08:00:00+00:00"
}
```

---

### GET `/api/workouts`

List workouts for a user within a date range, ordered by date descending. Does not embed exercises.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |
| `from` | string | yes | Start date `YYYY-MM-DD` (inclusive) |
| `to` | string | yes | End date `YYYY-MM-DD` (inclusive) |

**Response (200):** Array of workout list objects (see above).

**Status codes:**
- 200 — success
- 400 — invalid `user_id` or date format

---

### GET `/api/workouts/{workout_id}`

Get a single workout with its full exercise list.

**Path parameters:**
- `workout_id` — UUID string

**Response (200):** Workout detail object (see above).

**Status codes:**
- 200 — success
- 400 — invalid `workout_id`
- 404 — workout not found

---

### POST `/api/workouts`

Create a new workout, optionally with exercises.

**Request body:**

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `user_id` | UUID string | yes | Must exist |
| `name` | string | yes | Non-empty |
| `workout_date` | string | yes | `YYYY-MM-DD`, not in future |
| `workout_type` | string | yes | Non-empty, e.g. `"run"`, `"bike"`, `"gym"` |
| `remarks` | string | no | Free text |
| `tss` | float | no | ≥ 0 |
| `distance_km` | float | no | ≥ 0 |
| `duration_seconds` | integer | no | ≥ 0 |
| `avg_hr` | integer | no | 20–250 |
| `max_hr` | integer | no | 20–250 |
| `elevation_m` | integer | no | — |
| `source` | string | no | One of `manual`, `strava`, `stryd`, `strava,stryd`, `stryd,strava` |
| `strava_activity_url` | string | no | URL string |
| `exercises` | array | no | List of exercise objects (see below); defaults to `[]` |

Exercise object fields:

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `name` | string | yes | Non-empty |
| `sets` | integer | no | > 0 |
| `reps` | integer | no | — |
| `weight_kg` | float | no | — |
| `duration` | string | no | Free text |
| `rpe` | integer | no | 1–10 |
| `distance_km` | float | no | ≥ 0 |
| `duration_seconds` | integer | no | ≥ 0 |
| `avg_hr` | integer | no | 20–250 |

**Response (201):** Workout detail object.

**Status codes:**
- 201 — created
- 400 — invalid `user_id`
- 404 — user not found
- 422 — validation error (name empty, date in future, TSS < 0, invalid source, etc.)

---

### PATCH `/api/workouts/{workout_id}`

Update one or more fields of a workout. Only fields present in the request body are modified.

**Path parameters:**
- `workout_id` — UUID string

**Request body:** All fields optional — same fields as `POST /api/workouts` minus `user_id` and `exercises`.

**Response (200):** Workout detail object.

**Status codes:**
- 200 — success
- 400 — invalid `workout_id`
- 404 — workout not found
- 422 — validation error

---

### DELETE `/api/workouts/{workout_id}`

Delete a workout and all its exercises.

**Path parameters:**
- `workout_id` — UUID string

**Response:** 204 No Content

**Status codes:**
- 204 — deleted
- 400 — invalid `workout_id`
- 404 — workout not found

---

### POST `/api/workouts/{workout_id}/exercises/reorder`

Set the display order of exercises in a workout. Every exercise in the workout must be included; the server assigns `display_order` 0, 1, 2… in the submitted order.

**Path parameters:**
- `workout_id` — UUID string

**Request body:**
```json
{"ordered_ids": ["f1a2b3c4-...", "f1a2b3c4-..."]}
```

**Response (200):** Workout detail object with exercises in new order.

**Status codes:**
- 200 — success
- 400 — invalid `workout_id` or malformed exercise UUID
- 404 — workout not found or exercise not in this workout

---

### POST `/api/workouts/{workout_id}/exercises`

Append a new exercise to a workout.

**Path parameters:**
- `workout_id` — UUID string

**Request body:** Exercise object (see fields under `POST /api/workouts`).

**Response (201):** Exercise object.

**Status codes:**
- 201 — created
- 400 — invalid `workout_id`
- 404 — workout not found
- 422 — exercise validation error

---

### PATCH `/api/workouts/{workout_id}/exercises/{exercise_id}`

Update an exercise. Only supplied fields are changed.

**Path parameters:**
- `workout_id` — UUID string
- `exercise_id` — UUID string

**Request body:** All exercise fields optional (same as exercise object fields above).

**Response (200):** Exercise object.

**Status codes:**
- 200 — success
- 400 — invalid UUIDs
- 404 — workout or exercise not found
- 422 — validation error

---

### DELETE `/api/workouts/{workout_id}/exercises/{exercise_id}`

Delete an exercise from a workout.

**Path parameters:**
- `workout_id` — UUID string
- `exercise_id` — UUID string

**Response:** 204 No Content

**Status codes:**
- 204 — deleted
- 400 — invalid UUIDs
- 404 — workout or exercise not found

---

## Workout Splits

### Split object

```json
{
  "id": "a1b2c3d4-0000-0000-0000-000000000002",
  "workout_id": "e1f2a3b4-0000-0000-0000-000000000001",
  "split_index": 0,
  "distance_km": "1.000",
  "duration_seconds": 360,
  "avg_hr": 148,
  "created_at": "2024-06-01T08:00:00+00:00",
  "updated_at": "2024-06-01T08:00:00+00:00"
}
```

Note: `distance_km` is serialized as a decimal string.

---

### GET `/api/workouts/{workout_id}/splits`

Get all splits for a workout, ordered by `split_index` ascending.

**Path parameters:**
- `workout_id` — UUID string

**Response (200):** Array of split objects.

**Status codes:**
- 200 — success
- 400 — invalid `workout_id`
- 404 — workout not found

---

### POST `/api/workouts/{workout_id}/splits`

Replace all splits for a workout (deletes existing splits, inserts new set atomically).

**Path parameters:**
- `workout_id` — UUID string

**Request body:**
```json
{
  "splits": [
    {"split_index": 0, "distance_km": 1.0, "duration_seconds": 360, "avg_hr": 148},
    {"split_index": 1, "distance_km": 1.0, "duration_seconds": 355, "avg_hr": 152}
  ]
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `split_index` | integer | yes | 0-based position |
| `distance_km` | float | yes | ≥ 0 |
| `duration_seconds` | integer | yes | ≥ 0 |
| `avg_hr` | integer | no | 20–250 |

**Response (201):** Array of split objects sorted by `split_index`.

**Status codes:**
- 201 — replaced
- 400 — invalid `workout_id`
- 404 — workout not found
- 422 — validation error

---

### DELETE `/api/workouts/{workout_id}/splits`

Delete all splits for a workout.

**Path parameters:**
- `workout_id` — UUID string

**Response:** 204 No Content

**Status codes:**
- 204 — deleted
- 400 — invalid `workout_id`
- 404 — workout not found

---

## Daily Metrics

### Daily metric object

```json
{
  "id": "b2c3d4e5-0000-0000-0000-000000000001",
  "user_id": "b1f3e2d4-0000-0000-0000-000000000001",
  "metric_date": "2024-06-01",
  "resting_hr": 52,
  "hrv": 65,
  "sleep_hours": 7.5,
  "sleep_quality": 4,
  "energy": 4,
  "mood": 3,
  "notes": "Felt good after rest day",
  "created_at": "2024-06-01T08:00:00+00:00",
  "updated_at": "2024-06-01T08:00:00+00:00"
}
```

| Field | Type | Constraints |
|-------|------|-------------|
| `resting_hr` | integer \| null | 20–200 |
| `hrv` | integer \| null | 0–300 |
| `sleep_hours` | float \| null | 0–24 |
| `sleep_quality` | integer \| null | 1–5 |
| `energy` | integer \| null | 1–5 |
| `mood` | integer \| null | 1–5 |
| `notes` | string \| null | Free text |

---

### GET `/api/daily-metrics`

List daily metrics for a user in a date range, ordered by date descending. Defaults to the last 30 days when `from`/`to` are both omitted.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |
| `from` | string | no | Start date `YYYY-MM-DD` |
| `to` | string | no | End date `YYYY-MM-DD` |

**Response (200):** Array of daily metric objects.

**Status codes:**
- 200 — success
- 400 — invalid `user_id` or date format

---

### GET `/api/daily-metrics/{user_id}/{metric_date}`

Get the daily metric for a specific user and date.

**Path parameters:**
- `user_id` — UUID string
- `metric_date` — `YYYY-MM-DD`

**Response (200):** Daily metric object.

**Status codes:**
- 200 — success
- 400 — invalid `user_id` or `metric_date`
- 404 — no record for this user/date

---

### POST `/api/daily-metrics`

Create a new daily metric. Only one record per user per date is allowed.

**Request body:**

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `user_id` | UUID string | yes | Must exist |
| `metric_date` | string | yes | `YYYY-MM-DD`, not in future |
| `resting_hr` | integer | no | 20–200 |
| `hrv` | integer | no | 0–300 |
| `sleep_hours` | float | no | 0–24 |
| `sleep_quality` | integer | no | 1–5 |
| `energy` | integer | no | 1–5 |
| `mood` | integer | no | 1–5 |
| `notes` | string | no | Free text |

**Response (201):** Daily metric object.

**Status codes:**
- 201 — created
- 400 — invalid `user_id`
- 404 — user not found
- 409 — record already exists for this user/date (use PATCH to update)
- 422 — `metric_date` in future or field out of range

---

### PATCH `/api/daily-metrics/{user_id}/{metric_date}`

Update specific fields of a daily metric. Only supplied (non-null) fields are overwritten.

**Path parameters:**
- `user_id` — UUID string
- `metric_date` — `YYYY-MM-DD`

**Request body:** All fields optional — same nullable fields as the daily metric object minus `user_id`, `metric_date`, `id`, timestamps.

**Response (200):** Updated daily metric object.

**Status codes:**
- 200 — success
- 400 — invalid `user_id` or `metric_date`
- 404 — record not found (use POST to create)
- 422 — `metric_date` in future or field out of range

---

### PUT `/api/daily-metrics/{user_id}/{metric_date}`

Upsert a daily metric — creates if absent, fully replaces all metric fields if present. Null values in the body clear the corresponding fields.

**Path parameters:**
- `user_id` — UUID string
- `metric_date` — `YYYY-MM-DD`

**Request body:** Same as PATCH — all fields optional.

**Response (200):** Daily metric object.

**Status codes:**
- 200 — success
- 400 — invalid `user_id` or `metric_date`
- 404 — user not found (only on insert path)
- 422 — `metric_date` in future or field out of range

---

### GET `/api/daily-metrics/trend`

Return trend values (sleep, energy, mood) for each day in a rolling window ending today. Days without a record have `null` values.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |
| `days` | integer | no | Window size (default 7, range 1–90) |

**Response (200):**
```json
[
  {"date": "2024-05-26", "sleep_hours": 7.5, "energy": 4, "mood": 3},
  {"date": "2024-05-27", "sleep_hours": null, "energy": null, "mood": null}
]
```

**Status codes:**
- 200 — success
- 400 — invalid `user_id`

---

### DELETE `/api/daily-metrics/{user_id}/{metric_date}`

Delete a daily metric record.

**Path parameters:**
- `user_id` — UUID string
- `metric_date` — `YYYY-MM-DD`

**Response:** 204 No Content

**Status codes:**
- 204 — deleted
- 400 — invalid `user_id` or `metric_date`
- 404 — record not found

---

## Trends

### GET `/trends/summary`

> ⚠ This endpoint does **not** use the `/api/` prefix — it is served at `/trends/summary`, not `/api/trends/summary`. This is an exception to the project's routing convention.

Return a comprehensive trends summary with time-series and aggregate statistics for readiness, HRV, RHR, sleep, energy, mood, and TSS, plus period-over-period deltas.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |
| `range` | string | no | Preset window: `"7d"`, `"30d"`, or `"90d"` |
| `from` | string | no | Start date `YYYY-MM-DD` (used together with `to`) |
| `to` | string | no | End date `YYYY-MM-DD` (used together with `from`) |

`from`+`to` take precedence over `range`. If neither is given, defaults to last 30 days. `from` must be ≤ `to`.

**Response (200):**
```json
{
  "range": {"from": "2024-05-01", "to": "2024-05-31", "days": 31},
  "readiness": {
    "series": [{"date": "2024-05-01", "score": 72}],
    "avg": 70.5, "min": 60, "max": 85
  },
  "hrv": {
    "series": [{"date": "2024-05-01", "value": 65}],
    "avg": 63.0, "min": 55, "max": 72,
    "baseline_mean": 62.0, "baseline_sd": 5.5, "is_approximate": false
  },
  "rhr": {
    "series": [{"date": "2024-05-01", "value": 52}],
    "avg": 53.0, "min": 50, "max": 58,
    "baseline_mean": 53.5, "baseline_sd": 2.1, "is_approximate": false
  },
  "sleep": {
    "series": [{"date": "2024-05-01", "hours": 7.5, "quality": 4}],
    "avg_hours": 7.3, "min_hours": 6.0, "max_hours": 8.5
  },
  "energy": {
    "series": [{"date": "2024-05-01", "value": 4}],
    "avg": 3.8, "min": 2, "max": 5
  },
  "mood": {
    "series": [{"date": "2024-05-01", "value": 3}],
    "avg": 3.5, "min": 2, "max": 5
  },
  "tss": {
    "series": [{"date": "2024-05-01", "value": 55.0}],
    "avg": 48.2, "total": 1494.2
  },
  "deltas": {
    "readiness": "+3",
    "hrv": "+2",
    "rhr": "-1",
    "sleep": "+0.2h",
    "energy": "+0.3",
    "mood": "-0.1",
    "tss": "+8%"
  }
}
```

HRV/RHR baseline fields: `baseline_mean` and `baseline_sd` are computed from the 30-day rolling window ending on `to`. `is_approximate` is `true` when fewer than 30 data points were available for the baseline.

**Status codes:**
- 200 — success
- 400 — invalid `user_id`, date format, date order, or unsupported `range` preset

---

## Readiness

### GET `/api/readiness/today`

Return today's readiness record for a user.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |

**Response (200):**
```json
{
  "date": "2024-06-01",
  "score": 74.5,
  "hrv_contribution": 0.3,
  "rhr_contribution": 0.25,
  "sleep_contribution": 0.25,
  "energy_contribution": 0.2,
  "missing_data": {
    "hrv": false,
    "rhr": false,
    "sleep": false,
    "energy": false
  }
}
```

**Status codes:**
- 200 — success
- 400 — invalid `user_id`
- 404 — no readiness record for today

---

### GET `/api/readiness`

Return daily readiness scores for a date range. Days without a stored score are represented as `null`.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |
| `from` | string | yes | Start date `YYYY-MM-DD` |
| `to` | string | yes | End date `YYYY-MM-DD` (must be ≥ `from`) |

**Response (200):** Array with one entry per day — either a score object or `null`:
```json
[
  {"date": "2024-06-01", "score": 74.5},
  null,
  {"date": "2024-06-03", "score": 68.0}
]
```

**Status codes:**
- 200 — success
- 400 — invalid `user_id`, date format, or `from` > `to`

---

### POST `/api/readiness/compute`

Trigger readiness score computation for a user on a given date and persist the result. Idempotent — calling it again for the same user/date upserts with freshly computed values.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |
| `date` | string | no | Target date `YYYY-MM-DD` (default today) |

> ⚠ schema needs verification: response shape is determined by `services.readiness.job.compute_and_store`, which is not part of `backend/main.py`. Expected to match the readiness record shape used by `GET /api/readiness/today`.

**Status codes:**
- 200 — success
- 400 — invalid `user_id` or `date`
- 404 — no `daily_metrics` row found for this user/date

---

## Training Log

### GET `/api/training-log`

Return workouts (and optionally rest days) grouped by calendar week, with per-week summaries. Defaults to the last 30 days.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |
| `from` | string | no | Start date `YYYY-MM-DD` (default 30 days ago) |
| `to` | string | no | End date `YYYY-MM-DD` (default today) |
| `types` | string | no | Comma-separated workout types to filter, e.g. `"run,bike"`; `"all"` or omit to include all |
| `search` | string | no | Case-insensitive substring match against workout name and remarks |
| `include_rest` | boolean | no | When `true`, includes days with daily metric data but no workouts as `"rest"` entries (default `false`) |

**Response (200):**
```json
{
  "weeks": [
    {
      "week_start": "2024-05-27",
      "week_end": "2024-06-02",
      "label": "This week",
      "entries": [
        {
          "date": "2024-06-01",
          "type": "run",
          "id": "e1f2a3b4-0000-0000-0000-000000000001",
          "title": "Morning run",
          "duration_seconds": 3600,
          "duration_minutes": 60.0,
          "distance_km": 10.0,
          "avg_hr": 145,
          "elevation_m": 80,
          "average_pace_seconds_per_km": 360.0,
          "tss": 55.0,
          "source": "strava",
          "notes": "Easy pace",
          "weight_context": "Easy pace"
        }
      ],
      "workouts": [...],
      "summary": {
        "workout_count": 3,
        "total_distance_km": 25.0,
        "total_tss": 155.0,
        "total_time_minutes": 180.0
      }
    }
  ]
}
```

`average_pace_seconds_per_km` is only non-null for `run` and `bike` workout types when both `duration_seconds` and `distance_km` are set.

Rest day entries (when `include_rest=true`) have `type: "rest"` and include `sleep_hours`, `energy`, `mood`, `resting_hr`, and a `metrics` sub-object.

**Status codes:**
- 200 — success
- 400 — invalid `user_id` or date format

---

## Personal Records

### Personal record object

```json
{
  "id": "c3d4e5f6-0000-0000-0000-000000000001",
  "user_id": "b1f3e2d4-0000-0000-0000-000000000001",
  "track_key": "5k",
  "track_name": "5 km",
  "track_type": "time",
  "value_numeric": 1200.0,
  "achieved_on": "2024-05-15",
  "source": "strava",
  "created_at": "2024-05-15T09:00:00+00:00",
  "updated_at": "2024-05-15T09:00:00+00:00"
}
```

| Field | Description |
|-------|-------------|
| `track_key` | Machine-readable key (e.g. `"5k"`, `"bench_press"`) |
| `track_name` | Human-readable label |
| `track_type` | `"time"` (value in seconds) or `"weight"` (value in kg) |
| `value_numeric` | The record value; > 0 |
| `source` | Free-text source label (optional) |

---

### GET `/api/personal-records`

List all personal records for a user, ordered by `achieved_on` descending.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `user_id` | UUID string | yes | Target user |

**Response (200):** Array of personal record objects.

**Status codes:**
- 200 — success
- 400 — invalid `user_id`

---

### POST `/api/personal-records`

Create a personal record.

**Request body:**

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `user_id` | UUID string | yes | Must exist |
| `track_key` | string | yes | — |
| `track_name` | string | yes | — |
| `track_type` | string | yes | `"time"` or `"weight"` |
| `value_numeric` | float | yes | > 0 |
| `achieved_on` | string | yes | `YYYY-MM-DD`, not in future |
| `source` | string | no | — |

**Response (201):** Personal record object.

**Status codes:**
- 201 — created
- 400 — invalid `user_id`
- 404 — user not found
- 422 — `track_type` invalid, `value_numeric` ≤ 0, or `achieved_on` in future

---

### PATCH `/api/personal-records/{record_id}`

Update one or more fields of a personal record.

**Path parameters:**
- `record_id` — UUID string

**Request body:** All fields optional — same fields as create minus `user_id`.

**Response (200):** Updated personal record object.

**Status codes:**
- 200 — success
- 400 — invalid `record_id`
- 404 — record not found
- 422 — validation error

---

### DELETE `/api/personal-records/{record_id}`

Delete a personal record.

**Path parameters:**
- `record_id` — UUID string

**Response:** 204 No Content

**Status codes:**
- 204 — deleted
- 400 — invalid `record_id`
- 404 — record not found

---

## Integrations

### Strava

#### GET `/api/strava/connect`

Initiate the Strava OAuth flow for the default user. Returns an authorization URL; does not redirect. The default user is the first user alphabetically by name.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `scope` | string | no | OAuth scope; default `"activity:read_all"`. Allowed: `"read"`, `"activity:read"`, `"activity:read_all"` |

**Response (200):**
```json
{"authorize_url": "https://www.strava.com/oauth/authorize?client_id=..."}
```

**Status codes:**
- 200 — success
- 422 — invalid `scope`
- 500 — `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, or `STRAVA_STATE_SECRET` not configured; or no users in database

---

#### GET `/api/strava/callback`

Strava OAuth redirect callback. Exchanges authorization code for tokens, stores them, and returns an HTML page that posts a `strava_connected` message to the opener window and closes itself.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `code` | string | yes | Authorization code from Strava |
| `state` | string | yes | Signed state token issued by `/api/strava/connect` |
| `scope` | string | no | Granted scope returned by Strava |

**Response (200):** `text/html` page (not JSON). Intended as a browser redirect target; not called directly by clients.

**Status codes:**
- 200 — HTML response (success)
- 400 — `state` expired or invalid
- 500 — `STRAVA_STATE_SECRET` not configured
- 502 — Strava token exchange returned a 4xx error

---

#### GET `/api/strava/status`

Return Strava connection status for the default user. Silently refreshes the token if near expiry.

**Query parameters:** none

**Response (200):**
```json
{
  "connected": true,
  "athlete_name": "Alice Smith",
  "scope": "activity:read_all",
  "expires_at": "2024-07-01T12:00:00+00:00"
}
```

When not connected: `{"connected": false, "athlete_name": null, "scope": null, "expires_at": null}`

**Status codes:** 200 (always — errors return the null/disconnected shape)

---

#### DELETE `/api/strava/disconnect`

Delete the stored Strava token and attempt to deauthorize with Strava's API (best-effort; failure is swallowed).

**Query parameters:** none

**Response (200):**
```json
{"disconnected": true}
```

**Status codes:** 200 (always)

---

### Stryd

#### POST `/api/stryd/connect`

Authenticate against Stryd with email and password, encrypt and store the credentials, and return connection status. Operates on the default user (first alphabetically by name).

**Request body:**

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `email` | string | yes | Valid email format |
| `password` | string | yes | Min length 1 |

**Response (200):**
```json
{
  "connected": true,
  "athlete_id": 123456,
  "stryd_user_email": "alice@example.com"
}
```

**Status codes:**
- 200 — success
- 422 — validation error (invalid email format or empty password)
- 500 — no users in database or Stryd sign-in failure

---

#### GET `/api/stryd/status`

Return Stryd connection status for the default user. Silently refreshes the session if near expiry. Deletes stored credentials if refresh fails.

**Query parameters:** none

**Response (200):**
```json
{
  "connected": true,
  "athlete_id": 123456,
  "stryd_email": "alice@example.com",
  "session_expires_at": "2024-06-25T12:00:00+00:00"
}
```

When not connected: `{"connected": false, "athlete_id": null, "stryd_email": null, "session_expires_at": null}`

**Status codes:** 200 (always)

---

#### DELETE `/api/stryd/disconnect`

Delete stored Stryd credentials for the default user.

**Query parameters:** none

**Response (200):**
```json
{"disconnected": true}
```

**Status codes:** 200 (always)

---

## Sync

### POST `/api/sync/strava`

Trigger a Strava activity sync for the session user. Creates a `SyncJob` record and runs the sync via `BackgroundTasks`. Returns 202 immediately; poll `/api/sync/strava/status?job_id=<id>` for progress.

**Request body (optional):**
```json
{"since_date": "2024-01-01"}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `since_date` | string | no | `YYYY-MM-DD`; cannot be more than 1 year in the past |

**Response (202):**
```json
{
  "job_id": "...",
  "status": "running",
  "polling_url": "/api/sync/strava/status?job_id=..."
}
```

**Status codes:**
- 202 — sync started
- 409 — another sync is already running for this user (`job_id` of active job returned)
- 422 — Strava not connected, or `since_date` invalid/too old

---

### GET `/api/sync/strava/status`

Return the full `SyncJob` record for a given `job_id`. Auth required (session user must match job owner).

**Query parameters:**

| Name | Type | Required |
|------|------|----------|
| `job_id` | UUID | yes |

**Response (200):**
```json
{
  "id": "...",
  "user_id": "...",
  "source": "strava",
  "job_type": "manual_trigger",
  "status": "completed",
  "started_at": "2024-06-01T08:00:00+00:00",
  "completed_at": "2024-06-01T08:01:30+00:00",
  "activities_fetched": 12,
  "activities_created": 8,
  "activities_updated": 4,
  "activities_skipped": 0,
  "error_message": null,
  "since_date": "2024-01-01"
}
```

`status` values: `pending`, `running`, `completed`, `failed`, `cancelled`.

**Status codes:** 200, 404

---

### GET `/api/sync/strava/latest`

Return info about the most recent Strava sync for the session user.

**Query parameters:** none (optional `user_id` UUID returns full SyncJob for that user; requires auth)

**Response (200) — session user (legacy summary):**
```json
{
  "synced_at": "2024-06-01T08:01:30+00:00",
  "activities_synced": 12,
  "new_workouts": 8
}
```

**Response (200) — with `user_id` param (full SyncJob):** same shape as `/api/sync/strava/status`.

**Status codes:** 200, 404

---

### GET `/api/sync/strava/dry-run`

Read-only preview of what reconciling the current `strava_activities` into `workouts` would produce. No DB writes.

**Query parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `user_id` | UUID | yes | — |
| `since_date` | string | no | all time |
| `limit` | integer | no | 20 (max 50) |

**Status codes:** 200, 400

---

### GET `/api/sync/strava/data-quality`

Return data quality counts describing the sync state between `strava_activities` and `workouts`.

**Query parameters:**

| Name | Type | Required |
|------|------|----------|
| `user_id` | UUID | yes |

**Response (200):**
```json
{
  "strava_activities_total": 100,
  "workouts_from_strava": 95,
  "workouts_no_source": 3,
  "workouts_stryd_linked": 20
}
```

**Status codes:** 200, 400

---

### POST `/api/sync/strava/reconcile`

Reconcile unlinked `strava_activities` into `workouts` rows. Idempotent upsert.

**Query parameters:**

| Name | Type | Required |
|------|------|----------|
| `user_id` | UUID | yes |

**Response (200):** Reconcile result counts (created, updated, skipped).

---

### GET `/api/sync/history`

Return paginated SyncJob history for the session user.

**Query parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `limit` | integer | no | 5 |

**Response (200):**
```json
{
  "jobs": [
    {
      "id": "...",
      "source": "strava",
      "job_type": "manual_trigger",
      "status": "completed",
      "started_at": "2024-06-01T08:00:00+00:00",
      "completed_at": "2024-06-01T08:01:30+00:00",
      "duration_seconds": 90,
      "activities_fetched": 12,
      "activities_created": 8,
      "activities_updated": 4,
      "activities_skipped": 0,
      "error_message": null
    }
  ]
}
```

**Status codes:** 200

---

## Conventions

### URL structure

All data API endpoints use the `/api/` prefix with hyphenated path segments (e.g. `/api/daily-metrics`, `/api/habit-logs`, `/api/personal-records`). The one exception is `GET /trends/summary`, which predates this convention.

### Multi-user

This is a multi-user app. Nearly every endpoint accepts `user_id` as a query parameter or path parameter to identify the target user. Integration endpoints (Strava, Stryd) currently operate on the "default user" (first alphabetically by name) as a placeholder; per-user multi-integration support is planned.

### Dates

- Date parameters use ISO 8601 format: `YYYY-MM-DD` (e.g. `2024-06-01`).
- Timestamps in responses are ISO 8601 with UTC timezone offset (e.g. `2024-06-01T08:00:00+00:00`).
- Date range endpoints use query parameter aliases `from` and `to`.
- Past-only fields (e.g. `workout_date`, `metric_date`, `achieved_on`) reject future dates with 422.

### IDs

All resource IDs are UUIDs serialized as lowercase hyphenated strings. A non-UUID value for any ID parameter returns 400.

### Error responses

| Code | Meaning |
|------|---------|
| 400 | Malformed input (invalid UUID, bad date format, missing required param) |
| 404 | Resource not found |
| 409 | Conflict — e.g. duplicate entry for same date, last user cannot be deleted |
| 422 | Validation failure — field out of valid range, date in future, etc. |
| 503 | Database unavailable (only on `GET /api/users`) |

422 responses for field validation use a structured detail: `{"field": "<field_name>", "error": "<message>"}`.

### Response format

All responses are `application/json` via `JSONResponse`, except `GET /api/strava/callback` which returns `text/html`.

### TSS source

When `tss` is set manually via POST or PATCH, `tss_source` is set to `"manual"`. When `tss` is cleared (set to `null`), `tss_source` is also cleared. Source values from integrations (`"strava"`, `"stryd"`, `"strava,stryd"`) are written by the sync jobs, not by these endpoints directly.
