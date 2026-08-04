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

## Plan-vs-Actual Tracking (Redesign v6)

The weight page redesign (sprint 53) introduced plan-vs-actual tracking: a daily
expected weight (`plan_today_kg`), a gap analysis showing how far ahead/behind the
user is, a milestone chart, and a coach strip.

### `plan_at` Formula

`plan_at(target, date)` linearly interpolates between `start_weight_kg` on
`start_date` and `target_weight_kg` on `target_date`.

```
t = (date - start_date).days / (target_date - start_date).days
plan_at = start_weight_kg + (target_weight_kg - start_weight_kg) * t
```

The result is clamped: if `date <= start_date` it returns `start_weight_kg`; if
`date >= target_date` it returns `target_weight_kg`.

**Worked numeric example:**

- `start_weight_kg = 85.0 kg` on `2025-01-01`
- `target_weight_kg = 75.0 kg` on `2025-09-01` (= 243 days later)
- Today = `2025-04-01` (= 90 days in)

```
t = 90 / 243 = 0.3704
plan_at = 85.0 + (75.0 - 85.0) × 0.3704
        = 85.0 + (-10.0) × 0.3704
        = 85.0 - 3.7
        = 81.3 kg
```

So on 2025-04-01 the plan expects the user to be at **81.3 kg**.

---

### Gap Basis Selection

To compare the user's actual progress against the plan, `compute_gap` selects a
"current basis" weight by delegating to `_weight_rollup` — the same rule used
by every other "current weight" figure in the app (the Home/Weight-page
headline stats, the Hermes weight brief). This is a deliberately conservative
rule: the basis never PREFERS the single most recent entry over other
available context. Priority order:

1. **`avg_7d`** — if the user has ≥ 2 entries in the last 7 days, use their
   rolling average over those entries.
2. **`avg_wide`** — if fewer than 2 entries exist in the last 7 days but ≥ 2
   entries exist somewhere in the wider lookback window (55 days), average
   over all of them instead — never just the single latest entry, even when
   only one exists in the trailing 7 days but more history is available
   further back.
3. **`single_entry`** — if exactly one entry exists in the entire 55-day
   lookback (the trailing 7 days included), the basis is that entry's raw
   value — there is no other data to average against, so the rule cannot
   (and does not pretend to) do anything else. `basis` reports this
   honestly as `"single_entry"` rather than mislabeling it `"avg_wide"`,
   which would claim an average that never happened.
4. **`no_data`** — if no entry exists within the 55-day lookback, the gap
   cannot be computed and `gap_direction` is set to `"no_data"`.

The `basis` field in the API response reflects which rule was applied
(`"avg_7d"`, `"avg_wide"`, `"single_entry"`, or `null` for no_data). This is
an API-visible contract change: any consumer that special-cased the old
`"latest_entry"` string, or that only expected two non-null values, needs to
handle `"single_entry"` too — see `docs/pre-production-review-status.md` §3.3.

(Prior to the "current weight" unification, `compute_gap` had its own
3-in-7d-else-latest-single-entry-within-14d rule, and `basis` could report
`"latest_entry"`. That rule disagreed with `_weight_rollup`'s on identical
data and has been retired. Note also that the wider lookback is 55 days, not
the old rule's 14-day cap — on sparse data the wide-lookback average can now
reach materially further back than before.)

---

### `gap_direction` Thresholds

`gap_kg = current_basis_kg - plan_today_kg`

A positive `gap_kg` means the user is heavier than plan (bad for a weight-loss
goal); negative means lighter (good for weight loss, bad for a weight-gain goal).

The `gap_direction` field is determined by the **±0.2 kg on_plan band**:

| Condition | `gap_direction` |
|---|---|
| `abs(gap_kg) <= 0.2 kg` | `on_plan` |
| weight-loss goal AND `gap_kg > 0.2` | `behind` (heavier than plan) |
| weight-loss goal AND `gap_kg < -0.2` | `ahead` (lighter than plan) |
| weight-gain goal AND `gap_kg < -0.2` | `behind` (lighter than plan) |
| weight-gain goal AND `gap_kg > 0.2` | `ahead` (heavier than plan) |
| No qualifying entries | `no_data` |

---

### Milestone Generation

Milestones mark key waypoints on the chart between today and the goal date.
`generate_milestones` produces up to 4 stones: **today**, up to 2 intermediates,
and the **goal**.

**Placement:** intermediate stones are placed at 1/3 and 2/3 of remaining days:

```
remaining_days = (target_date - today).days
d1 = today + remaining_days // 3
d2 = today + remaining_days * 2 // 3
```

**Month-start rounding:** each intermediate date is snapped to the nearest 1st of
month (`_snap_to_month_start`). If `d1` is closer to the 1st of the current month
it snaps back; otherwise it snaps to the 1st of the next month.

**Deduplication:** if two intermediate stones snap to the same date, or a stone
collides with today or the goal date, the duplicate is dropped. Each stone appears
at most once.

---

### Coach Strip

The coach strip is a single contextual message below the hero cards that reacts to
the user's daily log status and goal direction.

| State | Trigger | Copy |
|---|---|---|
| **No entry** | `logged_today = false` | "😴 No entry yet today — log your weight to wake me up" |
| **On pace** | Logged today; delta toward goal or < 0.05 kg change | "🎉 You did well — on pace this week" |
| **Off pace (loss goal)** | Logged today; moved away from goal | "💪 Up a little — new day, keep going" |
| **Off pace (gain goal)** | Logged today; moved away from goal | "💪 Down a little — new day, keep going" |

The strip background is grey (no entry), green (on pace), or amber (off pace).

---

### Chart Implementation

The weight chart is rendered as a **custom SVG** element, built entirely in
`frontend/js/weight-chart.js`. **Chart.js was dropped for this page** — the CDN
script (`chart.js@4.4.0`) is not loaded. The SVG approach was chosen to support
the split-zone layout (historical actuals zone / future milestones zone with a
visual break), custom gap shading between plan and actual series, and milestone
annotation pins — none of which were straightforward with Chart.js without heavy
custom plugins.

The `WeightChart.render(data, range)` function manages the entire SVG DOM tree
directly, replacing it on each re-render.

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

---

## Data Maintenance

### Purging Low-Weight / Historical Entries

The script `scripts/purge_weight_entries.py` removes weight entries that match both
a date ceiling and a weight ceiling. Use this to clean up erroneous entries or
outliers that skew trend stats.

**Usage:**

```bash
# Preview which rows would be deleted (no changes made)
python scripts/purge_weight_entries.py \
  --before 2025-01-01 \
  --below 79 \
  --dry-run

# Delete matching rows (will prompt for confirmation before any deletion)
python scripts/purge_weight_entries.py \
  --before 2025-01-01 \
  --below 79
```

**Flags:**

| Flag | Description |
|---|---|
| `--before DATE` | Delete entries with `entry_date < DATE` (ISO YYYY-MM-DD) |
| `--below KG` | Delete entries with `weight_kg < KG` |
| `--dry-run` | Print count of affected rows without modifying data |

Both `--before` and `--below` are required. Running without `--dry-run` shows the
affected row count and prompts `Confirm deletion? [y/N]` before proceeding.

**Environment:** the script reads `DATABASE_URL` (or `DATABASE_URL_UAT` /
`DATABASE_URL_PRD`) and `ENVIRONMENT` from the environment, matching the same
detection logic as `backend/db.py`.
