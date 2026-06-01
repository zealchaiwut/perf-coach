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

## backfill_readiness.py — Historical readiness score backfill

One-shot backfill for historical readiness scores.

```bash
python scripts/backfill_readiness.py --user-id <UUID> [--env uat|prd]
```
