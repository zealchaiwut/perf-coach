# Home Page Widget Spec

Audited from `frontend/pages/home.html` + `frontend/js/home.js`.
This document is the contract for home page backend work; subsequent sprint tickets reference it.

---

## Backend Route Search Results

Searched `backend/main.py` for routes matching the following patterns:

| Pattern | Route(s) found | Status |
|---|---|---|
| `home` | `GET /api/home/weight-summary` | EXISTS |
| `dashboard` | _(none)_ | — |
| `readiness` | `GET /api/readiness/today`, `GET /api/readiness`, `POST /api/readiness/compute` | EXISTS |
| `recent-workouts` | _(no dedicated route — served by `/api/workouts`)_ | — |
| `weekly-summary` | _(no dedicated route — served by `/trends/summary`)_ | — |
| `pr` | `GET /api/personal-records` | EXISTS |

---

## Widget Inventory

Page layout (desktop):

```
┌─────────────────────────────────────────────────────┐
│  Greeting (h1 + date subtitle)                       │  ← above row-1
├──────────────────────────────┬──────────────────────┤
│  Readiness Hero Card (2fr)   │  Sleep Card (1fr)    │  ← row-1
├──────────────────────────────┬──────────────────────┤
│  Performance Card (2fr)      │  Recent Workouts(1fr)│  ← row-2
├──────────────────────────────────────────────────────┤
│  Log Today Card (full width)                         │  ← row-log
├───────────┬───────────┬───────────┬──────────────────┤
│ HRV (1fr) │  TSS (1fr)│ RHR (1fr) │ Weight (1fr)    │  ← row-3
├──────────────────────────────┬──────────────────────┤
│  Habits Week Grid (2fr)      │  Habits Stats (1fr)  │  ← row-4
└──────────────────────────────┴──────────────────────┘
```

---

### 1. Greeting

**Layout position:** Above row-1, full width  
**HTML element:** `#greeting-text` (h1) + `#greeting-date` (p)  
**Current data source:** `hardcoded` (JS computes from `new Date()`)  
**Endpoint:** none — NEEDS BUILDING if personalised greeting is ever required  

**Required JSON:** N/A (greeting name fetched from `/api/auth/me` — see Login section)

---

### 2. Readiness Hero Card

**Layout position:** Row 1, left (2fr)  
**HTML element:** `#readiness-hero-card` (`.card.readiness`)  
**Current data source:** `live API`

**Endpoints used:**

| Endpoint | Status |
|---|---|
| `GET /api/readiness/today` | EXISTS |
| `POST /api/readiness/compute` | EXISTS |
| `GET /api/readiness?from=YYYY-MM-DD&to=YYYY-MM-DD` | EXISTS |
| `GET /api/daily-metrics?from=YYYY-MM-DD&to=YYYY-MM-DD` | EXISTS |

**Required JSON — `GET /api/readiness/today`:**

```json
{
  "date": "YYYY-MM-DD",
  "score": 0.0,
  "hrv_contribution": 0.0,
  "rhr_contribution": 0.0,
  "sleep_contribution": 0.0,
  "energy_contribution": 0.0,
  "missing_data": {
    "hrv": false,
    "rhr": false,
    "sleep": false,
    "energy": false
  }
}
```

Returns **404** when no readiness row exists for today (card shows compute CTA).

**Required JSON — `GET /api/readiness` (range):**

```json
[
  { "date": "YYYY-MM-DD", "score": 78.5 },
  null
]
```

One entry per day in `[from, to]`; `null` where no record exists.

---

### 3. Sleep Card

**Layout position:** Row 1, right (1fr)  
**HTML element:** `#sleep-hero-card` (`.card.sleep-card`)  
**Current data source:** `live API` for hours/quality/HRV; sleep stage breakdown is `stub` (hardcoded demo percentages: deep 22 %, REM 28 %, light 50 %)

**Endpoint used:**

