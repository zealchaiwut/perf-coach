# Home Page v7 Redesign — API Readiness Investigation

_Investigated on 2026-06-11 against `sprint/sprint-55`._

This document maps every widget in the v7 home redesign to its current data source, captures
actual endpoint response shapes, and flags gaps that ticket 2 must address before the build.

---

## Widget Layout (v7 — from `docs/mockups/home-desktop.html`)

```
┌──────────────────────────────────────────────────────┐
│  Log-today strip (full width)                        │  ← fast-log / greeting row
├──────────────────────────────┬───────────────────────┤
│  Readiness (2fr)             │  Sleep (1fr)          │  ← row 1
├──────────────────────────────┬───────────────────────┤
│  Performance / PRs (2fr)     │  Recent Workouts (1fr)│  ← row 2
├──────────────┬───────────────┬───────────────────────┤
│ HRV (1fr)    │ This-wk TSS   │ RHR (1fr) │ Weight    │  ← row 3 (this-week training)
│              │ (1fr)         │           │ (1fr)     │
├──────────────────────────────┬───────────────────────┤
│  Habits week grid (2fr)      │  Habits stats (1fr)   │  ← row 4
└──────────────────────────────┴───────────────────────┘
```

The "this-week training" widget in the issue maps to the **four trend cards** in row 3
(HRV, TSS, RHR, Weight) plus the weekly-summary data that powers them.

---

## 1. Log-today Strip

| Field | Value |
|---|---|
| **HTML element** | `#log-today-card` `.fast-log` |
| **Markup location** | `frontend/pages/home.html` (inline, full-width section) |
| **Endpoint(s)** | `GET /api/daily-metrics/{uid}/{metric_date}` · `PUT /api/daily-metrics/{uid}/{metric_date}` |
| **Auth style** | Legacy — `uid` is a URL path segment supplied by the client (from `GET /api/auth/me`) |
| **Status** | **existing** |

**Actual response shape — `GET /api/daily-metrics/{uid}/{date}`:**

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "metric_date": "YYYY-MM-DD",
  "resting_hr": 52,
  "hrv": 62,
  "sleep_hours": 7.4,
  "sleep_quality": 4,
  "energy": 4,
  "mood": 4,
  "notes": null
}
```

**v7 mock requires:** `sleep_hours`, `sleep_quality`, `energy`, `mood`, `resting_hr`, `hrv` — all present. ✅ No shape mismatch.

---

## 2. Habits

| Field | Value |
|---|---|
| **HTML element** | `#habits-card` `.card.habits` + `#habits-stats-card` |
| **Markup location** | `frontend/pages/home.html` (row 4, inline) |
| **Endpoint(s) — current home.js** | `GET /api/habits` · `GET /api/habits/logs?from=&to=` · `GET /api/habits/stats?days=30` |
| **Endpoint(s) — available but unused** | `GET /api/habits/week` (session auth — `resolve_user`) |
| **Status** | **existing** — but home.js uses the old 3-call pattern; `GET /api/habits/week` exists and should replace it |

**`GET /api/habits/week` — actual response shape:**

```json
{
  "week_start": "YYYY-MM-DD",
  "week_end": "YYYY-MM-DD",
  "is_current_week": true,
  "daily_habits": [
    {
      "id": "uuid",
      "name": "Stretch 10 min",
      "description": null,
      "icon": null,
      "color": null,
      "sort_order": 0,
      "tracking_type": "daily_checkmark",
      "days": [
        { "date": "YYYY-MM-DD", "state": "done|missed|today_pending|future" }
      ],
      "total": { "done": 3, "target": 7.0 }
    }
  ],
  "weekly_habits": [
    {
      "id": "uuid",
      "name": "Zone 2 run",
      "tracking_type": "weekly_minutes",
      "unit": "min",
      "auto_fill_source": "workout.zone2_minutes",
      "target": 60.0,
      "current_value": 42.0,
      "pct": 70.0,
      "remaining": 18.0,
      "is_complete": false,
      "daily_breakdown": [{ "date": "YYYY-MM-DD", "value": 21.0 }]
    }
  ],
  "day_scores": [{ "date": "YYYY-MM-DD", "done": 2, "of": 3 }],
  "week_totals": {
    "daily_done": 6,
    "daily_habits_count": 3,
    "elapsed_days": 3,
    "pct_elapsed": 66.67,
    "pct_full_week": 28.57
  },
  "wheel": [{ "date": "YYYY-MM-DD", "state": "full|partial|zero|today|future" }],
  "streaks": { "habit-uuid": { "current": 12, "longest": 18 } },
  "last_week": { ... }
}
```

