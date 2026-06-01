# Render Setup

How to connect perf-coach to Render and keep UAT/PRD running.

---

## 1. Apply the Blueprint

1. In the Render dashboard → **New → Blueprint**.
2. Connect the `zealchaiwut/perf-coach` GitHub repo.
3. Render reads `render.yaml` from the repo root and creates two services:
   - `perf-coach-uat` — watches the `develop` branch, auto-deploy **on**
   - `perf-coach-prd` — watches the `master` branch, auto-deploy **off**

---

## 2. Environment Variables

`DATABASE_URL` is intentionally absent from `render.yaml` (never commit a connection string).
After the blueprint is applied, set it manually for each service:

### perf-coach-uat

| Variable | Value |
|----------|-------|
| `DATABASE_URL` | Neon UAT branch connection string (`postgresql://...`) |
| `ENVIRONMENT` | `uat` *(set by render.yaml — verify it is present)* |

### perf-coach-prd

| Variable | Value |
|----------|-------|
| `DATABASE_URL` | Neon PRD branch connection string (`postgresql://...`) |
| `ENVIRONMENT` | `prd` *(set by render.yaml — verify it is present)* |

**Where to get the Neon connection strings:**
Neon dashboard → your project → **Branches** → select the branch → **Connection Details** → copy the `psql` string. Ensure it starts with `postgresql://` (not `postgres://`).

> The app reads `DATABASE_URL` first; if absent it falls back to `DATABASE_URL_UAT` / `DATABASE_URL_PRD` (local-dev convention). On Render, always set `DATABASE_URL`.

---

## 3. Deploy Lifecycle

Each Render deploy runs these steps in order (configured in `render.yaml`):

```
pip install -r requirements.txt
alembic upgrade head          ← preDeployCommand
uvicorn backend.main:app ...  ← startCommand
```

Render waits for `alembic upgrade head` to exit 0 before starting `uvicorn`. If migration fails the deploy is marked failed and the previous version keeps serving traffic.

---

## 4. Triggering a Deploy

| Service | Trigger |
|---------|---------|
| `perf-coach-uat` | Any push to `develop` — automatic |
| `perf-coach-prd` | Manual deploy only (auto-deploy is off) |

To deploy PRD: Render dashboard → `perf-coach-prd` → **Manual Deploy → Deploy latest commit**.

---

## 5. Cold-Start Behaviour

Render's **Starter** plan spins down services after ~15 minutes of inactivity. The first request after spin-down takes **30–60 seconds** while the container restarts.

- The `/api/health` health-check path is configured in `render.yaml`; Render polls it to confirm start-up success.
- For development use this is fine. For always-on UAT, upgrade to the **Standard** plan or set up an external uptime monitor to keep the service warm.

---

## 6. Region Selection

Both services are deployed to **Singapore** (`region: singapore` in `render.yaml`). This matches the Neon project region. Keep the Render region and Neon region co-located to minimise DB latency.

To change region: update the `region` field in `render.yaml`, delete the existing Render service, and re-apply the blueprint (region changes are not applied in-place by Render).

Available Render regions: `oregon`, `ohio`, `virginia`, `frankfurt`, `singapore`.

---

## 7. Verifying a UAT Deploy

```bash
# Health check
curl https://perf-coach-uat.onrender.com/api/health
# Expected: {"status":"ok","environment":"uat",...}

# Smoke tests
BASE_URL=https://perf-coach-uat.onrender.com \
  EXPECTED_ENVIRONMENT=uat \
  pytest tests/test_smoke_deploy.py -v
```

---

## 8. Troubleshooting

### `DuplicateTable` in migration log
Idempotency guards (`IF NOT EXISTS`) in migration files prevent this. If you see it anyway, the migration file is missing a guard — add one and re-deploy.

### Health check never goes green
Check the Render build log. Common causes: `alembic upgrade head` failed (bad `DATABASE_URL`), or `uvicorn` crashed on startup (missing env var).

### `could not connect to server`
Verify the `DATABASE_URL` in Render matches the Neon connection string exactly, including `sslmode=require`. Neon connections require SSL.
