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

1. Render dashboard → **perf-coach-prd** → **Deploys** tab.
2. Find the last known-good deploy.
3. Click **Rollback to this deploy**.

Render re-deploys the previous image immediately — no code changes needed.

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
