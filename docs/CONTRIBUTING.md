# Contributing to perf-coach

This document captures the sprint structure, ticket patterns, and project
conventions that keep agent-driven sprints consistent. Read it before filing
issues or opening pull requests.

---

## 1. Sprint Structure

### What a sprint is

A sprint is a numbered batch of GitHub issues (`sprint-N` label) executed
sequentially by the coder agent. Each sprint has its own integration branch
(`sprint/sprint-N`) that is rebased from `develop` at sprint start and merged
back when all issues pass UAT.

### Sequencing

Issues within a sprint are executed **sequentially by default** — one issue
fully completes (code → tests → tester approval) before the next begins. This
avoids merge conflicts and keeps the failure surface small.

**Explicit dependencies** — if issue B cannot start until issue A lands schema
changes, note it in the issue body:

```
Depends on: #A (must merge first — adds the `foo` column this issue reads)
```

The sprint manager respects this and will not attempt B until A has merged.

### Bulk-create filing

File all sprint issues together before the sprint starts. Enumerate them in a
single sprint-planning issue and apply the `sprint-N` label to every ticket.
Bulk filing lets the sprint manager build an ordered queue before any code
runs, avoiding the mid-sprint priority churn that causes merge conflicts.

### Branch naming

```
feature/<issue-number>-<short-slug>   # work branch
sprint/sprint-N                       # integration branch
master                                # production
```

Feature branches are created off the sprint integration branch and pushed
there — never directly to `master` or `develop`.

---

## 2. Ticket Writing Patterns

### Good vs bad tickets

**Bad** — vague scope, no acceptance criteria, no file hints:

```
Add export feature
```

**Good** — bounded scope, explicit AC, concrete file paths:

```
Add CSV export for training log (GET /api/training-log/export)

## Acceptance Criteria
- [ ] GET /api/training-log/export?user_id=<uuid>&from=YYYY-MM-DD&to=YYYY-MM-DD
      returns 200 with Content-Type: text/csv
- [ ] CSV columns: date, workout_name, type, tss, duration_min
- [ ] Endpoint added to backend/main.py under the # ── Workouts section
- [ ] Test at tests/test_csv_export_training_log__<issue>.py covers happy path
      and 400 on invalid user_id
```

### Annotated ticket anatomy

```markdown
## What & Why
<!-- One paragraph. What will exist after this ticket that doesn't now?
     Why does it matter — user pain, data gap, or sprint dependency? -->

## Acceptance Criteria
- [ ] <Verb> <noun> — testable and binary (passes or fails, no "should")
      # Good:  "GET /api/habits returns 200 with a JSON array"
      # Bad:   "habits endpoint works correctly"
- [ ] File path included when a specific file must change
      # e.g. "endpoint added to backend/main.py"
- [ ] Edge cases listed explicitly
      # e.g. "returns 409 when (user_id, date) row already exists"
- [ ] Env vars named if the feature needs them
      # e.g. "reads STRAVA_CLIENT_ID from environment"

## UAT Test Steps
<!-- Numbered shell commands the tester can copy-paste. Each step has an
     Expected: line so the tester knows what success looks like. -->
1. Run `curl -s http://127.0.0.1:9001/api/habits?user_id=<uuid>`
   **Expected:** HTTP 200, JSON array (may be empty).

