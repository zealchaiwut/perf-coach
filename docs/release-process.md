# Release Process

How to promote a tested change from UAT to production (PRD).

---

## Overview

```
develop ──► UAT (auto-deploy)
              │
              ▼  (after UAT passes)
           master ──► PRD (manual deploy on Render)
```

PRD auto-deploy is **off**. Every PRD release is deliberate: a human opens the
PR, reviews it, merges it, then clicks "Manual Deploy" in the Render dashboard.

---

## 7-Step Release Flow

### Step 1 — Verify UAT is green

Before touching master, confirm UAT is stable:

```bash
curl https://perf-coach-uat.onrender.com/api/health
# Expected: {"status":"ok","environment":"uat",...}
```

Run the smoke suite:

```bash
BASE_URL=https://perf-coach-uat.onrender.com \
  EXPECTED_ENVIRONMENT=uat \
  pytest tests/test_smoke_deploy.py -v
```

All tests must pass. Fix any failures on `develop` before proceeding.

---

### Step 2 — Open PR: develop → master

Create the release PR on GitHub:

```bash
gh pr create \
  --base master \
  --head develop \
  --title "release: <date> — <short summary>" \
  --body "Release from develop. UAT smoke tests passed."
```

Target branch must be `master`. Do **not** squash commits — preserve the merge
history for traceability.

---

### Step 3 — Review and merge the PR

At least one reviewer must approve the PR before merging. The review checklist:

- [ ] No migration conflicts (`alembic heads` shows a single head)
- [ ] `render.yaml` `perf-coach-prd` block unchanged or intentionally updated
- [ ] No `DATABASE_URL` or secrets committed
- [ ] `CHANGELOG.md` updated with the release entry
- [ ] UAT smoke tests passed (Step 1)

Merge via GitHub UI (merge commit, not squash). Direct pushes to `master` are
blocked — the PR is the only path.

---

### Step 3b — Verify the PRD compute worker is running

The PRD compute worker runs on zeal-server (`~/dev/perf-coach/prd`, port 9101)
and is responsible for the weekly Banister parameter refit. If it is not running
and `BANISTER_REFIT_ENABLED` is `"0"` in the Render dashboard, the refit silently
stops for production athletes — a regression from current behavior.

Before deploying, confirm one of the following:

**Option A — PRD worker is running (preferred):**

```bash
ssh zeal-server@100.103.104.41
curl -s http://127.0.0.1:9101/internal/health
# Expected: {"status": "ok", ...}
```

If healthy, verify the Render dashboard shows `BANISTER_REFIT_ENABLED=0` for
`perf-coach-prd` (so the web dyno does not double-run the refit).

**Option B — PRD worker is NOT running:**

Confirm `BANISTER_REFIT_ENABLED=1` (or the key is absent) in the Render
dashboard for `perf-coach-prd`. The in-process fallback on the web dyno keeps
the refit running until the PRD worker is stood up.

See `docs/worker.md § Live PRD runbook` for full setup instructions.

> **Do not skip this step.** An unguarded flag flip (`BANISTER_REFIT_ENABLED=0`
> with no PRD worker running) silently disables Banister refit for all production
> athletes.

---

### Step 3c — Pre-deploy DB snapshot (required for large migration batches)

> **Required whenever the release includes destructive schema changes — column
> renames, column drops, or table drops.**
>
> Before deploying, identify whether this release contains destructive migrations.
> Check the migration files in `alembic/versions/` that are new since the current
> PRD head (`DATABASE_URL=$DATABASE_URL_PRD alembic current`) and look for any
> `op.drop_column`, `op.drop_table`, or `op.alter_column` (renames) calls. If any
> exist, a code-only rollback against the already-migrated PRD schema is **unsafe**;
> if a deploy fails after migrations run, a DB restore is required.

Take a snapshot of PRD immediately before deploying:

```bash
# Source your .env to get DATABASE_URL_PRD
source .env
DATABASE_URL=$DATABASE_URL_PRD python scripts/db_snapshot.py
```

Note the snapshot filename printed (e.g. `snapshots/perf_coach_prd-<date>.sql.gz`).
If you need to roll back, follow `docs/backup-restore.md § 3` to restore it.

**Only skip this step if you have verified that no migration in this batch renames
or drops any column.** If uncertain, take the snapshot — it costs under 15 seconds.

---

### Step 4 — Trigger Manual Deploy on Render

