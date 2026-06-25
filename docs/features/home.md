# Home Page — Feature Reference

The home page delivers a complete daily snapshot using a **single API call**. All data blocks are populated from one aggregator endpoint, minimising round-trips and ensuring consistent Bangkok-time day boundaries across every widget.

---

## Single-Call Load Strategy

On page load, `home.js` calls:

```
GET /api/home/summary?user_id={uid}
```

This one request returns all seven data blocks. Each block is computed independently on the server; a failure in any block returns `null` for that block without affecting the others. The frontend distributes the response to the relevant renderers:

- `HomeStripHabits.render(summary)` — habits strip and log-today row
- `HomeRTS.render(summary)` — readiness tile, training card, sleep card
- `_renderHomeWeightWidget(summary.weight, userId)` — weight widget with stepper quick-log
- `loadPerformanceCard(userId)` — performance / PR card
- `loadRecentWorkoutsCard(userId, summary.recent_workouts)` — recent workouts card

**Rationale:** A single call eliminates waterfall loading, reduces server connections, and makes the home page's time-to-interactive predictable regardless of how many blocks are rendered.

---

## API Contract: GET /api/home/summary

### Request

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | UUID string | Yes | The authenticated user's ID. Supplied from `GET /api/auth/me`. |

**Auth:** Session cookie (`resolve_user`). Returns 404 if `user_id` is absent or unknown.

**Bangkok-time boundary:** The server derives `today_bkk` and `week_start` from `datetime.now(ZoneInfo("Asia/Bangkok"))`. All date ranges and "today" checks throughout the seven blocks use this Bangkok date, not UTC.

### Response shape

```json
{
  "habits":          { ... } | null,
  "weight":          { ... } | null,
  "readiness":       { ... } | null,
  "training_week":   { ... } | null,
  "performance":     { ... } | null,
  "recent_workouts": { ... } | null,
  "sleep":           { ... } | null
}
```

A `null` value for any block means the block failed or had no data; the page renders that block in its empty/error state.

---

## Rendered Blocks

### habits

**Container:** `#home-habits-widget`  
**JS module:** `home-strip-habits.js` (`HomeStripHabits.render`)  
**Data source:** `GET /api/habits/week` (via `_build_habits_block`)

Shape:
```json
{
  "wheel": [{ "date": "YYYY-MM-DD", "state": "full|partial|zero|today|future" }],
  "pct_elapsed": 75.0,
  "daily_habits": [{
    "id": "uuid",
    "name": "Sleep 8h",
    "icon": "ti-moon",
    "color": null,
    "today_checked": false,
    "week_count": 3
  }],
  "week_totals": { "daily_done": 3, "daily_habits_count": 3, "pct_elapsed": 75.0 },
  "top_habits": [],
  "remaining_count": 0
}
```

**Degradation (null block):** Shows "Add habits to track your week" empty state with link to /habits.

---

### weight

**Container:** `#home-weight-widget`  
**JS renderer:** `_renderHomeWeightWidget` in `home.js`  
**Data source:** weight entries + active target (via `_build_weight_block`)

Shape:
```json
{
  "current_kg": 72.4,
  "seven_day_avg": 72.6,
  "weekly_rate_kg": -0.2,
  "sparkline": [{ "date": "YYYY-MM-DD", "kg": 72.8 }],
  "plan_sparkline": null,
  "gap_direction": "below",
  "gap_kg": -0.4,
  "last_entry_kg": 72.4,
  "logged_today": false,
  "target_kg": 70.0,
  "target_date": "YYYY-MM-DD",
  "progress_pct": 42.0
}
```

**Degradation (null block):** Shows "No weight logged yet" with link to /weight.

---

### readiness

**Container:** rendered inside `#home-top-row-right` by `HomeRTS.render`  
**JS module:** `home-readiness-training-sleep.js`  
**Data source:** `daily_metrics` for today + 7-day rolling baseline

Shape:
```json
{
  "score": 78,
  "score_label": "Good",
  "contributors": [{
    "factor": "hrv",
    "value": 62,
    "weight": 0.25,
    "impact": "positive"
  }],
  "rolling_baseline": {
    "hrv_7d_avg": 58.0,
    "rhr_7d_avg": 52.0,
    "sleep_7d_avg_hours": 7.1
  }
}
```

Per-component delta is computed on the client: `delta = value − rolling_baseline[key]`.  
Score narrative ("You're ready to push today") is derived client-side from `score_label`.