## Out of Scope
<!-- Explicit exclusions prevent scope creep and agent confusion. -->
- Do not modify the habits table schema
- Do not add pagination (follow-on ticket)
```

---

## 3. Coding Conventions

### API endpoints

- All routes are prefixed `/api/` and use **hyphens**, not underscores:
  `/api/daily-metrics`, `/api/workout-splits`, `/api/habit-logs`.
- Group endpoints by resource under a section comment in `backend/main.py`:

  ```python
  # ── Daily Metrics ─────────────────────────────────────────────────────────────
  ```

- Every endpoint that operates on user data takes `user_id` as a query param
  or path segment. Never assume a single implicit user — this is a multi-user
  app.
- Date params are ISO `YYYY-MM-DD`. Range endpoints use query aliases `from`
  and `to`.
- Return `JSONResponse` for all API responses. Follow the `_*_dict()` helper
  pattern for serialization shape — one helper per model.

### HTTP status codes

| Situation | Status |
|---|---|
| Successful read | 200 |
| Successful create | 201 |
| Successful upsert / update | 200 |
| Successful delete | 204 |
| Validation failure (bad field value) | 422, `{"detail": {"field": "<name>", ...}}` |
| Conflict (duplicate unique row) | 409 |
| Bad user input (invalid UUID, bad date format) | 400 |
| Row not found | 404 |

### Python style

- Snake_case for all Python identifiers. No camelCase outside JSON payloads.
- Models live in `backend/models.py` only — no model definitions in
  `main.py`.
- DB session access via `backend/db.py` engine and session helpers.
- No business logic in migration files — migrations only modify schema.

### Secrets in serializers

**Never include tokens, credentials, or secret keys in any API response.**
A `_user_dict()` helper must not emit `hashed_password`, `strava_access_token`,
or any other credential field, even if the ORM model carries it. Serializer
helpers are the last line of defense before the response leaves the process.

### Single-user shortcut pattern

Some pages pass `user_id` via a query param set to the first user in the list.
Keep this as-is — it is not a bug. The app is multi-user at the data layer and
single-user-by-convention at the UI layer for the current deployment. Do not
remove `user_id` params from endpoints to "simplify" them.

---

## 4. Schema Changes

### Adding a new column

New columns must be **nullable with a server-side default** so the migration
runs on a live table without locking every row:

```python
sa.Column("pace_sec_per_km", sa.Integer(), nullable=True, server_default=None)
```

After backfilling, a follow-on migration may add `NOT NULL` if appropriate.

### Adding a new table

Wrap `create_table` in an existence guard so the migration is idempotent:

```python
from alembic.helpers import table_exists   # prefer the project helper

def upgrade() -> None:
    if not table_exists("new_table"):
        op.create_table("new_table", ...)
```

Use `alembic/helpers.py` guards (`table_exists`, `column_exists`,
`index_exists`, `fk_exists`) instead of raw `inspector.has_table()` calls
scattered across migration files.

### Foreign keys

Always declare `ON DELETE` behaviour explicitly. Prefer `CASCADE` for child
rows that are meaningless without the parent (e.g., `habit_logs` → `habits`).
Use `SET NULL` only for optional references. Never leave `ON DELETE` implicit —
the default (RESTRICT) produces opaque errors on Neon when a parent row is
deleted.

```python
op.create_foreign_key(
    "habit_logs_habit_id_fkey",
    "habit_logs", "habits",
    ["habit_id"], ["id"],
    ondelete="CASCADE",
)
```

### Indexes

Add an index for every foreign key column and every column used in a
`WHERE` or `ORDER BY` clause in a time-series query. Use
`CREATE INDEX IF NOT EXISTS` so the statement is idempotent:

```python
op.execute(
    "CREATE INDEX IF NOT EXISTS ix_habit_logs_user_date "
    "ON habit_logs (user_id, log_date DESC)"
)
```

---

## 5. Testing Conventions

### Directory layout

`tests/` mirrors the source concern, not the file tree. Name files after the
issue they cover:

```
tests/test_<feature-slug>__<issue-number>.py
```

Example: `tests/test_daily_metrics_rest_api__39.py`.

### Unit tests for helpers

Functions in `backend/services/` and utility helpers in `backend/main.py`
(e.g., `_workout_dict`, `_habit_dict`) should have unit tests that do not
require a running server. Use `pytest` with `fastapi.testclient.TestClient`
for these.

### Integration tests for endpoints

Endpoint integration tests hit a real running server at
`http://127.0.0.1:9001`. Each test file starts with a docstring naming the
server:

```python
"""
Tests for issue #N: <description>
Server under test: http://127.0.0.1:9001
"""
```

Use `httpx.Client` with `scope="module"` fixtures so the connection is reused
across the test module:

```python
@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url="http://127.0.0.1:9001", timeout=10) as c:
        yield c
```

Resolve `alice_id` via `GET /api/users` — never hard-code a UUID. This keeps
tests portable across environments.

### Mocking external services

Strava, Stryd, and any other external HTTP service must be mocked in tests —
never call live APIs in CI. Use `unittest.mock.patch` to stub the transport
layer or the specific helper that calls the external service:

```python
from unittest.mock import patch

def test_strava_callback(monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "cid")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "csecret")

    with patch("backend.main._exchange_strava_code", return_value={...}), \
         patch("backend.main._upsert_strava_token") as mock_upsert:
        res = client.get("/api/strava/callback", params={"code": "abc", ...})

    assert res.status_code == 200
    mock_upsert.assert_called_once()
```

