# DB Snapshot — Backup & Restore Runbook

## 1. When to Back Up

Take a snapshot before any of these events:

1. **Pre-sprint deploy** — before merging a sprint branch into `master`.
2. **Pre-manual SQL** — before running any hand-crafted `UPDATE`, `DELETE`, or `ALTER` against PRD or UAT.
3. **Pre-PRD deploy** — before pushing a new Alembic migration to production.
4. **Weekly habit** — every Sunday (or Monday morning) as a standing baseline so any regression is at most a week old.
5. **Before schema experiments** — before `alembic downgrade` or any destructive migration test.

---

## 2. Taking a Snapshot

### Prerequisites

- `pg_dump` in PATH (`brew install libpq` on macOS, `apt install postgresql-client` on Ubuntu).
- `DATABASE_URL` set in your environment or `.env` file.

### Command

Run from the repo root:

```bash
python scripts/db_snapshot.py
```

### What happens

- Output directory: `snapshots/` (created automatically if missing).
- **File naming**: `<dbname>-<YYYYMMDD>-<HHMMSS>.sql.gz`
  - Example: `perf_coach_prd-20260531-143022.sql.gz`
- The dump uses `pg_dump --no-owner --no-acl` and pipes stdout through gzip.
- **Expected file size**: 10 KB – 2 MB for a single-user database at typical scale.
- **Expected runtime**: 2–15 seconds on a Neon serverless DB depending on wake-up latency.

Progress is printed to stderr:

```
Dumping perf_coach_prd from ep-xyz.us-east-2.aws.neon.tech...
Wrote snapshots/perf_coach_prd-20260531-143022.sql.gz (48 KB)
```

Exit code 0 on success, non-zero on any error.

---

## 3. Restoring a Snapshot

### (a) Choose the snapshot file

```bash
ls -lht snapshots/
```

Pick the `.sql.gz` file you want to restore. Copy the full filename.

### (b) Drop and recreate the target DB

> **⚠ DESTRUCTIVE — this erases all existing data in the target database.**
> Run only against a throwaway / local / UAT database unless you are performing
> a disaster recovery on PRD and accept full data loss for the restore period.

```bash
# Connect to the postgres admin DB (not the target DB itself)
psql "$ADMIN_DATABASE_URL" \
  -c "DROP DATABASE IF EXISTS <target_dbname>;" \
  -c "CREATE DATABASE <target_dbname>;"
```

Replace `<target_dbname>` with the database name shown in your `DATABASE_URL`.

### (c) Restore with gunzip + psql

```bash
gunzip -c snapshots/<snapshot_file>.sql.gz | psql "$DATABASE_URL"
```

Example:

```bash
gunzip -c snapshots/perf_coach_prd-20260531-143022.sql.gz | psql "$DATABASE_URL"
```

### (d) Sanity queries

```bash
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM users;"
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM workouts;"
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM daily_metrics;"
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM weight_entries;"
```

All counts should be non-zero (unless the source DB was genuinely empty).

---

## 4. Restoring to a Different Environment

Use case: copy PRD data into UAT or a local DB for debugging.

**Step 1** — Snapshot PRD:

```bash
DATABASE_URL="$PRD_DATABASE_URL" python scripts/db_snapshot.py
```

**Step 2** — Drop + recreate the target (UAT or local):

> **⚠ DESTRUCTIVE — this erases all data in the target environment.**

```bash
psql "$UAT_ADMIN_DATABASE_URL" \
  -c "DROP DATABASE IF EXISTS <uat_dbname>;" \
  -c "CREATE DATABASE <uat_dbname>;"
```

**Step 3** — Restore into UAT / local:

```bash
gunzip -c snapshots/<prd_snapshot>.sql.gz | psql "$UAT_DATABASE_URL"
```

**Step 4** — Confirm with sanity queries from Section 3.

---

## 5. Snapshot Retention

This is a single-user project with no compliance requirements. Recommended policy:

- **Keep last 10 snapshots** — delete older ones manually:
  ```bash
  ls -t snapshots/*.sql.gz | tail -n +11 | xargs rm -f
  ```
- **Or delete snapshots older than 30 days**:
  ```bash
  find snapshots/ -name "*.sql.gz" -mtime +30 -delete
  ```

Run either command after taking a fresh snapshot. There is no automated pruning today.

---

## 6. What NOT to Back Up

| Do not commit or back up | Reason |
|---|---|
| `.env` / `.env.*` files | Contain live DB credentials and API secrets |
| `snapshots/` directory | Snapshots can contain PRD PII; treat as sensitive, store locally only |
| `__pycache__/`, `.venv/` | Generated, environment-specific, large |
| Application state outside the DB | Log files, local caches, uvicorn PID files — none are part of a DB backup |

`snapshots/` is already in `.gitignore`. Do not remove that entry.

---

## 7. Future: Automated Snapshots

`scripts/db_snapshot.py` is **manual-only** today. It must be run by hand before risky operations (see Section 1).

Possible next steps (future ticket):

- **Render scheduled job** — add a cron job on Render that runs `python scripts/db_snapshot.py` nightly and uploads the `.sql.gz` to S3 or R2.
- **GitHub Actions cron** — weekly workflow dispatching the snapshot script against PRD and storing the artifact.
- **Snapshot pruning script** — automate the keep-last-N policy from Section 5.

None of these are in scope for the current sprint. File a new issue when ready to implement.