| Endpoint | Status |
|---|---|
| `GET /api/daily-metrics/{uid}/{date}` | EXISTS |

**Required JSON:**

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "metric_date": "YYYY-MM-DD",
  "sleep_hours": 7.4,
  "sleep_quality": 4,
  "hrv": 62,
  "resting_hr": 52,
  "energy": 4,
  "mood": 4,
  "notes": null
}
```

Sleep stages (deep/REM/light) are hardcoded demo values — a future endpoint would supply them via a sleep-import integration.

---

### 4. Performance Card

**Layout position:** Row 2, left (2fr)  
**HTML element:** `#perf-card` (`.card`)  
**Current data source:** `live API` for PR and recent values; "Predicted next" column is `stub` (hardcoded `—`)

**Endpoints used:**

| Endpoint | Status |
|---|---|
| `GET /api/personal-records` | EXISTS |
| `GET /api/workouts?from=YYYY-MM-DD&to=YYYY-MM-DD` | EXISTS |
| `GET /api/workouts/{workout_id}` | EXISTS |

**Required JSON — `GET /api/personal-records`:**

```json
[
  {
    "id": "uuid",
    "user_id": "uuid",
    "track_key": "half_marathon",
    "track_name": "Half Marathon",
    "track_type": "time",
    "value_numeric": 5940.0,
    "achieved_on": "YYYY-MM-DD",
    "source": null
  }
]
```

`track_type` is `"time"` (value in seconds) or `"weight"` (value in kg).  
The home page uses hardcoded `TRACK_CONFIGS` keyed by `track_key`; only configured keys are displayed.

---

### 5. Recent Workouts Card

**Layout position:** Row 2, right (1fr)  
**HTML element:** `#workouts-card` (`.card.workouts`)  
**Current data source:** `live API`

**Endpoint used:**

| Endpoint | Status |
|---|---|
| `GET /api/workouts?from=YYYY-MM-DD&to=YYYY-MM-DD` | EXISTS |

The widget fetches the last 14 days and displays up to 4 most-recent workouts.

**Required JSON (list item):**

```json
{
  "id": "uuid",
  "workout_date": "YYYY-MM-DD",
  "name": "Morning Run",
  "workout_type": "run",
  "distance_km": 10.2,
  "duration_seconds": 3240,
  "tss": 55.0,
  "source": "strava",
  "strava_activity_url": "https://www.strava.com/activities/..."
}
```

No dedicated `/api/home/recent-workouts` endpoint exists; the generic workouts list is used. NEEDS BUILDING as a home-specific endpoint is a future optimisation only.

---

### 6. Log Today Card

**Layout position:** Row log, full width  
**HTML element:** `#log-today-card` (`.card.log-today`)  
**Current data source:** `live API`

**Endpoints used:**

| Endpoint | Status |
|---|---|
| `GET /api/daily-metrics/{uid}/{date}` | EXISTS |
| `PUT /api/daily-metrics/{uid}/{date}` | EXISTS |

**Required JSON — request body for `PUT`:**

```json
{
  "sleep_hours": 7.5,
  "sleep_quality": 4,
  "energy": 3,
  "mood": 4,
  "resting_hr": 52,
  "hrv": 60
}
```

`resting_hr` and `hrv` are optional. `sleep_hours` 0–24; `sleep_quality`, `energy`, `mood` are integers 1–5.

---

### 7. HRV Trend Card

**Layout position:** Row 3, card 1 (1fr)  
**HTML element:** `#trend-card-hrv` (`.trend-card`)  
**Current data source:** `live API`

**Endpoint used:**

| Endpoint | Status |
|---|---|
| `GET /trends/summary?range=30d` | EXISTS |

Note: this endpoint has **no `/api/` prefix** (served at `/trends/summary`).

**Required JSON (relevant slice):**

