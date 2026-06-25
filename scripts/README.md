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