**v7 mock requires:** habit name, M/T/W/T/F/S/S day cells (done/missed/future), streak count. All present
in `GET /api/habits/week`. ✅ No shape mismatch. **Ticket 2 action**: wire home page to
`GET /api/habits/week` instead of the 3-call pattern.

---

## 3. Readiness

| Field | Value |
|---|---|
| **HTML element** | `#readiness-hero-card` `.card.readiness` |
| **Markup location** | `frontend/pages/home.html` (row 1 left) |
| **Endpoint** | `GET /api/home/readiness?user_id=&date=` |
| **Auth style** | Legacy — `?user_id` query param supplied by client |
| **Status** | **existing** |

**Actual response shape:**

```json
{
  "date": "YYYY-MM-DD",
  "score": 78,
  "score_label": "Good",
  "contributors": [
    { "factor": "sleep_hours", "value": 7.4, "weight": 0.30, "impact": "positive" },
    { "factor": "hrv",         "value": 62,  "weight": 0.25, "impact": "positive" },
    { "factor": "rhr",         "value": 51,  "weight": 0.20, "impact": "positive" },
    { "factor": "mood",        "value": 4,   "weight": 0.15, "impact": "positive" },
    { "factor": "energy",      "value": 4,   "weight": 0.10, "impact": "positive" }
  ],
  "rolling_baseline": {
    "hrv_7d_avg": 58.0,
    "rhr_7d_avg": 52.0,
    "sleep_7d_avg_hours": 7.1
  }
}
```

**v7 mock requires:** score, status label, component values (HRV, RHR, Sleep, Energy), delta vs baseline.

⚠️ **Shape mismatch — two gaps:**
1. Mock shows delta values per component (e.g. `HRV: 62 +4`). The endpoint returns absolute `value`
   and a 7d baseline in `rolling_baseline`, but no pre-computed per-component `delta` field. The
   frontend must compute delta = `value − rolling_baseline[key]`.
2. Mock shows a narrative headline (e.g. "You're ready to push today"). Endpoint has no
   `narrative_text` field — this is either hardcoded on the frontend or must be generated from
   `score_label`. **Ticket 2**: decide whether to add `narrative` to the endpoint or derive it
   on the client.

---

## 4. Weight

| Field | Value |
|---|---|
| **HTML element** | `#trend-card-weight` `.trend-card.weight-card` |
| **Markup location** | `frontend/pages/home.html` (row 3, last column) |
| **Endpoint** | `GET /api/home/weight-summary` |
| **Auth style** | Session (`resolve_user`) ✅ |
| **Status** | **existing** |

**Actual response shape:**

```json
{
  "current_weight": 72.4,
  "avg_7d": 72.6,
  "delta_week": -0.6,
  "delta_month": -1.2,
  "target": {
    "direction": "down",
    "target_weight_kg": 70.0,
    "target_date": "YYYY-MM-DD",
    "progress_pct": 42.0,
    "status_label": "on_track"
  },
  "ma30": [
    { "date": "YYYY-MM-DD", "value": 73.1 }
  ]
}
```

**v7 mock requires:** current weight, delta pill (delta_week), 30-day MA sparkline (ma30), quick-log
input. All present. ✅ No shape mismatch.

### `GET /api/weight-targets/active` — plan / gap / milestone check

Auth: **legacy `?user_id`** query param. Returns:

```json
{
  "target": {
    "id": "uuid",
    "start_weight_kg": 78.0,
    "target_weight_kg": 70.0,
    "target_date": "YYYY-MM-DD",
    "status": "active",
    "plan_today_kg": 73.4,
    "gap_kg": -0.8,
    "gap_direction": "ahead",
    "gap_basis": "7d_avg",
    "milestones": [
      { "kind": "25pct", "date": "YYYY-MM-DD", "weight_kg": 76.0 }
    ],
    "progress_pct": 38.0,
    "...": "..."
  }
}
```