```json
{
  "hrv": {
    "series": [{ "date": "YYYY-MM-DD", "value": 62 }],
    "avg": 58.3,
    "min": 44,
    "max": 72,
    "baseline_mean": 57.0,
    "baseline_sd": 8.2,
    "is_approximate": false
  }
}
```

---

### 8. Weekly TSS Trend Card

**Layout position:** Row 3, card 2 (1fr)  
**HTML element:** `#trend-card-tss` (`.trend-card`)  
**Current data source:** `live API`

**Endpoint used:**

| Endpoint | Status |
|---|---|
| `GET /trends/summary?range=30d` | EXISTS |

Shared fetch with HRV and RHR cards.

**Required JSON (relevant slice):**

```json
{
  "tss": {
    "series": [{ "date": "YYYY-MM-DD", "value": 45.0 }],
    "avg": 38.2,
    "total": 267.4
  }
}
```

The widget slices `series[-8:]` for the last 8 days and computes the week total.

---

### 9. RHR Trend Card

**Layout position:** Row 3, card 3 (1fr)  
**HTML element:** `#trend-card-rhr` (`.trend-card`)  
**Current data source:** `live API`

**Endpoint used:**

| Endpoint | Status |
|---|---|
| `GET /trends/summary?range=30d` | EXISTS |

**Required JSON (relevant slice):**

```json
{
  "rhr": {
    "series": [{ "date": "YYYY-MM-DD", "value": 52 }],
    "avg": 53.1,
    "min": 48,
    "max": 60,
    "baseline_mean": 54.0,
    "baseline_sd": 3.5,
    "is_approximate": false
  }
}
```

---

### 10. Weight Widget

**Layout position:** Row 3, card 4 (1fr)  
**HTML element:** `#trend-card-weight` (`.trend-card`)  
**Current data source:** `live API`

**Endpoints used:**

| Endpoint | Status |
|---|---|
| `GET /api/home/weight-summary` | EXISTS |
| `POST /api/weight` | EXISTS |

`POST /api/weight` is used by the quick-save button embedded in the widget.

**Required JSON — `GET /api/home/weight-summary`:**

```json
{
  "current_weight": 78.4,
  "avg_7d": 78.6,
  "delta_week": -0.4,
  "delta_month": -1.2,
  "ma30": [
    { "date": "YYYY-MM-DD", "value": 79.1 }
  ],
  "target": {
    "progress_pct": 42.0,
    "status_label": "on_track",
    "direction": "down"
  }
}
```

`target` is `null` when no active weight target exists.  
`status_label` values: `"on_track"`, `"behind"`, `"ahead"`.

---

### 11. Habits Week Grid

**Layout position:** Row 4, left (2fr)  
**HTML element:** `#habits-card` (`.card.habits`)  
**Current data source:** `live API`

**Endpoints used:**

| Endpoint | Status |
|---|---|
| `GET /api/habits` | EXISTS |
| `GET /api/habits/logs?from=YYYY-MM-DD&to=YYYY-MM-DD` | EXISTS |
| `GET /api/habits/stats?habit_id=UUID&days=30` | EXISTS |
| `POST /api/habits/logs` | EXISTS |
| `DELETE /api/habits/logs/{log_id}` | EXISTS |

**Required JSON — `GET /api/habits`:**

```json
[{ "id": "uuid", "name": "Morning run", "display_order": 0 }]
```

**Required JSON — `GET /api/habits/logs`:**

```json
[{ "id": "uuid", "habit_id": "uuid", "logged_date": "YYYY-MM-DD" }]
```

**Required JSON — `GET /api/habits/stats` (single habit):**

```json
{
  "streak": 5,
  "completion_rate": 0.7143,
  "days_completed": 5,
  "days_total": 7
}
```

---

### 12. Habits Stats Graph

**Layout position:** Row 4, right (1fr)  
**HTML element:** `#habits-stats-card` (`.card.habits-graph`)  
**Current data source:** `live API`

**Endpoints used:**