1. Open [Render dashboard](https://dashboard.render.com) → service **perf-coach-prd**.
2. Click **Manual Deploy → Deploy latest commit**.
3. Confirm the commit SHA matches the merge commit from Step 3.

> Auto-deploy is intentionally disabled for PRD (`autoDeploy: no` in
> `render.yaml`). Never enable it.

---

### Step 5 — Watch the build log

Monitor the Render build log in real time. Confirm all three stages complete
without errors:

1. `pip install -r requirements.txt` — exits 0
2. `alembic upgrade head` (against PRD Neon DB) — exits 0, no `DuplicateTable`
3. `uvicorn backend.main:app` starts and the health check path `/api/health`
   returns HTTP 200

If any stage fails, Render aborts the deploy and keeps the previous version
live. See [Troubleshooting](#troubleshooting) below.

---

### Step 6 — Smoke-test PRD

Once the deploy is marked **Live** in Render, verify:

```bash
# Health check
curl https://perf-coach-prd.onrender.com/api/health
# Expected: {"status":"ok","environment":"prd",...}

# Smoke suite
BASE_URL=https://perf-coach-prd.onrender.com \
  EXPECTED_ENVIRONMENT=prd \
  pytest tests/test_smoke_deploy.py -v
```

Also manually open `/home.html`, `/log`, and `/trends` on the PRD URL and
confirm pages load without errors and the nav badge reads **PRD** in red.

---

### Step 7 — Rollback if broken

If smoke tests fail or PRD is unhealthy after deploy:

> ⚠ **Read this before clicking "Rollback".**
>
> A Render image rollback re-deploys the previous Docker image — it does **not**
> roll back already-applied Alembic migrations. If `alembic upgrade head` already
> ran as the `preDeployCommand`, the PRD database schema is already at the new
> head. Rolling back the code image while the DB is at the new head can break
> things further if any applied migration renamed or dropped a column the old
> code still reads.
>
> **Destructive migrations are specifically unsafe to roll back via code-only
> rollback.** Column drops, column renames, or table drops mean the old code image
> references columns or tables that no longer exist (or have been renamed). Running
> the old image against the migrated schema will produce 500 errors or silent data
> corruption, not a clean rollback.

**Decision tree:**

- If `alembic upgrade head` **did not run** (build failed before the preDeployCommand
  completed): a Render image rollback is safe — the DB schema is unchanged.
- If `alembic upgrade head` **ran successfully** before the failure: a code-only
  rollback is **unsafe for releases with destructive migrations**. You must restore
  the DB from the pre-deploy snapshot taken in Step 3c, then redeploy the old image.

**Code-only rollback (safe when migrations did not run or were non-destructive):**

1. Render dashboard → **perf-coach-prd** → **Deploys** tab.
2. Find the last known-good deploy.
3. Click **Rollback to this deploy**.

**Full DB restore (required when destructive migrations already ran):**

1. Restore the pre-deploy snapshot per `docs/backup-restore.md § 3`:
   ```bash
   gunzip -c snapshots/<pre-deploy-snapshot>.sql.gz | psql "$DATABASE_URL_PRD"
   ```
2. Then perform the Render image rollback (steps 1–3 above).
3. Verify the restored DB is consistent with the old code before considering
   the rollback complete.

After rolling back:
- Open a hotfix branch off `master`, fix the issue, merge via PR, and repeat
  from Step 1.
- Do **not** revert the `develop` branch; fix forward.

---

## Alembic state verification

To confirm the PRD database migration head matches the codebase:

```bash
# Check codebase migration head
alembic heads

# Check PRD DB current revision (requires DATABASE_URL_PRD in .env)
DATABASE_URL=$(grep DATABASE_URL_PRD .env | cut -d= -f2-) alembic current
```

Both outputs must show the same revision hash.

---

## Troubleshooting

### `alembic upgrade head` fails in PRD build log
Verify `DATABASE_URL` is set in the Render dashboard for `perf-coach-prd` and
matches the Neon PRD connection string (includes `sslmode=require`).

### Health check never goes green after deploy
Check that `uvicorn` started — look for `Application startup complete` in the
log. If absent, a missing env var or import error prevented startup.

### `DuplicateTable` in migration log
Migration is missing an idempotency guard. Add `IF NOT EXISTS` to the offending
`CREATE TABLE` or `ADD COLUMN` statement and re-deploy.

### Nav badge shows wrong environment
`ENVIRONMENT` env var in Render must be exactly `prd` (lowercase). Verify in
Render dashboard → **perf-coach-prd** → **Environment**.