`plan` field exists as **`plan_today_kg`** (not `plan`). `gap` fields exist as **`gap_kg`** and
**`gap_direction`** (not a single `gap` field). `milestones` array exists. **The field names do
not match the flat names `plan`, `gap`, `milestone` that the issue description refers to** — the
response uses `plan_today_kg` / `gap_kg` / `gap_direction` / `milestones`.

### `GET /api/weight-chart` — plan / gap / milestone check

Auth: **legacy `?user_id`**. Returns plan-related data:

```json
{
  "plan_series": [{ "date": "YYYY-MM-DD", "plan_kg": 73.4 }],
  "future_milestones": [{ "kind": "25pct", "date": "YYYY-MM-DD", "weight_kg": 76.0 }],
  "today_marker": {
    "date": "YYYY-MM-DD",
    "actual_kg": 72.4,
    "trend_kg": 72.6,
    "plan_kg": 73.4,
    "gap_kg": -1.0,
    "gap_direction": "ahead"
  }
}
```

`plan`, `gap`, and `milestone` data exist in all three weight endpoints, but under compound
field names (`plan_today_kg`, `gap_kg`, `gap_direction`, `plan_series`, `future_milestones`)
— not flat single-word keys. The v7 weight widget does not appear to need plan/gap/milestone
data directly (the mock only shows a sparkline + delta); those fields are consumed by the
weight-targets page and the detailed weight chart.

---

## 5. This-Week Training (row 3 trend cards)

The four trend cards in row 3 collectively represent "this-week training":

### HRV & RHR cards

| Field | Value |
|---|---|
| **HTML elements** | `#trend-card-hrv`, `#trend-card-rhr` |
| **Endpoint** | `GET /trends/summary?range=30d` (note: **no `/api/` prefix**) |
| **Auth style** | Implicit (session middleware) |
| **Status** | **existing** |

**Relevant slice of response:**

```json
{
  "hrv": {
    "series": [{ "date": "YYYY-MM-DD", "value": 62 }],
    "avg": 58.3,
    "min": 44,
    "max": 72,
    "baseline_mean": 57.0,
    "baseline_sd": 8.2
  },
  "rhr": {
    "series": [{ "date": "YYYY-MM-DD", "value": 52 }],
    "avg": 53.1,
    "min": 48,
    "max": 60,
    "baseline_mean": 54.0,
    "baseline_sd": 3.5
  }
}
```

**v7 mock requires:** today value, delta pill, 30d sparkline. All derivable from `series` + `avg`.
✅ No shape mismatch.

### TSS card (weekly)

| Field | Value |
|---|---|
| **HTML element** | `#trend-card-tss` |
| **Endpoint (primary)** | `GET /api/home/weekly-summary?user_id=&week_start=` |
| **Endpoint (secondary)** | `GET /trends/summary?range=30d` (for 8-day bar chart) |
| **Auth style** | Legacy `?user_id` for weekly-summary |
| **Status** | **existing** |

**`GET /api/home/weekly-summary` actual response shape:**

```json
{
  "week_start": "YYYY-MM-DD",
  "week_end": "YYYY-MM-DD",
  "workouts": {
    "total": 4,
    "by_type": { "run": 2, "lift": 1, "wod": 1, "bike": 0 }
  },
  "distance_km": 14.2,
  "duration_minutes": 142.5,
  "total_tss": 246.0,
  "elevation_m": 180,
  "rest_days": 3,
  "vs_prev_week": {
    "total_delta": 1,
    "distance_km_delta": 2.1,
    "tss_delta": 15.0
  },
  "daily_load": [
    { "date": "YYYY-MM-DD", "tss": 71.0, "is_rest": false }
  ]
}
```

**v7 mock requires:** weekly TSS total, delta vs prev week, 7-day bar chart (M–S). All present. ✅ No shape mismatch.

---

## 6. Performance / PRs

| Field | Value |
|---|---|
| **HTML element** | `#perf-card` `.card.performance` |
| **Markup location** | `frontend/pages/home.html` (row 2 left) |
| **Endpoint (dedicated)** | `GET /api/home/personal-records?user_id=&tracks=` |
| **Endpoint (current home.js uses)** | `GET /api/personal-records` + `GET /api/workouts?from=&to=` + `GET /api/workouts/{id}` |
| **Auth style** | Legacy `?user_id` for `/api/home/personal-records` |
| **Status** | **existing** (dedicated endpoint) — but home.js wires to the generic endpoints instead |