For HTTP-level mocking of outbound requests (e.g., testing a service that
calls `requests.get`), use the `responses` library:

```python
import responses as rsps

@rsps.activate
def test_stryd_fetch():
    rsps.add(rsps.GET, "https://api.stryd.com/...", json={...}, status=200)
    result = fetch_stryd_activities(token="t")
    assert len(result) == 1
```

---

## 6. Agent Failure Modes

The sprint manager classifies each issue outcome. Two failure categories
require specific diagnosis steps.

### TESTER_REJECTED

**Meaning:** The coder agent pushed a feature branch and the tester agent ran
the UAT test steps, but found at least one failing assertion. The issue was
not advanced to UAT and was not merged.

**Why it happens:**

- The implementation satisfies the coder's own checks but misses an acceptance
  criterion the tester actually verifies (most common cause).
- A new endpoint exists but has no test covering its happy path — the tester's
  first step fails.
- The migration ran but left a data inconsistency that an assertion catches.
- A response shape mismatch: the coder returns `{"data": [...]}` but the
  tester asserts `res.json()` is a plain list.

**Diagnosis steps:**

1. Read the tester's rejection log — the first failing assertion line tells
   you exactly which UAT step failed.
2. Run the failing UAT step manually against a local server
   (`http://127.0.0.1:9001`).
3. Compare the actual response to the `Expected:` line in the issue's UAT
   Test Steps section.
4. Fix the delta, push a new commit to the same feature branch, and re-run
   the tester.

**Do not re-run the sprint** for a TESTER_REJECTED issue without first fixing
the root cause. A blind re-run produces the same rejection.

### CRASH

**Meaning:** The coder or tester agent process exited unexpectedly — not a
test assertion failure, but an unhandled exception, OOM, or forced
termination. The issue state is indeterminate.

**Why it happens:**

- A migration raised an unhandled exception and left the schema in a partial
  state.
- The coder agent exceeded its context window and was terminated mid-edit.
- A background uvicorn process failed to start (port conflict, import error).
- The tester agent itself crashed before completing all assertions.

**Diagnosis steps:**

1. Check the sprint log for the last line before the crash — it identifies
   which step was in progress.
2. Run `alembic current` and `alembic heads` to confirm migration state.
3. Try starting the server manually (`uvicorn backend.main:app --port 9001`)
   and check the traceback.
4. If the feature branch has partial commits, inspect them with `git log` and
   `git diff` before deciding whether to continue or re-implement from scratch.

**Investigate before re-running.** A CRASH caused by a bad migration will
crash again on re-run unless the migration is fixed or rolled back first.

---

## 7. PR Review Checklist

Before a feature branch is eligible for merge via `scripts/finish_feature.py`,
verify the following:

### Tests

- [ ] `pytest tests/` passes locally with the server running at port 9001.
- [ ] Every new endpoint has at least a happy-path test (correct status code +
      response shape) and a 400/404/422 sad-path test.
- [ ] No test hard-codes a UUID — user IDs are resolved via `GET /api/users`.

### Migrations

- [ ] New migration file exists in `alembic/versions/` with a meaningful
      docstring.
- [ ] `upgrade()` uses `alembic/helpers.py` guards (`table_exists`,
      `column_exists`, `index_exists`, `fk_exists`) so re-running is safe.
- [ ] `downgrade()` reverses every change made in `upgrade()`.
- [ ] `alembic upgrade head` completes without error on the UAT database.

### Security

- [ ] No plaintext secrets, tokens, or credentials in any API response.
- [ ] No secrets committed to the repo (no `.env` file, no hardcoded keys).
- [ ] Any new env var is named in the issue and documented in `docs/local-dev.md`
      if it affects local setup.

### Endpoints

- [ ] Route prefix is `/api/` and uses hyphens (not underscores).
- [ ] `user_id` param present on every endpoint that reads or writes user data.
- [ ] No existing endpoint's response shape changed in a breaking way (no field
      removed, no field renamed without a migration-period alias).

### Docs

- [ ] If the change adds a new endpoint, `docs/api-reference.md` is updated.
- [ ] If the change adds a new table or column, `docs/data-model.md` is
      updated.
- [ ] If the change affects local setup (new env var, new dependency, new
      migration step), `docs/local-dev.md` is updated.
