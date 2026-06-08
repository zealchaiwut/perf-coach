# Weight Tracking

## Purpose

Weight tracking lets a user log daily weigh-ins, visualise their trend over time, and
set a goal target with deadline. The feature covers the full arc: free-form entry
logging → rolling average chart → goal setting → progress and projection → milestone
timeline → export.

---

## Data Model

### `weight_entries`

One row per weigh-in. A user may have multiple entries on the same date (e.g. morning
and evening), but only one entry per date is allowed via the quick-log form.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users | |
| `entry_date` | DATE | ISO YYYY-MM-DD |
| `entry_time` | TIME nullable | HH:MM |
| `weight_kg` | FLOAT | 20–300 kg |
| `created_at` | TIMESTAMP | |

### `weight_targets`

One active target per user at a time. Completed targets are kept for history.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users | |
| `start_weight_kg` | FLOAT | |
| `start_date` | DATE | |
| `target_weight_kg` | FLOAT | |
| `target_date` | DATE | |
| `notes` | TEXT nullable | |
| `status` | ENUM | `active`, `achieved`, `replaced`, `abandoned` |
| `end_weight_kg` | FLOAT nullable | set when ended |
| `ended_at` | TIMESTAMP nullable | |
| `duration_days` | INT nullable | |
| `created_at` | TIMESTAMP | |

---

## API Reference

### Weight Entries

#### `POST /api/weight-entries`
Log a new weigh-in.

**Request body:**
```json
{
  "entry_date": "2025-06-08",
  "entry_time": "07:15",
  "weight_kg": 82.4
}
```

**Response 201:**
```json
{
  "id": "uuid",
  "entry_date": "2025-06-08",
  "entry_time": "07:15",
  "weight_kg": 82.4
}
```

Errors: 409 if an entry already exists for that date (use PATCH to update).

#### `GET /api/weight-entries`
List entries for the session user. Supports `?from=YYYY-MM-DD&to=YYYY-MM-DD`.

**Response 200:**
```json
{
  "entries": [
    { "id": "uuid", "entry_date": "2025-06-08", "entry_time": "07:15", "weight_kg": 82.4 }
  ],
  "summary": {
    "entries_logged": 14,
    "first_date": "2025-05-25",
    "last_date": "2025-06-08"
  }
}
```

#### `PATCH /api/weight-entries/{id}`
Update `weight_kg` (or `entry_time`) for an existing entry.

#### `DELETE /api/weight-entries/{id}`
Delete an entry. Returns 204.

---

### Weight Targets

#### `POST /api/weight-targets`
Create a new target. Only one active target is allowed per user.

**Request body:**
```json
{
  "start_weight_kg": 85.0,
  "start_date": "2025-01-01",
  "target_weight_kg": 75.0,
  "target_date": "2025-09-01",
  "notes": "Summer cut goal"
}
```

**Response 201:**
```json
{ "target": { "id": "uuid", "status": "active", ... } }
```

Errors: 409 if an active target already exists.

#### `GET /api/weight-targets/active`
Returns the current active target with computed fields (`progress_pct`, `kg_to_go`,
`status_label`, `projected_end_date`, `required_pace_kg_per_week`,
`current_pace_kg_per_week`).

**Response 200:**
```json
{
  "target": {
    "id": "uuid",
    "start_weight_kg": 85.0,
    "target_weight_kg": 75.0,
    "progress_pct": 53.0,
    "kg_to_go": 4.7,
    "status_label": "on_track",
    "projected_end_date": "2025-08-21",
    "required_pace_kg_per_week": 0.38,
    "current_pace_kg_per_week": 0.42
  }
}
```

Returns `{ "target": null }` when no active target exists.

#### `GET /api/weight-targets/history`
All non-active targets for the user, newest first.

#### `PATCH /api/weight-targets/{id}`
Edit `target_weight_kg`, `target_date`, or `notes` on the active target.

#### `POST /api/weight-targets/{id}/end`
End the active target.

**Request body:**
```json
{ "status": "achieved" }
```