**Degradation (null block or score: null):** Shows "Log today's metrics →" link to the fast-log section.

---

### training_week

**Container:** `#home-training-card`  
**JS module:** `home-readiness-training-sleep.js` (`HomeRTS.render`)  
**Data source:** workouts for current Bangkok week (via `_build_training_week_block`)

Shape:
```json
{
  "total_workouts": 4,
  "total_tss": 246.0,
  "distance_km": 14.2,
  "duration_minutes": 142.5,
  "elevation_m": 180,
  "rest_days": 3,
  "daily_load": [{ "date": "YYYY-MM-DD", "tss": 71.0, "is_rest": false }],
  "vs_prev_week": { "tss_delta": 15.0 }
}
```

`daily_load` always contains exactly 7 entries (Mon–Sun of the current Bangkok week).

**Degradation (null block):** Shows "No workouts this week" with link to /log.

---

### performance

**Container:** `#home-perf-container`  
**JS function:** `loadPerformanceCard` in `home.js`  
**Data source:** `GET /api/personal-records` + recent workout details

Lists configured PR tracks (half_marathon, 10k, squat_1rm, etc.) with personal best, most-recent value, and predicted next (currently always `null`).

**Degradation (no PRs):** Shows "No personal records yet — add your first PR in Settings".

---

### recent_workouts

**Container:** `#home-workouts-container`  
**JS function:** `loadRecentWorkoutsCard` in `home.js`  
**Data source:** last 4 workouts via `_build_recent_workouts_block`

Shape:
```json
{
  "workouts": [{
    "id": "uuid",
    "workout_date": "YYYY-MM-DD",
    "workout_type": "run",
    "name": "Tempo run",
    "distance_km": 8.0,
    "duration_seconds": 2322,
    "avg_hr": 162,
    "tss": 71.0,
    "source": "strava"
  }],
  "count": 4,
  "has_more": false
}
```

**Degradation (null block or empty workouts):** Shows "No workouts in the last 14 days — log one".

---

### sleep

**Container:** `#home-sleep-card`  
**JS module:** `home-readiness-training-sleep.js` (`HomeRTS.render`)  
**Data source:** `daily_metrics` for today (sleep_hours, sleep_quality, hrv)

Shape:
```json
{
  "sleep_hours": 7.4,
  "sleep_quality": 4,
  "hrv": 62
}
```

Sleep score (0–100) is computed client-side:
```
clip(((sleep_hours - 4) / 5) * 60 + ((sleep_quality - 1) / 4) * 40, 0, 100)
```

Sleep stages (deep/REM/light) are not available from `daily_metrics`; that section requires a future sleep-import integration.

**Degradation (null block):** Shows "Log today's metrics" link.

---

## Inline vs Link-Out Actions

| Action | Type | Target |
|--------|------|--------|
| Habit check / uncheck | **Inline** — `POST /api/habits/{id}/log` or `DELETE /api/habits/{id}/log` | Same page, streak wheel updates immediately |
| Weight stepper log | **Inline** — `POST /api/weight-entries` | Same page, widget value updates immediately |
| Log today's metrics | **Inline** — expands `#fast-log-section` form | Form submits `PUT /api/daily-metrics/{uid}/{date}` |
| All habits | **Link-out** → `/habits` | Habits management page |
| Open weight | **Link-out** → `/weight` | Full weight page |
| Edit target | **Link-out** → `/weight/targets` | Weight target edit page |
| All tracks | **Link-out** → `/settings#personal-records` | PR track settings |
| Training log | **Link-out** → `/log` | Full training log |

---

## Bangkok-Time (UTC+7) Day Boundary

All "today" checks and week boundaries on the server use:

```python
from zoneinfo import ZoneInfo
BKK = ZoneInfo("Asia/Bangkok")
today_bkk = datetime.now(BKK).date()
```

The Bangkok week starts on Monday. `_week_start_bangkok(today_bkk)` returns the most recent Monday in Bangkok time. This ensures midnight transitions happen at 07:00 UTC, matching the user's local experience.

The JavaScript side mirrors this with:
```js
function bangkokTodayStr() {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
}
```

---

## Error Shape

Any block that fails returns `null` in the summary response. The client-side renderers treat a `null` block as an empty state — they never throw. Errors are logged server-side via `_HOME_SUMMARY_LOG.error(...)` with the user ID and exception message.

The HTTP status of `GET /api/home/summary` is always `200` as long as authentication succeeds; individual block failures are absorbed into `null` values within the response body.