| Endpoint | Status |
|---|---|
| `GET /api/habits` | EXISTS |
| `GET /api/habits/logs?from=YYYY-MM-DD&to=YYYY-MM-DD` | EXISTS |
| `GET /api/habits/stats?days=30` | EXISTS |

**Required JSON — `GET /api/habits/stats` (list mode, no `habit_id`):**

```json
[
  {
    "habit_id": "uuid",
    "habit_name": "Morning run",
    "streak": 5,
    "completion_rate": 0.7143,
    "days_completed": 21,
    "days_total": 30
  }
]
```

---

## Shared / Auth Endpoints Used on Page Load

| Endpoint | Used by | Status |
|---|---|---|
| `GET /api/auth/me` | All widgets (resolves `userId`, name) | EXISTS |

---

## Stub / Hardcoded Data Summary

| Widget | Stubbed field | Detail |
|---|---|---|
| Sleep Card | Stage breakdown (deep/REM/light %) | Hardcoded demo: 22 % / 28 % / 50 % |
| Performance Card | "Predicted next" column | Hardcoded `—`; no prediction model built |
| Greeting | Text content | JS-computed; name pulled from `/api/auth/me` |

---

## Sprint Build Plan

All endpoints currently consumed by the home page **exist**. The following gaps are identified for future sprint work:

| # | Missing capability | Suggested endpoint | Notes |
|---|---|---|---|
| 1 | Performance prediction model | `GET /api/home/performance-prediction` | NEEDS BUILDING — "Predicted next" column currently hardcoded `—` in Performance card |
| 2 | Sleep stage breakdown | `GET /api/home/sleep-summary` or extend `/api/daily-metrics` | NEEDS BUILDING — deep/REM/light percentages are demo stubs; requires sleep-import data |
| 3 | Home-optimised workout summary | `GET /api/home/recent-workouts` | NEEDS BUILDING (optional) — current widget reuses generic `/api/workouts`; a purpose-built endpoint could reduce payload |
| 4 | Weekly training summary | `GET /api/home/weekly-summary` | NEEDS BUILDING (optional) — no dedicated weekly summary endpoint; `trends/summary` covers it but is general-purpose |

No `dashboard`-prefixed routes exist or are needed at this time.

---

## Final State (post sprint-47)

All 5 primary home widgets are wired to `/api/home/*` endpoints and fire simultaneously via `Promise.all` on page load. A centralized `_homeFetch` helper in `home.js` handles fetch, JSON parsing, and error normalization for every widget.

| # | Widget | Endpoint | Status |
|---|--------|----------|--------|
| 1 | Recent Workouts | `GET /api/home/recent-workouts` | **LIVE** — wired sprint-47 (#355) |
| 2 | Weight | `GET /api/home/weight-summary` | **LIVE** — wired sprint-47 (#353) |
| 3 | Personal Records | `GET /api/home/personal-records` | **LIVE** — wired sprint-47 (#354) |
| 4 | Readiness | `GET /api/home/readiness` | **LIVE** — wired sprint-47 (#354) |
| 5 | Weekly Summary | `GET /api/home/weekly-summary` | **LIVE** — wired sprint-47 (#355) |

**Parallel fetch:** `Promise.all([loadReadinessCard, loadPerformanceCard, loadRecentWorkoutsCard, loadWeeklySummaryCard, loadWeightWidget])` — all 5 fetches start simultaneously, verified via DevTools Network tab.

**Independent failure:** each widget catches its own errors and renders an error state; a failing widget does not affect the other 4.

**Weekly Summary widget details:**
- Location: `#row-5` (full-width card below habits row)
- Shows: workout count, type breakdown with icons, total distance / duration / TSS, rest day count
- Delta pills: `vs_prev_week` totals, distance, TSS — green for positive, red for negative, neutral for zero
- 7-day TSS bar chart: pure SVG, Mon–Sun labels, rest days gray (`var(--chip-bg)`), today in accent color (`var(--accent)`)