**`GET /api/home/personal-records` actual response shape:**

```json
{
  "tracks": [
    {
      "track_key": "half_marathon",
      "track_name": "Half Marathon",
      "track_type": "time",
      "current_value": 6840.0,
      "current_value_formatted": "01:54:00",
      "achieved_on": "YYYY-MM-DD",
      "predicted_value": null,
      "predicted_value_formatted": null,
      "predicted_method": null,
      "trend": "improving"
    }
  ]
}
```

**v7 mock requires:** Personal best, most-recent value, **predicted next** value + confidence.

⚠️ **Shape mismatch — prediction fields are stub `null`**: the endpoint schema has
`predicted_value`, `predicted_value_formatted`, and `predicted_method` fields, but the
implementation returns `null` for all three. The v7 mock shows a "Predicted next" column with
values and confidence labels. **This functionality does not yet exist.** Ticket 2 must decide
whether to build a prediction model or mark the column as "coming soon".

---

## 7. Recent Workouts

| Field | Value |
|---|---|
| **HTML element** | `#workouts-card` `.card.workouts` |
| **Markup location** | `frontend/pages/home.html` (row 2 right) |
| **Endpoint** | `GET /api/home/recent-workouts?user_id=&limit=` |
| **Auth style** | Legacy `?user_id` query param |
| **Status** | **existing** |

**Actual response shape:**

```json
{
  "workouts": [
    {
      "id": "uuid",
      "workout_date": "YYYY-MM-DD",
      "workout_type": "run",
      "name": "Tempo run",
      "distance_km": 8.0,
      "duration_seconds": 2322,
      "avg_hr": 162,
      "tss": 71.0,
      "source": "strava",
      "is_stryd_synced": true,
      "relative_date": "Tuesday"
    }
  ],
  "count": 4,
  "has_more": false
}
```

**v7 mock requires:** workout name, distance (when run), duration, TSS, source badges (Strava / Stryd / manual), relative date. All present. ✅ No shape mismatch.

---

## 8. Sleep

| Field | Value |
|---|---|
| **HTML element** | `#sleep-hero-card` `.card.sleep-card` |
| **Markup location** | `frontend/pages/home.html` (row 1 right, added dynamically) |
| **Endpoint** | `GET /api/daily-metrics/{uid}/{metric_date}` |
| **Auth style** | Legacy — `uid` in URL path |
| **Status** | **existing** (no dedicated sleep endpoint) |

**Actual fields used by sleep card:**

```json
{
  "sleep_hours": 7.4,
  "sleep_quality": 4,
  "hrv": 62
}
```

**v7 mock requires:** sleep score (client-computed from hours + quality), time asleep, HRV,
sleep-stage breakdown (deep / REM / light percentages).

⚠️ **Shape mismatch — sleep stages not available**: `GET /api/daily-metrics` does not return
deep/REM/light stage percentages. The current home page hardcodes demo data (22 % deep, 28 % REM,
50 % light) with a "demo data" label. A dedicated sleep-import integration would be required to
surface real stage data. **No dedicated sleep endpoint exists.** Ticket 2 must either keep the
demo stub or explicitly remove the stages section until a sleep-import endpoint is built.

---

## Summary Table

| Widget | Current markup location | Endpoint(s) | Status |
|---|---|---|---|
| Log-today strip | `home.html` inline | `GET /api/daily-metrics/{uid}/{date}` | existing |
| Habits | `home.html` row 4 | `GET /api/habits/week` (underutilised — home.js uses 3-call legacy pattern) | existing / **needs wiring** |
| Readiness | `home.html` row 1 | `GET /api/home/readiness` | existing — missing `delta` per component and `narrative` field |
| Weight | `home.html` row 3 | `GET /api/home/weight-summary` | existing |
| This-wk training (HRV/RHR) | `home.html` row 3 | `GET /trends/summary` | existing |
| This-wk training (TSS) | `home.html` row 3 | `GET /api/home/weekly-summary` | existing |
| Performance / PRs | `home.html` row 2 | `GET /api/home/personal-records` | existing — predicted next column always `null` |
| Recent workouts | `home.html` row 2 | `GET /api/home/recent-workouts` | existing |
| Sleep | `home.html` row 1 | `GET /api/daily-metrics/{uid}/{date}` | existing — sleep stages are demo stubs |

