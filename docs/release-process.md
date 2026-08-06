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

## Release Flow

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

### Step 4 — (Large-batch releases only) Create a Neon DB branch snapshot

> **When does this apply?** Any release where `alembic history -r current:head`
> shows more than ~20 pending migrations. Run the count before deploying:
>
> ```bash
> # Count migrations pending on PRD (requires DATABASE_URL_PRD in .env)
> DATABASE_URL=$(grep DATABASE_URL_PRD .env | cut -d= -f2-) \
>   alembic history -r current:head | grep -c "^Rev:"
> ```
>
> If the count is high (e.g. ≥ 20), take a Neon snapshot **before** clicking
> Manual Deploy in Step 5. Skipping this step for small releases is fine; for a
> large accumulated batch it gives you a fast, no-data-loss rollback path that
> the Render image rollback (Step 8) cannot provide — Render restores the app
> binary but **does not undo schema changes** applied by Alembic.

#### 4a — Create a Neon branch (point-in-time snapshot)

1. Open the [Neon console](https://console.neon.tech) and select the **perf-coach-prd** project.
2. Click **Branches** → **New Branch**.
3. Set:
   - **Branch name:** `pre-release-<YYYY-MM-DD>` (e.g. `pre-release-2026-08-07`)
   - **Branch from:** the PRD primary branch (`main` or `br-xxx`)
   - **Point in time:** leave as **Now** (captures the current schema + data)
4. Click **Create Branch**. The branch is ready in a few seconds.

Keep the branch for at least 48 hours after the release. Delete it once PRD
smoke tests have been stable for that window.

#### 4b — Record the branch ID

Copy the Neon branch connection string for the snapshot branch from the
console and save it somewhere temporary (e.g. a local note). You will need
it only if you must restore.

#### 4c — Restore from snapshot (if migrations go wrong)

If `alembic upgrade head` partially completes and leaves the PRD schema in an
inconsistent state:

1. Roll back the Render deploy (Step 8) first so the app stops writing to PRD.
2. In the Neon console, navigate to the snapshot branch (`pre-release-<date>`).
3. Click **Restore** → **Restore branch to another branch** (Neon PITR restore).
   Target the PRD primary branch.
4. Confirm the restore. The PRD branch is reset to the pre-migration state.
5. Re-run `alembic current` (against the restored DB) to confirm the head
   revision reverted, then fix the offending migration on `develop` before
   attempting another release.

> **Note:** Neon PITR is scoped to the Neon Free/Pro plan's retention window
> (typically 7 days on Pro). Prefer the explicit branch snapshot above over
> relying solely on the timeline slider, as the branch is an intentional,
> named checkpoint that is easy to find under pressure.

---

### Step 5 — Trigger Manual Deploy on Render

1. Open [Render dashboard](https://dashboard.render.com) → service **perf-coach-prd**.
2. Click **Manual Deploy → Deploy latest commit**.
3. Confirm the commit SHA matches the merge commit from Step 3.
   (If you took a Neon snapshot in Step 4, double-check it was created **before** clicking here.)

> Auto-deploy is intentionally disabled for PRD (`autoDeploy: no` in
> `render.yaml`). Never enable it.

---

### Step 6 — Watch the build log

Monitor the Render build log in real time. Confirm all three stages complete
without errors:

1. `pip install -r requirements.txt` — exits 0
2. `alembic upgrade head` (against PRD Neon DB) — exits 0, no `DuplicateTable`
3. `uvicorn backend.main:app` starts and the health check path `/api/health`
   returns HTTP 200

If any stage fails, Render aborts the deploy and keeps the previous version
live. See [Troubleshooting](#troubleshooting) below.

---

### Step 7 — Smoke-test PRD

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

### Step 8 — Rollback if broken

If smoke tests fail or PRD is unhealthy after deploy:

1. Render dashboard → **perf-coach-prd** → **Deploys** tab.
2. Find the last known-good deploy.
3. Click **Rollback to this deploy**.

Render re-deploys the previous image immediately — no code changes needed.

> **Important — schema changes are NOT rolled back by Render.** If `alembic
> upgrade head` ran (even partially) before the failure, the Render image
> rollback restores the app binary but leaves the PRD DB schema at whatever
> revision Alembic reached. For large-batch releases where you took a Neon
> snapshot in Step 4, use that branch to restore the DB schema (see
> Step 4c above). For small releases with no schema changes, the Render
> rollback alone is sufficient.

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

### Partial migration failure on a large batch (PRD schema inconsistent)
If `alembic upgrade head` fails mid-batch and the PRD DB is in a partially-migrated
state:

1. Roll back the Render deploy (Step 8) so the app stops writing.
2. If you took a Neon branch snapshot in Step 4, restore it (see Step 4c).
3. If you did **not** take a snapshot, use Neon's PITR timeline slider:
   - Neon console → **Branches** → primary branch → **Restore** → pick a
     timestamp from before the deploy. Neon Free retains 7 days; Pro retains
     30 days.
4. Verify `alembic current` against the restored DB shows the pre-release head.
5. Fix the offending migration on `develop`, run it through UAT, and re-release.

**Prevention:** for batches ≥ 20 migrations, always take the Neon snapshot
(Step 4) so recovery is a named branch restore rather than a timeline guess.
