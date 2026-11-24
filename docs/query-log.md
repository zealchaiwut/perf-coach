# Query-count logging (issues #1912, #1923, #1935)

Lightweight per-request SQL instrumentation for Log, Plan, and Performance endpoints:

- `GET /api/training-log`
- `GET /api/weekly-rollup`
- `GET /api/training/month`
- `GET /api/plan/revamp-week`
- `GET /api/plan/revamp-road-chart`
- `GET /api/plan/week-bundle`
- `GET /api/performance/radar`
- `GET /api/performance/score-cards`
- `GET /api/performance/hero`
- `GET /api/performance/a-race-readiness`
- `GET /api/performance/projection`
- `GET /api/performance/races`
- `GET /api/performance/focus`
- `GET /api/performance/coach-block`
- `GET /api/performance/mobility-tests`
- `GET /api/performance/anchor-lifts`

## Enable

Off by default (no SQLAlchemy listener registered). To turn on:

```bash
PERF_QUERY_LOG=1
```

Set that in the UAT process environment (local `.env`, or the UAT Render service env vars) and restart uvicorn.

## What to look for

Each instrumented request emits one structured log line from logger `backend.query_log`:

| Field | Meaning |
|---|---|
| path | Endpoint path |
| user_id | Session user |
| query_count | SQL statements during the request (`before_cursor_execute`) |
| write_count | INSERT / UPDATE / DELETE statements in that request |
| duration_ms | Wall-clock time for the handler |
| rss_delta_kb | Peak RSS increase during the request (macOS bytes→KB) |
| radar_cache | `hit` / `miss` for `derived:radar` (radar and focus only) |

With `LOG_FORMAT=json` (default) those fields are on the JSON object. With `LOG_FORMAT=human` they still appear on the LogRecord extras.

Sprint 145 used these numbers as the baseline before batching `weekly_rollups()` and thinning `/api/training-log`. Sprint 146 (#1923) adds Plan endpoints plus `write_count` so GET-side writes are visible. Sprint 147 (#1935) adds the Performance page endpoints plus `rss_delta_kb` and `radar_cache`.