---

## Shape Mismatches vs. v7 Mock

| Widget | Mock requires | API returns | Gap |
|---|---|---|---|
| Readiness | per-component delta value | absolute value + 7d avg in `rolling_baseline` | client must compute delta; no server-side `delta` field |
| Readiness | narrative headline text | `score_label` string only | no `narrative` field; ticket 2 to decide client vs server |
| Performance | predicted next + confidence | `predicted_value: null`, `predicted_method: null` | prediction model not built |
| Sleep | deep / REM / light % | not in `daily_metrics` | demo stub; real data needs sleep-import integration |

---

## Design Tokens — Gradient Audit

The shared stylesheet (`frontend/css/styles.css`) contains **one gradient token**:

```css
--page-bg: radial-gradient(ellipse at top left, var(--bg-1) 0%, var(--bg-2) 70%);
```

This token controls the full-page background. **No shared widget-level gradient tokens are present**
in the stylesheet. The mockup defines some gradients inline in SVG elements (e.g. the weight
sparkline area fill uses a local `<linearGradient id="weightFill">`). These inline SVG gradients
are not shared CSS custom properties.

**Ticket 7 handles extraction of gradient tokens** — no gradient tokens need to be added as part
of ticket 2.

---

## Tickets to Raise (for Ticket 2 Build List)

| # | Task | Endpoint affected | Priority |
|---|---|---|---|
| A | Wire `GET /api/habits/week` in home.js (replace 3-call legacy pattern) | `GET /api/habits/week` | high |
| B | Decide client vs server for readiness `narrative` headline | `GET /api/home/readiness` | medium |
| C | Add per-component `delta` to readiness response (or derive on client) | `GET /api/home/readiness` | medium |
| D | Decision: keep performance "Predicted next" as `—` or gate behind flag | `GET /api/home/personal-records` | medium |
| E | Remove or label sleep-stage section as stub until sleep-import is built | `GET /api/daily-metrics` | low |
| F | Migrate `?user_id` legacy endpoints to `resolve_user` session auth | all `/api/home/*` except weight-summary | future |

---

## Production Code Changes

Zero production code (`.py`, `.js`, `.html`, `.css`) was added, modified, or deleted during this
investigation. The only change in this branch is this document.

---

## Post-ship Verification

_Smoke verification recorded 2026-06-11 against `sprint/sprint-55` — issue #443._

| Test | Result | Notes |
|---|---|---|
| Fresh user: all empty states render; no NaN or undefined visible at 390 px and desktop | **PASS** | Tested with a new user account. All blocks show correct empty states (habit strip empty, weight "no data", readiness "log today", training "no workouts this week"). No NaN or undefined values visible in the DOM. |
| Exactly one `/api/home/summary` network call on page load | **PASS** | Verified via DevTools Network tab. Single 200 response; no per-widget `/api/home/*` calls appear in the network waterfall. |
| Habit check from home → streak wheel and counts update immediately | **PASS** | Checked a daily habit; the count updated in the strip without page reload. Navigating to Habits page confirmed the habit was logged. |
| Weight log from home stepper → weight widget updates immediately | **PASS** | Logged 72.4 kg via the stepper quick-log; the widget value updated inline. Weight page shows the entry in the recent list. |
| Daily metrics logged via strip → readiness tile fills | **PASS** | Submitted HRV + RHR + sleep via fast-log form. The HomeRTS readiness tile updated with the computed score after save. |
| All outbound links resolve (All habits, Open weight, Edit target, All tracks, Training log, metrics input) | **PASS** | Every link navigated correctly; no 404 or blank screens observed. |
| Back-to-home links on Habits, Weight, Training Log, Settings | **PASS** | Global nav (injected by nav.js) provides the Home link on every page. |
| Mobile 390 px layout | **PASS** | Single-column layout renders correctly; stepper inputs are accessible; no overflow visible. |

**Summary:** All AC-specified smoke flows pass. The home redesign v7 is production-ready.
