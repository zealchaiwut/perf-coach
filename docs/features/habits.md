# Habits feature

This document covers the habits page redesign shipped in Sprint 54 (issues #428–#435).

## Page layout

The habits page (`/habits`) is composed of:

1. **Week wheel (Card A)** — 7-segment SVG ring; one arc per day of the week.
2. **Stats cards (Card B)** — Today / Best streak / Last week tiles.
3. **Daily grid card** — tap-to-check grid for `daily_checkmark` habits, with a day-score footer row.
4. **Weekly habits card** — progress bars for `weekly_count`, `weekly_minutes`, and `weekly_quantity` habits; includes a `+ log` chip for manual habits and auto-sync badges for workout-linked ones.
5. **Archived habits** — collapsible section at the bottom of the weekly card.

---

## API: `GET /api/habits/week`

Single-batch endpoint. Returns everything the habits page needs in one round-trip.

**Request**

```
GET /api/habits/week?week_start=YYYY-MM-DD   (optional; defaults to current Bangkok week)
```

**Response**

```json
{
  "week_start": "2026-06-08",
  "week_end":   "2026-06-14",
  "is_current_week": true,

  "daily_habits": [
    {
      "id": "uuid",
      "name": "string",
      "description": "string|null",
      "icon": "ti-run|null",
      "color": "#3b82f6|null",
      "sort_order": 0,
      "tracking_type": "daily_checkmark",
      "days": [
        { "date": "2026-06-08", "state": "done|missed|today_pending|future" }
      ],
      "total": { "done": 3, "target": 7.0 }
    }
  ],

  "weekly_habits": [
    {
      "id": "uuid",
      "name": "string",
      "description": "string|null",
      "icon": "ti-run|null",
      "color": "#3b82f6|null",
      "sort_order": 0,
      "tracking_type": "weekly_count|weekly_minutes|weekly_quantity",
      "unit": "min|sessions|km|null",
      "auto_fill_source": "workout.zone2_minutes|null",
      "target": 210.0,
      "current_value": 45.0,
      "pct": 21.4,
      "remaining": 165.0,
      "is_complete": false,
      "daily_breakdown": [
        { "date": "2026-06-09", "value": 30.0 },
        { "date": "2026-06-10", "value": 15.0 }
      ]
    }
  ],

  "day_scores": [
    { "date": "2026-06-08", "done": 2, "of": 3 }
  ],

  "week_totals": {
    "daily_habits_count": 3,
    "daily_done": 9,
    "elapsed_days": 3,
    "pct_elapsed": 100.0,
    "pct_full_week": 42.9
  },

  "wheel": [
    { "state": "full|partial|zero|today|future" }
  ],

  "streaks": {
    "best": { "habit_id": "uuid", "habit_name": "string", "length": 14 },
    "per_habit": { "<habit_id>": 5 }
  },

  "last_week": {
    "done": 12,
    "possible": 21,
    "pct": 57.1
  }
}
```

The `wheel` array always has exactly 7 elements (Mon → Sun). `day_scores` also has 7 elements in the same order.

---

## Wheel color rules

Each day arc is colored based on daily-checkmark completion for that day:

| State | Color | Meaning |
|---|---|---|
| `full` | `#16a34a` (green) | All daily habits done for that day |
| `partial` | `#f59e0b` (amber) | At least one daily habit done, but not all |
| `zero` | `#9ca3af` (gray) | Elapsed day with no habits done |
| `today` | `#2563eb` (blue) | Today — regardless of completion count; represents "in progress" |
| `future` | `#d1d9e9` (light blue-gray) | Day has not yet arrived |

The wheel center percentage is `week_totals.pct_elapsed` (elapsed % — see below).

---

## Streak rules

- A streak is the longest consecutive run of days on which a given `daily_checkmark` habit was completed.
- **Today-pending does NOT break a streak.** If today's cell is `today_pending` (i.e. the habit has not been logged yet today), the streak count continues from yesterday. The streak will only break if the day passes without a log.
- The streak counter is capped at **365 days**.
- `streaks.best` returns the single longest active streak across all daily habits.
- `streaks.per_habit` maps each daily habit's id to its current streak length.

---

## Backfill window

Users may backfill missed daily habits for any date **within the current week** (Monday → Sunday in Bangkok time).

- Cells from earlier in the current week are interactive (state `missed`) — clicking them logs the habit for that date.
- Cells from **past weeks** (any date before the current week's Monday) are **read-only**. The week navigator shows past weeks in a read-only mode; no write calls fire when a past-week cell is clicked.
- Future cells (`state: future`) are always inert.

---

## Add-mode logging behavior

For `weekly_minutes`, `weekly_count`, and `weekly_quantity` habits, the `POST /api/habits/{id}/log` endpoint accepts a `mode` parameter:

| Mode | Behavior |
|---|---|
| `add` (default) | Increments the existing log value for the current day: `new_value = old_value + submitted_value` |
| `set` | Replaces the existing log value: `new_value = submitted_value` |
| n/a for `daily_checkmark` | Mode is ignored; value is always 1 (one log = one check) |

The response includes `week_current_value` — the total accumulated value for the habit in the current week after the mutation. The frontend updates the progress bar in-place from this field without a full page refetch.

---

## Pace formula for weekly habits

The pace sub-line beneath each weekly habit bar shows whether the user is on pace to reach their weekly target by Sunday.

**On pace** if: `current_value / target >= elapsed_days / 7`

Where `elapsed_days` is the number of days that have started in the current week (1–7, Bangkok time).

If `elapsed_days == 0` (i.e. the week hasn't started yet), the habit is always considered on pace.

If behind pace: the "to go" amount is `remaining = target - current_value`.

---

## Both-percentages decision

The habits page derives two percentages from the week data:

| Percentage | Field | Used for |
|---|---|---|
| **Elapsed %** | `week_totals.pct_elapsed` | **Wheel center** — represents progress through elapsed days only. Calculated as `daily_done_for_elapsed_days / (daily_habits_count × elapsed_days)`. Reaches 100 % when every elapsed day is fully checked. |
| **Full-week %** | `week_totals.pct_full_week` | **Grid day-score footer** and **Stats last-week tile** — represents progress as a fraction of the entire 7-day week. Calculated as `total_daily_done / (daily_habits_count × 7)`. Always ≤ 100 % and grows as the week progresses. |

Using elapsed % for the wheel means a user who checks every habit every day will see 100 % in the wheel center, even if it's only Wednesday. Using full-week % for the grid total keeps the score honest across the full seven days.

---

## Performance contract

The habits page makes exactly **one** `GET /api/habits/week` call on initial load (inside the `Promise.all` in `loadAndRender`). There are no per-habit `/api/habits/{id}/progress` calls; all progress data is embedded in the `weekly_habits` array of the batch response.

After a daily-grid cell mutation (check or uncheck), a single debounced `GET /api/habits/week` refetch fires 300 ms later to refresh the wheel, stats, and grid totals. The weekly habit log chip updates the bar in-place from the `week_current_value` field in the log response — no additional week fetch needed.
