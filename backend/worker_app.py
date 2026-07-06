"""Standalone compute-worker FastAPI app.

Runs on a separate machine (zeal-server), port 9100, sharing the same Neon
Postgres as the webapp. Handles scheduled + manually-triggered syncs and
heavy recomputes (Strava/Stryd sync, performance backfill, Banister refit).

IMPORTANT: this module must NEVER import backend.main — that module starts
daemon threads (sleep sync, banister refit) at import time. Only import
backend.db, backend.models, and backend.services.* here.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy.orm import Session

from backend.db import engine

logger = logging.getLogger("backend.worker_app")

app = FastAPI(title="perf-coach compute worker")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="worker-sync")

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
_STALE_GUARD_WINDOW = timedelta(hours=2)
# Serializes the stale-guard check + job-row creation in _run_one_sync so
# concurrent triggers (manual + scheduled) can't start duplicate syncs.
_single_flight_lock = threading.Lock()
_BANISTER_REFIT_INTERVAL_SECONDS = 7 * 24 * 3600  # weekly


# ── Auth ─────────────────────────────────────────────────────────────────────

def require_worker_secret(x_worker_secret: str | None = Header(default=None)) -> None:
    configured = os.getenv("WORKER_SHARED_SECRET")
    if not configured:
        raise HTTPException(status_code=503, detail="worker secret not configured")
    if x_worker_secret != configured:
        raise HTTPException(status_code=401, detail="unauthorized")


# ── DbRecorder ───────────────────────────────────────────────────────────────

class DbRecorder:
    """Implements the sync_runner recorder duck-type, persisting to worker_job_runs.

    Each method opens its own short-lived Session and commits — worker runs
    can be long, so we avoid holding a single session open for the duration.
    """

    def __init__(self, job_type: str, user_id: str | None, triggered_by: str = "manual") -> None:
        from backend.models import WorkerJobRun

        self.job_id = None
        with Session(engine) as s:
            row = WorkerJobRun(
                job_type=job_type,
                user_id=user_id,
                status="running",
                phase=None,
                items_synced=0,
                triggered_by=triggered_by,
                started_at=datetime.now(timezone.utc),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            self.job_id = row.id

    def set_phase(self, uid, phase) -> None:
        from backend.models import WorkerJobRun

        with Session(engine) as s:
            row = s.get(WorkerJobRun, self.job_id)
            if row is not None:
                row.phase = phase
                s.commit()

    def increment(self, uid, current: int = 0, items_synced: int = 0) -> None:
        from backend.models import WorkerJobRun

        with Session(engine) as s:
            row = s.get(WorkerJobRun, self.job_id)
            if row is not None:
                row.items_synced = (row.items_synced or 0) + items_synced
                s.commit()

    def mark_success(self, uid, stats: dict | None = None) -> None:
        from backend.models import WorkerJobRun

        with Session(engine) as s:
            row = s.get(WorkerJobRun, self.job_id)
            # One-shot: once finished_at is set the run is finalized — a later
            # mark_success must not overwrite an earlier mark_error (or vice versa).
            if row is not None and row.finished_at is None:
                row.status = "success"
                row.finished_at = datetime.now(timezone.utc)
                if stats is not None:
                    row.stats = stats
                s.commit()

    def mark_error(self, uid, message: str) -> None:
        from backend.models import WorkerJobRun

        with Session(engine) as s:
            row = s.get(WorkerJobRun, self.job_id)
            if row is not None and row.finished_at is None:
                row.status = "error"
                row.error = message
                row.finished_at = datetime.now(timezone.utc)
                s.commit()


# ── Single-flight stale guard ────────────────────────────────────────────────

def _job_running_recently(job_type: str, user_id: str | None) -> bool:
    from backend.models import WorkerJobRun

    cutoff = datetime.now(timezone.utc) - _STALE_GUARD_WINDOW
    with Session(engine) as s:
        q = s.query(WorkerJobRun).filter(
            WorkerJobRun.job_type == job_type,
            WorkerJobRun.status == "running",
            WorkerJobRun.started_at >= cutoff,
        )
        if user_id is None:
            q = q.filter(WorkerJobRun.user_id.is_(None))
        else:
            q = q.filter(WorkerJobRun.user_id == user_id)
        return q.first() is not None


# ── Sync execution helpers ───────────────────────────────────────────────────

def _users_with_strava_tokens() -> list[str]:
    from backend.models import StravaToken

    with Session(engine) as s:
        return [str(uid) for (uid,) in s.query(StravaToken.user_id).all()]


def _users_with_stryd_credentials() -> list[str]:
    from backend.models import StrydCredentials

    with Session(engine) as s:
        return [str(uid) for (uid,) in s.query(StrydCredentials.user_id).all()]


def _run_one_sync(user_id: str, source: str, full: bool, triggered_by: str) -> None:
    from backend.services import sync_runner

    # Check-then-create under a lock so a manual /internal/sync/run racing the
    # scheduled sweep can't both pass the stale-guard and start duplicates.
    with _single_flight_lock:
        if _job_running_recently(source + "_sync", user_id):
            logger.info("skip %s sync for user %s: already running within stale-guard window", source, user_id)
            return
        recorder = DbRecorder(job_type=f"{source}_sync", user_id=user_id, triggered_by=triggered_by)

    logger.info("job start: %s_sync user=%s full=%s triggered_by=%s", source, user_id, full, triggered_by)
    try:
        # run_strava_sync/run_stryd_sync finalize the recorder themselves
        # (mark_success/mark_error) and never re-raise — do not finalize again
        # here, or a mark_error result would be overwritten with success.
        if source == "strava":
            sync_runner.run_strava_sync(user_id, full=full, recorder=recorder)
        elif source == "stryd":
            sync_runner.run_stryd_sync(user_id, full=full, recorder=recorder)
        else:
            raise ValueError(f"unknown source: {source}")
        logger.info("job finish: %s_sync user=%s", source, user_id)
    except Exception as exc:
        recorder.mark_error(user_id, str(exc))
        logger.error("job finish: %s_sync user=%s status=error: %s", source, user_id, exc, exc_info=True)


def _run_batch_sync(user_id: str | None, sources: list[str], full: bool, triggered_by: str) -> int:
    if user_id is not None:
        targets = {source: [user_id] for source in sources}
    else:
        targets = {}
        if "strava" in sources:
            targets["strava"] = _users_with_strava_tokens()
        if "stryd" in sources:
            targets["stryd"] = _users_with_stryd_credentials()

    count = 0
    for source, user_ids in targets.items():
        for uid in user_ids:
            _executor.submit(_run_one_sync, uid, source, full, triggered_by)
            count += 1
    return count


def _run_backfill(user_id: str) -> None:
    from backend.services.backfill_performance import backfill_performance_for_athlete

    recorder = DbRecorder(job_type="backfill", user_id=user_id, triggered_by="manual")
    logger.info("job start: backfill user=%s", user_id)
    try:
        with Session(engine) as s:
            result = backfill_performance_for_athlete(user_id, s)
        recorder.mark_success(user_id, stats=result if isinstance(result, dict) else None)
        logger.info("job finish: backfill user=%s status=success", user_id)
    except Exception as exc:
        recorder.mark_error(user_id, str(exc))
        logger.error("job finish: backfill user=%s status=error: %s", user_id, exc, exc_info=True)


def _run_banister_refit_batch() -> None:
    from backend.models import User
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    with Session(engine) as s:
        user_ids = [str(r.id) for r in s.query(User.id).filter(User.is_active.is_(True)).all()]

    recorder = DbRecorder(job_type="banister_refit", user_id=None, triggered_by="schedule")
    logger.info("job start: banister_refit users=%d", len(user_ids))
    try:
        results = run_banister_refit_pipeline(user_ids)
        ok_count = sum(1 for v in results.values() if v == "ok")
        stats = {"ok": ok_count, "total": len(results), "results": results}
        recorder.mark_success(None, stats=stats)
        logger.info("job finish: banister_refit status=success ok=%d/%d", ok_count, len(results))
    except Exception as exc:
        recorder.mark_error(None, str(exc))
        logger.error("job finish: banister_refit status=error: %s", exc, exc_info=True)


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/internal/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.post("/internal/sync/run", dependencies=[Depends(require_worker_secret)])
def sync_run(body: dict):
    user_id = body.get("user_id")
    sources = body.get("sources") or ["strava", "stryd"]
    full = bool(body.get("full", False))
    triggered_by = body.get("triggered_by", "manual")

    started = _run_batch_sync(user_id, sources, full, triggered_by)
    return {"started": True, "users": started}


@app.get("/internal/jobs", dependencies=[Depends(require_worker_secret)])
def list_jobs(limit: int = 50):
    from backend.models import WorkerJobRun

    with Session(engine) as s:
        rows = (
            s.query(WorkerJobRun)
            .order_by(WorkerJobRun.started_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": str(row.id),
                "job_type": row.job_type,
                "user_id": str(row.user_id) if row.user_id else None,
                "status": row.status,
                "phase": row.phase,
                "items_synced": row.items_synced,
                "error": row.error,
                "triggered_by": row.triggered_by,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
            for row in rows
        ]


@app.post("/internal/performance/backfill", dependencies=[Depends(require_worker_secret)])
def performance_backfill(body: dict):
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")

    _executor.submit(_run_backfill, user_id)
    return {"started": True}


# ── Scheduler thread ─────────────────────────────────────────────────────────

def _parse_sync_times() -> list[tuple[int, int]]:
    raw = os.getenv("WORKER_SYNC_TIMES", "06:00,18:00")
    times = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        # Skip (loudly) rather than raise: a malformed entry must not kill the
        # scheduler thread before its loop starts.
        try:
            hh_s, mm_s = part.split(":")
            hh, mm = int(hh_s), int(mm_s)
            if not (0 <= hh < 24 and 0 <= mm < 60):
                raise ValueError(part)
        except ValueError:
            logger.error("WORKER_SYNC_TIMES: ignoring invalid entry %r (expected HH:MM)", part)
            continue
        times.append((hh, mm))
    if not times:
        logger.error("WORKER_SYNC_TIMES=%r yields no valid times — no scheduled syncs will run (hourly idle poll)", raw)
    return times


def _seconds_until_next(times: list[tuple[int, int]]) -> float:
    now = datetime.now(BANGKOK_TZ)
    candidates = []
    for hh, mm in times:
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        candidates.append(candidate)
    next_time = min(candidates)
    return (next_time - now).total_seconds()


def _scheduler_loop() -> None:
    times = _parse_sync_times()
    logger.info("sync scheduler started (times=%s, tz=Asia/Bangkok)", times)

    banister_enabled = os.getenv("WORKER_BANISTER_ENABLED", "1") == "1"
    last_banister_refit = time.monotonic()

    while True:
        sleep_seconds = _seconds_until_next(times) if times else 3600
        time.sleep(max(sleep_seconds, 1))
        try:
            count = _run_batch_sync(None, ["strava", "stryd"], full=False, triggered_by="schedule")
            logger.info("scheduled sync enqueued: %d job(s)", count)
        except Exception as exc:
            logger.error("scheduled sync failed to enqueue: %s", exc, exc_info=True)

        if banister_enabled and (time.monotonic() - last_banister_refit) >= _BANISTER_REFIT_INTERVAL_SECONDS:
            last_banister_refit = time.monotonic()
            try:
                _executor.submit(_run_banister_refit_batch)
            except Exception as exc:
                logger.error("scheduled banister refit failed to enqueue: %s", exc, exc_info=True)


@app.on_event("startup")
def _start_scheduler() -> None:
    thread = threading.Thread(target=_scheduler_loop, daemon=True, name="worker-scheduler")
    thread.start()
