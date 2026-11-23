# Query-count logging (issue #1912)

Lightweight per-request SQL instrumentation for the Log tab endpoints:

- `GET /api/training-log`
- `GET /api/weekly-rollup`
- `GET /api/training/month`

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
| duration_ms | Wall-clock time for the handler |

With `LOG_FORMAT=json` (default) those fields are on the JSON object. With `LOG_FORMAT=human` they still appear on the LogRecord extras.

Sprint 145 uses these numbers as the baseline before batching `weekly_rollups()` and thinning `/api/training-log`.