Valid statuses: `achieved`, `abandoned`.

---

### Weight Chart

#### `GET /api/weight-chart`
Returns data for the chart in the requested range.

Query params: `from`, `to`, `include_target=true`.

**Response 200:**
```json
{
  "actuals": [{ "date": "2025-06-08", "weight_kg": 82.4 }],
  "trend": [{ "date": "2025-06-08", "weight_kg": 82.8 }],
  "target": {
    "target_weight_kg": 75.0,
    "projected_path": [{ "date": "2025-07-01", "weight_kg": 80.2 }]
  },
  "stats": {
    "current_weight_kg": 82.4,
    "current_avg_kg": 82.8,
    "delta_7d_kg": -0.6,
    "delta_30d_kg": -1.2
  }
}
```

---

### Exports

#### `GET /api/exports/weight-entries`
CSV download of all weight entries for the user. Supports `?from=` and `?to=`.

#### `GET /api/exports/weight-targets`
CSV download of target history. Supports `?status=` filter.

---

## 7-Day Moving Average

The trend line is a 7-day rolling mean of `weight_kg` values.

**Formula:** for each date D, the moving average is the mean of all entries in
[D-6, D] (inclusive). Days with no entry are excluded from the mean — the count
is the number of non-null days, not always 7.

**Worked numeric example:**

| Date | Weight (kg) | 7-day MA |
|------|------------|---------|
| Jun 1 | 83.0 | 83.00 (1 day) |
| Jun 2 | 82.8 | 82.90 (2 days) |
| Jun 3 | — | 82.90 (still 2, no entry) |
| Jun 4 | 82.6 | 82.80 (3 days) |
| Jun 5 | 82.5 | 82.73 (4 days) |
| Jun 6 | 82.3 | 82.64 (5 days) |
| Jun 7 | 82.4 | 82.60 (6 days) |
| Jun 8 | 82.1 | 82.39 (7 days: mean of 83.0, 82.8, 82.6, 82.5, 82.3, 82.4, 82.1) |

Calculation for Jun 8: (83.0 + 82.8 + 82.6 + 82.5 + 82.3 + 82.4 + 82.1) / 7 = **82.39 kg**

---

## `status_label` Threshold Logic

The `status_label` field on an active target is computed by comparing the user's
actual pace (kg lost per week since start) to the required pace (kg remaining / weeks
remaining).

**Tolerance:** `tolerance = max(0.5, 0.05 * total_kg_to_change)`

This means for a 10 kg goal the tolerance is `max(0.5, 0.5) = 0.5 kg/wk`, and for
a 20 kg goal it is `max(0.5, 1.0) = 1.0 kg/wk`.

| Condition | `status_label` |
|---|---|
| `actual_pace >= required_pace + tolerance` | `ahead` |
| `actual_pace >= required_pace - tolerance` | `on_track` |
| `actual_pace < required_pace - tolerance` | `behind` |
| Target date already passed | `at_risk` |
| Goal weight reached | `complete` |

---

## Linear Projection Math

The projected end date is calculated by assuming the user continues at their
`current_pace_kg_per_week`.

```
days_remaining = kg_to_go / current_pace_kg_per_week * 7
projected_end_date = today + days_remaining
```

If `current_pace_kg_per_week <= 0` the projection returns `null`.

The milestone timeline uses linear interpolation between start and goal:

```
weight_at_date = start_weight + (goal_weight - start_weight) * (days_in / total_days)
```

where `days_in = date - start_date` and `total_days = target_date - start_date`.

---

## Known Limitations

- **Single active target:** Only one active target per user is supported at a time.
  To set a new target the current one must be ended (achieved or abandoned) first.
- **No unit switching:** Weights are stored and displayed in kg only. Converting to
  lb is not supported.
- **No Samsung Health auto-import:** Entries must be logged manually. Samsung Health
  integration is not planned.
- **No retroactive moving average back-fill:** The 7-day MA is computed from actual
  entries; gap days reduce the sample count rather than being interpolated.
