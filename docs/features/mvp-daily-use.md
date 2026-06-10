# MVP Daily-Use Guide

How to use the core daily-use features of perf-coach.

## How to log daily metrics

1. Open the home page. If you have not logged today's metrics, a **Log today**
   card is shown at the top of the page.
2. Tap or click **Log today**.
3. Fill in:
   - **RHR** — resting heart rate in bpm
   - **HRV** — heart rate variability in ms
   - **Sleep hours** — total sleep (0–24)
   - **Sleep quality** — 1 (poor) to 5 (excellent)
   - **Energy** — 1 to 5
   - **Mood** — 1 to 5
   - **Weight** — body weight in kg (optional)
4. Tap **Save**. The card disappears and your readiness score updates.

The day boundary is **Bangkok midnight** (Asia/Bangkok, UTC+7). A new "Log
today" prompt appears at midnight Bangkok time, not UTC midnight.

## How to log workouts

1. From the home page or training log, tap **Log workout**.
2. Choose a workout type (Run, Lift, Bike, etc.).
3. Fill in the details:
   - **Name** — optional label
   - **Date** — defaults to today
   - **Distance, duration, HR** — as applicable
   - **Zone 2 minutes** — minutes spent in Zone 2 (aerobic base) during the
     workout. This field auto-fills your Zone 2 habit progress.
4. Tap **Save**. The workout appears in the training log and the weekly habits
   widget updates.

If you have no workouts yet, the training log shows a friendly empty state with
a **Log your first workout** prompt.

## How to manage habits

Habits are tracked on the **Habits** page (`/habits`).

### Adding a habit

- If you have no habits, **starter habit buttons** are shown. Tap one to add it
  instantly (e.g. Zone 2, Strength, Mobility, Sleep 8h).
- To create a custom habit, tap **+ Add habit** and fill in the form.

### Habit fields

| Field | Description |
|-------|-------------|
| Name | Display name |
| Icon | Emoji or category icon |
| Color | Accent color for the row |
| Weekly target | Goal value per week (e.g. 150 minutes) |
| Auto-fill source | `zone2_minutes` pulls from workout data automatically |

### Logging progress

- Tap a day cell in the weekly grid to log progress manually.
- Habits with `auto_fill_source = workout.zone2_minutes` fill automatically
  when you log a workout with Zone 2 minutes.

### Archiving habits

Use the **⋯** menu on a habit row and choose **Archive**. Archived habits are
hidden from the active list but their history is preserved. You can restore
them from the **Archived** section at the bottom of the Habits page.

## How to interpret the weekly widget

The **Habits · this week** widget on the home page shows a Mon–Sun grid for
each active habit.

- **Filled cell** — logged (manually or auto-filled) for that day.
- **Empty cell** — not yet logged; future days are dimmed.
- **Today** — highlighted with a border.
- **Streak badge** — shown in the footer for habits with an active streak.

The widget uses **Bangkok Monday** as the week start. If you check the widget
near midnight, it rolls over to a new week at Bangkok midnight (00:00 UTC+7),
not UTC midnight.

### Zone 2 progress bar

Habits with a `weekly_target` show a progress bar below the day grid. For Zone
2 minutes, the bar fills as you log workouts with `zone2_minutes`. The target
is the `weekly_target` value set on the habit (e.g. 150 minutes per week).
