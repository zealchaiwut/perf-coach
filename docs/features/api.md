# Hermes External Agent API Reference

This document describes the perf-coach API endpoints called by Hermes (the external AI assistant). All endpoints require Bearer token authentication via the `Authorization` header.

## Auth

Hermes authenticates to perf-coach using a Bearer token sent in the HTTP `Authorization` header:

```
Authorization: Bearer <token>
```

The token value is set in the environment variable `HERMES_API_TOKEN` on the worker service and must match a pre-configured secret in the perf-coach deployment. Bearer tokens are validated by the `_resolve_read_user` dependency in `backend/worker_app.py`, which extracts the username from the token and verifies it against the user database.

**Main app endpoints** (`backend/main.py`, port 9000): Authenticated via session cookie (user must be logged in via the web UI). The `resolve_user` dependency extracts the user from the signed `perf-coach-session` cookie.

**Worker endpoints** (`backend/worker_app.py`, port 9100): Authenticated via Bearer token in the `Authorization` header. The `_resolve_read_user` dependency extracts and validates the token.

---

## `GET /api/brief/today`

**Method:** GET  
**Path:** `/api/brief/today`  
**Auth:** Session cookie (main app)  
**Port:** 9000

Returns the daily coaching brief for today, including form (CTL/ATL/TSB), weight status, advisories, and planned sessions for the week.

**Query Parameters:** None

**Response (HTTP 200):**

