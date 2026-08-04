# scripts/

Utility scripts for perf-coach developers.

---

## db_snapshot.py — Manual database snapshot

Dumps a gzipped SQL snapshot from `DATABASE_URL` into `snapshots/`.

### Prerequisites

- `pg_dump` installed and on `PATH` (ships with `postgresql-client`)
- `.env` at repo root contains a valid `DATABASE_URL`

### Usage

```bash
python scripts/db_snapshot.py
```

### Output

```
Dumping <dbname> from <host>...
Wrote snapshots/<dbname>-<timestamp>.sql.gz (<N> KB)
```

File lands in `snapshots/` (git-ignored). Timestamp format: `YYYYMMDD-HHMMSS` (local time).

### Restore

```bash
gunzip -c snapshots/<file>.sql.gz | psql $DATABASE_URL
```

### Exit codes

| Code | Meaning |
|------|---------|
| `0`  | Success |
| `1`  | Any failure (missing `DATABASE_URL`, bad URL, `pg_dump` not found, dump error) |

---

## set_user_password.py — Set password for an existing user

Sets (or resets) the password for an existing user by username. Hashes via
`backend.auth` and targets the database selected by `ENVIRONMENT`.

### Usage

```bash
ENVIRONMENT=uat python scripts/set_user_password.py <username>
ENVIRONMENT=prd python scripts/set_user_password.py <username>
```

Password is prompted with no echo (`getpass`). Plaintext is never printed or logged.

### Validation

- Empty password → exits with code `1`
- Password shorter than `MIN_PASSWORD_LENGTH` (defined in `backend/auth.py`) → exits with code `1`
- Username not found in the target database → exits with code `1`

### Exit codes

| Code | Meaning |
|------|---------|
| `0`  | Success — prints `Password updated for user '<username>'.` |
| `1`  | Failure — descriptive message written to stderr |

### Idempotent

Running the script twice with the same credentials is safe; the user's
`password_hash` is updated each time (new salt), but login continues to work.

---

## backfill_readiness.py — Historical readiness score backfill

One-shot backfill for historical readiness scores.

```bash
python scripts/backfill_readiness.py --user-id <UUID> [--env uat|prd]
```

---

## seed_mock_user.py — Disposable athlete for manual UI review

Creates one new user with synthetic-but-plausible history, so the app can be
driven in a browser without going anywhere near a real account. It reads no
other user's rows and copies no credentials — everything is generated.

```bash
ENVIRONMENT=uat python scripts/seed_mock_user.py --name uxmock
ENVIRONMENT=uat python scripts/seed_mock_user.py --name uxmock --drop  # rebuild
```

Generates ~20 weeks of runs (easy / tempo / intervals / long / strength, with a
down week every fourth and ~8% of sessions missed), 120 days of wellness
metrics with a few gaps, ~3 weigh-ins a week on a downward trend, an active
weight target, fuel settings, and five habits with logs. Deliberately imperfect:
a seed where every habit is 100% and no session is ever skipped hides exactly
the states the UI is worst at.

### Then

```bash
ENVIRONMENT=uat python scripts/set_user_password.py uxmock
ENVIRONMENT=uat PYTHONPATH=. python scripts/backfill_training_load.py --user_id <UUID> --env uat
ENVIRONMENT=uat PYTHONPATH=. python scripts/backfill_readiness.py --user-id <UUID> --env uat
```

The two backfills are not optional if you care about the pages that read
CTL/ATL/TSB or readiness — without them those panels render empty and you will
mistake missing seed data for a UI bug.

### Why it is a script and not a fixture

CLAUDE.md requires using a frontend change in a real browser before calling it
done, and an empty account cannot show you a crowded week, a stale weigh-in, or
a habit at 3/7. This exists so that requirement is cheap to meet.

`--drop` only ever deletes the user it was asked to create, and refuses the
names used by real accounts.
