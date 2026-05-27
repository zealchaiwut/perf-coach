# Timezone Convention

Perf Coach uses the user's local date for all daily reset logic. Records are stored as DATE (date-only, no timezone), interpreted as the user's local date at submission time.

## Rules

- All `logged_date` / `recorded_date` values are derived from the browser's local clock using local date parts (`getFullYear()`, `getMonth()`, `getDate()`), never from `toISOString()` which returns UTC.
- Streak and gap detection uses the stored `logged_date` values directly; no timezone translation is applied server-side.
- The habits page auto-refreshes checkbox state when the local date rolls over (detected via `visibilitychange` events and a `setTimeout` scheduled for the next local midnight).

## Why not UTC?

`new Date().toISOString()` returns the UTC date, which can differ from the user's local date by up to ±14 hours. A log submitted at 11:55 PM local time would be bucketed into tomorrow's UTC date in many timezones west of UTC, breaking streaks and "today" checks.

## Out of scope

- Multi-timezone support for shared users
- Configurable "day starts at" offset
- Backfilling historical logs submitted under a different convention