```json
{
  "schema_version": 3,
  "for_date": "2026-07-17",
  "generated_at": "2026-07-17T08:00:00+07:00",
  "today": {
    "date": "2026-07-17",
    "session_type": "run",
    "planned": true,
    "intensity": "easy",
    "duration_min": 50,
    "notes": null
  },
  "tomorrow": {
    "date": "2026-07-18",
    "session_type": null,
    "planned": false,
    "intensity": null,
    "duration_min": null,
    "notes": null
  },
  "form": {
    "ctl": 42.0,
    "atl": 38.0,
    "tsb": 4.0,
    "ramp": 1.2,
    "flags": {
      "guardrail_state": "ok"
    },
    "interpretation": "Neutral"
  },
  "recent_wrap": {
    "window_days": 14,
    "sessions_planned": 10,
    "sessions_completed": 8,
    "adherence": 0.8,
    "load_trend": 1.2,
    "highlights_md": "Good week."
  },
  "weight": {
    "current_kg": 72.5,
    "trend_7d": -0.2,
    "trend_28d": -0.5,
    "target_kg": 70.0,
    "target_date": "2026-09-01",
    "pace_kg_per_week": -0.2,
    "on_track": true,
    "projection_date": "2026-08-25"
  },
  "advisories": [
    {
      "key": "low_run_volume",
      "severity": "info",
      "text": "Consider more easy mileage."
    }
  ],
  "actions": [],
  "week_plan": {
    "days": [
      {
        "date": "2026-07-18",
        "day": "Sat",
        "session_type": "run",
        "intensity": "easy",
        "duration_min": 60,
        "planned": true
      }
    ]
  }
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | integer | Schema version (3) for API compatibility tracking |
| `for_date` | string (ISO 8601) | Date this brief was generated for (Bangkok timezone) |
| `generated_at` | string (ISO 8601 with TZ) | Timestamp when the brief was assembled |
| `today` | object | Today's planned session details (or null fields if no session) |
| `tomorrow` | object | Tomorrow's planned session details (or null fields if no session) |
| `form` | object | Current training form metrics (CTL, ATL, TSB, interpretation) |
| `recent_wrap` | object | 14-day summary of sessions and adherence |
| `weight` | object | Current weight status and target progress |
| `advisories` | array | List of coaching advisories (low volume, etc.) |
| `actions` | array | Actionable recommendations (currently empty, reserved) |
| `week_plan` | object | `{"days": [...]}` — remaining days this Bangkok week; each day has `date`, `day`, `session_type`, `intensity`, `duration_min`, `planned` |

**Error Responses:**
- `401` — Not authenticated (session cookie missing or invalid)
- `404` — User not found in database

**Notes:**
- Dates are in Asia/Bangkok timezone (UTC+7).
- Schema version 3 adds the `week_plan` field. Its shape is `{"days": [...]}` where each element describes one remaining day of the Bangkok week (tomorrow through Sunday). Empty when tomorrow is Saturday, Sunday, or past this week's Sunday.
- The `form` field contains guardrail state and interpretation suitable for AI coaching.

---

## `GET /api/readiness`

**Method:** GET  
**Path:** `/api/readiness`  
**Auth:** Session cookie (main app)  
**Port:** 9000

Returns current training-load readiness metrics (CTL, ATL, TSB, ACWR) or legacy wellness score range.

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `from` | string (ISO 8601) | Optional | Start date for legacy wellness score range (YYYY-MM-DD). Required if `to` is provided. |
| `to` | string (ISO 8601) | Optional | End date for legacy wellness score range (YYYY-MM-DD). Required if `from` is provided. |

**Response (HTTP 200) — No Date Params:**

```json
{
  "building_baseline": false,
  "ctl": 42.1,
  "atl": 38.5,
  "tsb": 3.6,
  "form_label": "Fresh",
  "readiness_label": "Fresh",
  "series": [
    {
      "date": "2026-06-20",
      "ctl": 40.2,
      "atl": 39.1,
      "tsb": 1.1,
      "acwr": 1.03
    },
    {
      "date": "2026-06-21",
      "ctl": 40.5,
      "atl": 38.8,
      "tsb": 1.7,
      "acwr": 1.02
    }
  ]
}
```

**Response (HTTP 200) — With Date Params (Legacy Wellness):**

```json
[
  {
    "date": "2026-06-20",
    "score": 55.3
  },
  {
    "date": "2026-06-21",
    "score": 56.1
  },
  null,
  {
    "date": "2026-06-23",
    "score": 54.8
  }
]
```

**Response Fields (No Date Params):**

| Field | Type | Description |
|-------|------|-------------|
| `building_baseline` | boolean | True if fewer than 30 workouts in the past 90 days (baseline not yet established) |
| `ctl` | number or null | Chronic training load (fitness), 1 decimal place. Null if building baseline. |
| `atl` | number or null | Acute training load (fatigue), 1 decimal place. Null if building baseline. |
| `tsb` | number or null | Training stress balance (form), 1 decimal place. Null if building baseline. |
| `form_label` | string or null | Human label for TSB (e.g. "Fresh", "Neutral", "Fatigued"). Null if building baseline. |
| `readiness_label` | string or null | Deprecated alias for `form_label`. Kept for one release. |
| `series` | array | 90-day history of daily CTL, ATL, TSB, ACWR values. Empty if building baseline. |

**Response Fields (With Date Params, Legacy):**

Each element is either:
- `null` — no wellness score recorded for that date
- Object with `date` (ISO 8601) and `score` (number, wellness readiness 0–100 scale)

**Error Responses:**
- `400` — Invalid date format or missing required parameter (`from` without `to`, etc.)
- `401` — Not authenticated

**Notes:**
- Without date params, returns training-load metrics (CTL/ATL/TSB), the primary source of truth for form calculation.
- With both `from` and `to` params, returns legacy wellness score range (historical compatibility).
- CTL/ATL/TSB values are pulled from the same snapshot series used by the fitness/fatigue/form chart and weekly coach report, ensuring consistency.
- ACWR (Acute/Chronic Work Ratio) is useful for detecting rapid load spikes.

---

## `GET /api/planned-sessions`

**Method:** GET  
**Path:** `/api/planned-sessions`  
**Auth:** Session cookie (main app)  
**Port:** 9000

Returns planned sessions for a date range or the current week.

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `from` | string (ISO 8601) | Optional | Start date (YYYY-MM-DD). Default: start of current week. |
| `to` | string (ISO 8601) | Optional | End date (YYYY-MM-DD). Default: end of current week. Required if `from` is provided. |

**Response (HTTP 200):**

A week-bundle object grouping sessions by day across the requested range. Empty days are included (Rest day UI).

```json
{
  "from": "2026-07-14",
  "to": "2026-07-20",
  "days": [
    {
      "date": "2026-07-14",
      "dow": "MON",
      "planned": [
        {
          "id": "550e8400-e29b-41d4-a716-446655440000",
          "planned_date": "2026-07-14",
          "session_type": "run",
          "name": "Easy 10k",
          "structure": {
            "distance_km": 10.0,
            "duration_min": 60,
            "intensity": "easy",
            "blocks": []
          },
          "notes": "Easy aerobic run",
          "status": "planned",
          "matched_workout_id": null,
          "actual": null,
          "estimated_tss": 42.0,
          "estimated_distance_km": 10.0,
          "plan_warnings": [],
          "created_at": "2026-07-13T10:30:00+07:00",
          "updated_at": "2026-07-13T10:30:00+07:00"
        }
      ],
      "unplanned": []
    },
    {
      "date": "2026-07-15",
      "dow": "TUE",
      "planned": [
        {
          "id": "550e8400-e29b-41d4-a716-446655440002",
          "planned_date": "2026-07-15",
          "session_type": "strength",
          "name": "Lower Body",
          "structure": {
            "duration_min": 45,
            "blocks": [
              {"name": "Squats", "reps": 5, "sets": 3, "load_kg": 100}
            ]
          },
          "notes": null,
          "status": "completed",
          "matched_workout_id": "550e8400-e29b-41d4-a716-446655440099",
          "actual": {
            "id": "550e8400-e29b-41d4-a716-446655440099",
            "name": "Lower Body",
            "workout_type": "strength",
            "run_subtype": null,
            "date": "2026-07-15",
            "distance_km": null,
            "duration_seconds": 2700,
            "tss": null,
            "feeling": null,
            "meta": "45min",
            "exercises": [
              {
                "id": "550e8400-e29b-41d4-a716-446655440088",
                "name": "Squats",
                "sets": 3,
                "reps": 5,
                "weight_kg": 100.0,
                "duration": null,
                "rpe": 8
              }
            ],
            "needs_rpe": false
          },
          "estimated_tss": null,
          "estimated_distance_km": null,
          "plan_warnings": [],
          "created_at": "2026-07-13T11:00:00+07:00",
          "updated_at": "2026-07-15T15:45:00+07:00"
        }
      ],
      "unplanned": [
        {
          "id": "550e8400-e29b-41d4-a716-446655440077",
          "name": "Morning Ride",
          "workout_type": "bike",
          "run_subtype": null,
          "date": "2026-07-15",
          "meta": "60min · 30.0 km"
        }
      ]
    }
  ]
}
```

**Top-level fields:**

| Field | Type | Description |
|-------|------|-------------|
| `from` | string (YYYY-MM-DD) | Start of the returned range (Bangkok timezone) |
| `to` | string (YYYY-MM-DD) | End of the returned range (Bangkok timezone) |
| `days` | array | One entry per calendar day across the range (including empty Rest days) |

**Day object fields (`days[*]`):**

| Field | Type | Description |
|-------|------|-------------|
| `date` | string (YYYY-MM-DD) | Calendar date for this day |
| `dow` | string | Day-of-week abbreviation: `MON`–`SUN` |
| `planned` | array | Planned sessions scheduled for this day (see below) |
| `unplanned` | array | Workouts logged on this day that were not matched to any planned session ("ghost" workouts) |

**Planned session object fields (`days[*].planned[*]`):**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string (UUID) | Unique identifier for the planned session |
| `planned_date` | string (YYYY-MM-DD) | Date the session is scheduled |
| `session_type` | string | `run`, `strength`, `recovery`, `sport`, etc. |
| `name` | string or null | Human-readable label (e.g. "Easy 10k", "Lower Body") |
| `structure` | object or null | Session details (distance, duration, intensity, exercise blocks) |
| `notes` | string or null | Coach or athlete notes |
| `status` | string | `planned`, `completed`, `missed`, `needs_review` |
| `matched_workout_id` | string (UUID) or null | ID of the matched workout when status is `completed` or `needs_review` |
| `actual` | object or null | Compact actual-workout summary when a workout is matched (see below); `null` otherwise |
| `estimated_tss` | number or null | Formula-estimated TSS for still-open future sessions; `null` for matched/missed/past sessions |
| `estimated_distance_km` | number or null | Formula-estimated distance for still-open future sessions; `null` otherwise |
| `plan_warnings` | array | Load-guard warning strings (may be empty); never omitted |
| `candidates` | array | Present only when `status` is `needs_review`; list of ghost-workout dicts (same shape as `unplanned` items) that are candidate matches |
| `created_at` | string (ISO 8601) | When the planned session was created |
| `updated_at` | string (ISO 8601) | When the planned session was last modified |

**Actual workout summary object (`actual`):**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string (UUID) | Workout id |
| `name` | string | Workout name |
| `workout_type` | string | e.g. `run`, `strength`, `bike` |
| `run_subtype` | string or null | Run sub-type when applicable |
| `date` | string (YYYY-MM-DD) | Date the workout was logged |
| `distance_km` | number or null | Distance |
| `duration_seconds` | number or null | Duration |
| `tss` | number or null | Training Stress Score |
| `feeling` | string or null | Logged feeling/RPE |
| `meta` | string | Human-readable summary (e.g. `"45min · 85 TSS"`) |
| `exercises` | array | Logged exercises for strength sessions (id, name, sets, reps, weight_kg, duration, rpe) |
| `needs_rpe` | boolean | `true` if any logged exercise is missing an RPE value |

**Unplanned / ghost workout object fields (`days[*].unplanned[*]`):**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string (UUID) | Workout id |
| `name` | string | Workout name |
| `workout_type` | string | e.g. `run`, `bike`, `strength` |
| `run_subtype` | string or null | Run sub-type when applicable |
| `date` | string (YYYY-MM-DD) | Date the workout was logged |
| `meta` | string | Human-readable summary (e.g. `"60min · 30.0 km"`) |

**Error Responses:**
- `400` — Invalid date format
- `401` — Not authenticated
- `422` — `to` is earlier than `from`

**Notes:**
- Default range is the current Mon–Sun ISO week in Bangkok timezone if no params are provided.
- Empty days are always included so the UI can render Rest day placeholders.
- The `structure` field is flexible; `run` sessions use `distance_km`/`duration_min`/`intensity`; `strength` sessions use `blocks`.
- `estimated_tss` / `estimated_distance_km` are formula-only estimates (no LLM) for unmatched future sessions — used by the weekly progress bar to reflect "what's still coming".

---

## `GET /api/training/gap-analysis`

**Method:** GET  
**Path:** `/api/training/gap-analysis`  
**Auth:** Session cookie (main app)  
**Port:** 9000

Returns gaps between current training profile and athlete's stated training goals, with recommendations to close each gap.

**Query Parameters:** None

**Response (HTTP 200):**

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440001",
  "evaluated_at": "2026-07-17T12:00:00Z",
  "gaps": [
    {
      "code": "gap_001",
      "category": "volume",
      "title": "Insufficient easy-run volume",
      "description": "Current easy-run mileage is 25 km/week; goal is 30 km/week.",
      "severity": "info",
      "recommended_action": "Add 5 km of easy running per week",
      "estimated_weeks_to_close": 2,
      "progress": 0.8
    },
    {
      "code": "gap_002",
      "category": "intensity",
      "title": "Missing tempo work",
      "description": "No tempo sessions in the past 4 weeks.",
      "severity": "warning",
      "recommended_action": "Schedule 1 tempo session per week (8–12 km)",
      "estimated_weeks_to_close": 1,
      "progress": 0.0
    }
  ]
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | string (UUID) | User being evaluated |
| `evaluated_at` | string (ISO 8601 UTC) | Timestamp of evaluation |
| `gaps` | array | List of detected gaps between current state and goals |

**Gap Object Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `code` | string | Unique identifier for this gap (e.g., `gap_001`) |
| `category` | string | Gap category: `volume`, `intensity`, `frequency`, `specificity`, etc. |
| `title` | string | Short human-readable title |
| `description` | string | Detailed explanation of the gap and current vs. goal state |
| `severity` | string | One of: `info`, `warning`, `critical` |
| `recommended_action` | string | Specific action to close the gap |
| `estimated_weeks_to_close` | integer or null | Estimated weeks needed to close this gap, or null if unknown |
| `progress` | number (0–1) | Current progress toward closing the gap (0 = not started, 1 = closed) |

**Error Responses:**
- `401` — Not authenticated
- `404` — User not found or no training goals configured

**Notes:**
- Gap analysis is computed against user-configured training goals (typically set in Settings).
- Each gap includes a severity level and recommended action suitable for AI coaching.
- Progress field helps prioritize which gaps to address first.

---

## `GET /api/weight-chart`

**Method:** GET  
**Path:** `/api/weight-chart`  
**Auth:** Session cookie (main app)  
**Port:** 9000

Returns weight-entry chart data for a date range, including entries, trend (EWMA), plan series, milestones, and statistics.

**Query Parameters:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `from` | string (ISO 8601) | Optional | Today − 90 days | Start date (YYYY-MM-DD) |
| `to` | string (ISO 8601) | Optional | Today | End date (YYYY-MM-DD) |
| `range` | string | Optional | — | Shorthand range: `7D`, `30D`, `90D`, `6M`, `1Y`, `ALL`. Overrides `from`/`to` if provided. |
| `include_target` | boolean | Optional | true | Whether to include the active weight target plan in response |
| `include_future_zone` | boolean | Optional | false | Whether to include projected future zone (prediction band) |

**Response (HTTP 200):**

```json
{
  "entries": [
    {
      "date": "2026-06-20",
      "weight_kg": 72.8,
      "notes": null
    },
    {
      "date": "2026-06-21",
      "weight_kg": 72.6,
      "notes": "After run"
    },
    {
      "date": "2026-06-22",
      "weight_kg": 72.5,
      "notes": null
    }
  ],
  "trend": [
    {
      "date": "2026-06-20",
      "weight_kg": 72.75
    },
    {
      "date": "2026-06-21",
      "weight_kg": 72.68
    }
  ],
  "stats": {
    "current_weight_kg": 72.5,
    "current_avg_kg": 72.68,
    "delta_7d_kg": -0.3,
    "delta_30d_kg": -0.8,
    "weekly_rate_ewma_kg": -0.15,
    "ewma_alpha": 0.1429
  },
  "plan_series": [
    {
      "date": "2026-06-20",
      "plan_kg": 72.9
    },
    {
      "date": "2026-06-21",
      "plan_kg": 72.8
    }
  ],
  "milestones": [
    {
      "date": "2026-08-01",
      "kind": "milestone",
      "weight_kg": 70.0,
      "label": "Milestone 1"
    },
    {
      "date": "2026-09-01",
      "kind": "target",
      "weight_kg": 70.0,
      "label": "Target"
    }
  ],
  "today_marker": {
    "date": "2026-07-17",
    "logged_today": false
  }
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `entries` | array | Raw weight entries in the requested date range |
| `trend` | array | EWMA (exponential moving average) trend line, one per day with a recorded entry |
| `stats` | object | Summary statistics (current weight, deltas, EWMA params) |
| `plan_series` | array | Weight-plan projection (one point per day in range). Present only if `include_target=true` and an active target exists. |
| `milestones` | array | Target milestones and final goal date. Present only if `include_target=true` and an active target exists. |
| `today_marker` | object | Flag indicating whether an entry was logged today and today's date |

**Stats Object Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `current_weight_kg` | number or null | Most recent weight in the range |
| `current_avg_kg` | number or null | Most recent trend value |
| `delta_7d_kg` | number or null | Change from 7 days ago |
| `delta_30d_kg` | number or null | Change from 30 days ago |
| `weekly_rate_ewma_kg` | number or null | EWMA weekly rate of change |
| `ewma_alpha` | number | Smoothing factor (2 / (span + 1), default span = 13) |

**Error Responses:**
- `400` — Invalid date format
- `401` — Not authenticated
- `404` — User not found
- `422` — Range exceeds 365 days or invalid `range` token

**Notes:**
- Date range is clamped to the same calendar (Bangkok timezone).
- EWMA smoothing uses a default span of 13 days (α ≈ 0.1429).
- Plan series is optional and only present if the user has an active weight target.
- The `range` shorthand token (e.g., `7D`) spans N days inclusive; `7D` = 7 days from today − 6 through today.

---

## `GET /api/weight-targets/active`

**Method:** GET  
**Path:** `/api/weight-targets/active`  
**Auth:** Session cookie (main app)  
**Port:** 9000

Returns the user's currently active weight target (goal weight, target date, progress metrics).

**Query Parameters:** None

**Response (HTTP 200):**

```json
{
  "target": {
    "id": "550e8400-e29b-41d4-a716-446655440010",
    "user_id": "550e8400-e29b-41d4-a716-446655440001",
    "status": "active",
    "start_date": "2026-06-01",
    "start_weight_kg": 73.5,
    "target_weight_kg": 70.0,
    "target_date": "2026-09-01",
    "created_at": "2026-06-01T08:00:00Z",
    "current_weight_kg": 72.5,
    "current_avg_kg": 72.68,
    "delta_from_start_kg": -1.0,
    "delta_to_target_kg": -2.5,
    "pct_complete": 0.4,
    "days_elapsed": 46,
    "days_remaining": 76,
    "pace_kg_per_week": -0.15,
    "on_track": true,
    "projected_arrival_date": "2026-08-25"
  }
}
```

**Response (HTTP 200) — No Active Target:**

```json
{
  "target": null
}
```

**Response Fields (Target Object):**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string (UUID) | Unique identifier for this target |
| `user_id` | string (UUID) | User who set this target |
| `status` | string | Always `active` for this endpoint |
| `start_date` | string (ISO 8601) | When the target was created (Bangkok timezone) |
| `start_weight_kg` | number | Weight at target creation |
| `target_weight_kg` | number | Goal weight |
| `target_date` | string (ISO 8601) | Goal date to reach target weight |
| `created_at` | string (ISO 8601 UTC) | When the target was created in the database |
| `current_weight_kg` | number or null | Most recent logged weight |
| `current_avg_kg` | number or null | Current EWMA trend weight |
| `delta_from_start_kg` | number or null | Progress from start weight |
| `delta_to_target_kg` | number or null | Remaining distance to target |
| `pct_complete` | number (0–1) | Percent of goal achieved (0 = just started, 1 = goal met) |
| `days_elapsed` | integer | Days since target creation |
| `days_remaining` | integer | Days until target date |
| `pace_kg_per_week` | number or null | Required weekly rate to hit target on time |
| `on_track` | boolean | Whether current pace will hit the target date |
| `projected_arrival_date` | string (ISO 8601) or null | Estimated date target will be reached at current pace |

**Error Responses:**
- `401` — Not authenticated
- `404` — User not found

**Notes:**
- Returns null if no active target exists (user hasn't set a weight goal yet).
- `on_track` is computed by comparing the required pace to actual pace.
- `projected_arrival_date` is computed if pace is non-zero; null if pace is zero or undetermined.

---

## `GET /api/plan/today`

**Method:** GET  
**Path:** `/api/plan/today`  
**Auth:** Bearer token (worker app)  
**Port:** 9100

Returns today's planned session details, used by Hermes to assemble the daily brief.

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `date` | string (ISO 8601) | Optional | Date to query (YYYY-MM-DD). Default: today in Bangkok timezone. |
| `user` | string | Required | Username of the athlete (resolved via token). |

**Response (HTTP 200):**

```json
{
  "plan_date": "2026-07-17",
  "planned": true,
  "sessions": [
    {
      "session_type": "run",
      "name": "Easy 10k",
      "target": {
        "distance_km": 10.0,
        "duration_min": 60,
        "intensity": "easy"
      },
      "note": "Easy aerobic run",
      "status": "planned"
    }
  ]
}
```

**Response (HTTP 200) — No Plan for Date:**

```json
{
  "plan_date": "2026-07-17",
  "planned": false,
  "sessions": []
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `plan_date` | string (ISO 8601) | Date queried |
| `planned` | boolean | Whether any sessions are planned for this date |
| `sessions` | array | Array of planned sessions (empty if none) |

**Session Object Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_type` | string | Type: `run`, `strength`, `recovery`, `sport`, etc. |
| `name` | string | Human-readable name (e.g., "Easy 10k") |
| `target` | object | Target metrics: `distance_km`, `duration_min`, `intensity`. Fields are optional depending on session type. |
| `note` | string or null | Coach notes or athlete comments |
| `status` | string | Status: `planned`, `completed`, `missed`, `skipped` |

**Error Responses:**
- `400` — Invalid date format
- `401` — Bearer token missing or invalid
- `403` — Token valid but user does not exist or is inactive
- `404` — User not found

**Notes:**
- This is a **worker endpoint** (port 9100), not the main app.
- Bearer token is required; session cookies are not accepted.
- The `target` field may have null values for fields not applicable to the session type (e.g., `distance_km` is null for strength sessions).

---

## `GET /api/weight/status`

**Method:** GET  
**Path:** `/api/weight/status`  
**Auth:** Bearer token (worker app)  
**Port:** 9100

Returns current weight status for the user on a given date, used by Hermes to build the weight block of the daily brief.

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `date` | string (ISO 8601) | Optional | Date to query (YYYY-MM-DD). Default: today in Bangkok timezone. |
| `user` | string | Required | Username of the athlete (resolved via token). |

**Response (HTTP 200):**

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440001",
  "status_date": "2026-07-17",
  "current_kg": 72.5,
  "trend_7d": -0.2,
  "trend_28d": -0.5,
  "target_kg": 70.0,
  "target_date": "2026-09-01",
  "pace_kg_per_week": -0.2,
  "on_track": true,
  "projection_date": "2026-08-25",
  "label": "On track to goal"
}
```

**Response (HTTP 200) — No Weight Data:**

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440001",
  "status_date": "2026-07-17",
  "current_kg": null,
  "trend_7d": null,
  "trend_28d": null,
  "target_kg": null,
  "target_date": null,
  "pace_kg_per_week": null,
  "on_track": null,
  "projection_date": null,
  "label": "No weight data"
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | string (UUID) | User ID |
| `status_date` | string (ISO 8601) | Date the status was computed for |
| `current_kg` | number or null | Most recent weight entry on or before `status_date` |
| `trend_7d` | number or null | 7-day trend (current vs. 7 days ago) |
| `trend_28d` | number or null | 28-day trend (current vs. 28 days ago) |
| `target_kg` | number or null | Active weight target, or null if none set |
| `target_date` | string (ISO 8601) or null | Target date to reach goal, or null if none set |
| `pace_kg_per_week` | number or null | Required weekly rate to hit target on time, or null if no target |
| `on_track` | boolean or null | Whether current pace will hit the target date |
| `projection_date` | string (ISO 8601) or null | Estimated arrival date at current pace, or null if pace is zero/unknown |
| `label` | string | Human-readable status label (e.g., "On track to goal", "Ahead of pace", "No weight data") |

**Error Responses:**
- `400` — Invalid date format
- `401` — Bearer token missing or invalid
- `403` — Token valid but user does not exist or is inactive
- `404` — User not found

**Notes:**
- This is a **worker endpoint** (port 9100), not the main app.
- Bearer token is required; session cookies are not accepted.
- All fields except `user_id`, `status_date`, and `label` may be null if no weight data exists.
- The `label` field is suitable for AI coaching and always has a meaningful human-readable string.

---

## API Versioning & Stability

All endpoints use SCHEMA_VERSION fields or explicit version markers (e.g., SCHEMA_VERSION 3 for `/api/brief/today`) to signal breaking changes. Clients should check these fields and handle version mismatches gracefully.

Future breaking changes will increment the schema version and be documented in `CHANGELOG.md`.

---

## Example: Hermes Daily Brief Assembly

Hermes assembles a daily brief by calling:

1. **`GET /api/brief/today`** (main app) → Get the full brief with form, weight, advisories, and plan
   - *Alternative workflow:*
2. **`GET /api/plan/today?user=<username>`** (worker) → Get today's planned sessions
3. **`GET /api/weight/status?user=<username>`** (worker) → Get current weight status
4. Combine results to build a coaching message

The main app's `/api/brief/today` endpoint is the recommended single call for convenience. The worker endpoints are available if Hermes needs to fetch only specific blocks (plan or weight) separately.

---

## Support & Debugging

- **Invalid Bearer Token:** Verify `HERMES_API_TOKEN` environment variable matches both Hermes deployment and perf-coach worker service.
- **Date Format Issues:** All dates must be ISO 8601 format (YYYY-MM-DD). Bangkok timezone is assumed for date interpretation.
- **Schema Version Mismatch:** Check the `schema_version` field in responses; update Hermes to handle the latest version.
- **Port Confusion:** Main app endpoints use port 9000 (session auth); worker endpoints use port 9100 (Bearer auth).
