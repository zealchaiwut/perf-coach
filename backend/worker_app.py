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
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy.orm import Session

from backend.db import engine
from backend.services import job_queue

logger = logging.getLogger("backend.worker_app")

app = FastAPI(title="perf-coach compute worker")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="worker-sync")

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
_STALE_GUARD_WINDOW = timedelta(hours=2)
# Serializes the stale-guard check + job-row creation in _run_one_sync so
# concurrent triggers (manual + scheduled) can't start duplicate syncs.
_single_flight_lock = threading.Lock()
_BANISTER_REFIT_INTERVAL_SECONDS = 7 * 24 * 3600  # weekly

# ── Pull-queue config (Phase 1) ──────────────────────────────────────────────
# The worker polls the Neon job_queue and claims work (FOR UPDATE SKIP LOCKED)
# instead of being reached over HTTP — outbound-only, so home NAT is a non-issue.
QUEUE_POLL_ENABLED = os.getenv("QUEUE_POLL_ENABLED", "1") == "1"
QUEUE_POLL_INTERVAL_SECONDS = int(os.getenv("QUEUE_POLL_INTERVAL_SECONDS", "5"))
QUEUE_LEASE_SECONDS = int(os.getenv("QUEUE_LEASE_SECONDS", "600"))
_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


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


def _enqueue_batch_sync(user_id: str | None, sources: list[str], full: bool, enqueued_by: str) -> int:
    """Queue-mode analog of _run_batch_sync: expand to per-user jobs and ENQUEUE
    them (one row per source+user) instead of executing directly. The dedupe_key
    mirrors the stale-guard intent (source_sync:user_id) so a scheduled sweep and
    an on-demand click don't double-enqueue the same work."""
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
            job_queue.enqueue(
                f"{source}_sync",
                {"user_id": uid, "full": full},
                enqueued_by=enqueued_by,
                dedupe_key=f"{source}_sync:{uid}",
            )
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


def _run_form_metrics_backfill(user_id: str) -> None:
    from backend.services.run_form_metrics_service import upsert_form_metrics_for_user

    recorder = DbRecorder(job_type="form_metrics_backfill", user_id=user_id, triggered_by="manual")
    logger.info("job start: form_metrics_backfill user=%s", user_id)
    try:
        result = upsert_form_metrics_for_user(user_id)
        recorder.mark_success(user_id, stats=result)
        logger.info(
            "job finish: form_metrics_backfill user=%s status=success processed=%d written=%d",
            user_id, result["processed"], result["written"],
        )
    except Exception as exc:
        recorder.mark_error(user_id, str(exc))
        logger.error(
            "job finish: form_metrics_backfill user=%s status=error: %s", user_id, exc, exc_info=True
        )


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


# ── Pull-queue: dispatch + poll loop (Phase 1) ───────────────────────────────
#
# Each handler runs the EXISTING execution function (which creates and finalizes
# its own worker_job_runs audit row via DbRecorder — we do NOT create a second
# one), then the wrapper marks the queue row done/failed. Job types map 1:1 to
# the handlers below.

def _enqueue_precompute_after_sync(user_id) -> None:
    """After a per-user sync, warm that user's load snapshot on the worker so the
    next dashboard read is a pure cache hit (Phase 2). Deduped per user; best
    effort — a failure here never fails the sync."""
    from backend.services import worker_client
    if user_id is None or not worker_client.precompute_after_sync_enabled():
        return
    try:
        job_queue.enqueue(
            "precompute", {"user_id": str(user_id)}, enqueued_by="worker",
            dedupe_key=f"precompute:{user_id}",
        )
    except Exception:
        logger.warning("post-sync precompute enqueue failed for %s", user_id, exc_info=True)


def _h_strava_sync(p: dict) -> None:
    _run_one_sync(p["user_id"], "strava", bool(p.get("full")), p.get("triggered_by", "queue"))
    _enqueue_precompute_after_sync(p.get("user_id"))


def _h_stryd_sync(p: dict) -> None:
    _run_one_sync(p["user_id"], "stryd", bool(p.get("full")), p.get("triggered_by", "queue"))
    _enqueue_precompute_after_sync(p.get("user_id"))


def _h_backfill(p: dict) -> None:
    _run_backfill(p["user_id"])


def _h_form_metrics_backfill(p: dict) -> None:
    _run_form_metrics_backfill(p["user_id"])


def _h_banister_refit(p: dict) -> None:
    _run_banister_refit_batch()


def _h_precompute(p: dict) -> None:
    from backend.services import precompute
    precompute.precompute_user(p["user_id"], dates=p.get("dates"))


def _h_garmin_sync(p: dict) -> None:
    # Garmin scaffold (Phase 3): a no-op while GARMIN_SYNC_ENABLED is off, so a
    # stray queued garmin_sync row completes cleanly rather than erroring.
    from backend.services import garmin
    if not garmin.is_enabled():
        logger.info("garmin_sync claimed but GARMIN_SYNC_ENABLED off; skipping")
        return
    garmin.sync_garmin(p["user_id"], full=bool(p.get("full")))
    _enqueue_precompute_after_sync(p.get("user_id"))


_DISPATCH = {
    "strava_sync": _h_strava_sync,
    "stryd_sync": _h_stryd_sync,
    "backfill": _h_backfill,
    "form_metrics_backfill": _h_form_metrics_backfill,
    "banister_refit": _h_banister_refit,
    "precompute": _h_precompute,
    "garmin_sync": _h_garmin_sync,
}


class _Heartbeat:
    """Bumps a claimed job's heartbeat/lease periodically so a long run isn't
    reaped by requeue_stale mid-flight. Stopped in the wrapper's finally."""

    def __init__(self, job_id: str, interval: int = 60) -> None:
        self._stop = threading.Event()
        self._t = threading.Thread(
            target=self._run, args=(job_id, interval), daemon=True, name="worker-heartbeat"
        )
        self._t.start()

    def _run(self, job_id: str, interval: int) -> None:
        while not self._stop.wait(interval):
            try:
                job_queue.heartbeat(job_id, lease_seconds=QUEUE_LEASE_SECONDS)
            except Exception:
                pass  # a missed heartbeat just risks an early requeue; not fatal

    def stop(self) -> None:
        self._stop.set()


def _handle_job(row: dict) -> None:
    job_id = str(row["id"])
    job_type = row["job_type"]
    payload = row.get("payload") or {}
    handler = _DISPATCH.get(job_type)
    if handler is None:
        job_queue.fail(job_id, f"no handler for job_type {job_type!r}", retryable=False)
        return
    hb = _Heartbeat(job_id)
    try:
        handler(payload)
        job_queue.complete(job_id, None)
    except Exception as exc:
        logger.error("queue job %s (%s) failed: %s", job_id, job_type, exc, exc_info=True)
        job_queue.fail(job_id, str(exc), retryable=True)
    finally:
        hb.stop()


def _queue_poll_loop() -> None:
    if not QUEUE_POLL_ENABLED:
        logger.info("queue poll disabled (QUEUE_POLL_ENABLED != 1)")
        return
    job_types = list(_DISPATCH.keys())
    logger.info(
        "queue poll started: worker_id=%s interval=%ss lease=%ss",
        _WORKER_ID, QUEUE_POLL_INTERVAL_SECONDS, QUEUE_LEASE_SECONDS,
    )
    while True:
        try:
            job_queue.requeue_stale()  # cheap; recovers jobs after a sleep/crash
            claimed = job_queue.claim_next(
                _WORKER_ID, lease_seconds=QUEUE_LEASE_SECONDS, job_types=job_types
            )
            if claimed is not None:
                _executor.submit(_handle_job, claimed)
                continue  # drain: try another immediately before sleeping
        except Exception as exc:
            logger.error("queue poll error: %s", exc, exc_info=True)
        time.sleep(QUEUE_POLL_INTERVAL_SECONDS)


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


@app.post("/internal/form-metrics/backfill", dependencies=[Depends(require_worker_secret)])
def form_metrics_backfill(body: dict):
    """Backfill run_form_metrics from all historical stryd_activities for a user."""
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")

    _executor.submit(_run_form_metrics_backfill, user_id)
    return {"started": True}


# ── Read API (Hermes) ─────────────────────────────────────────────────────────
#
# Read-only endpoints on /api/* for local consumption by Hermes (the Mac Mini
# voice assistant). No X-Worker-Secret required — the tailnet/localhost binding
# is the access boundary. No writes happen here; every endpoint is GET-only.


def _resolve_read_user(user_param: str | None) -> "User":  # type: ignore[name-defined]
    """Resolve the target user for a Hermes read-API request.

    Resolution order:
    1. Explicit ?user=<username> query param
    2. WORKER_READ_API_USER env var
    3. Exactly one active user in the DB
    4. Else → 400
    """
    from backend.models import User

    username = user_param or os.getenv("WORKER_READ_API_USER")
    with Session(engine) as s:
        if username:
            user = s.query(User).filter(User.name == username, User.is_active.is_(True)).first()
            if user is None:
                raise HTTPException(status_code=400, detail=f"user {username!r} not found or inactive")
            return user
        # Fallback: exactly one active user
        active = s.query(User).filter(User.is_active.is_(True)).all()
        if len(active) == 1:
            return active[0]
        raise HTTPException(status_code=400, detail="?user= required: multiple or zero active users")


def _extract_target(structure: dict | None) -> dict:
    """Extract distance_km, duration_min, intensity from a planned_sessions structure blob.

    Tries top-level keys first, then the first block in structure["blocks"].
    Returns nulls for any field not found.
    """
    out: dict = {"distance_km": None, "duration_min": None, "intensity": None}
    if not structure or not isinstance(structure, dict):
        return out
    for key in out:
        val = structure.get(key)
        if val is None:
            for block in structure.get("blocks", []):
                if isinstance(block, dict) and block.get(key) is not None:
                    val = block[key]
                    break
        out[key] = val
    return out


def _session_to_dict(row) -> dict:
    return {
        "session_type": row.session_type,
        "name": row.name,
        "target": _extract_target(row.structure),
        "note": row.notes,
        "status": row.status,
    }


@app.get("/api/plan/today")
def plan_today(date: str | None = None, user: str | None = None):
    """Return today's planned session(s) from planned_sessions for Hermes.

    Always HTTP 200 — planned:false when no row exists so Hermes always gets
    a narratable answer.
    """
    from backend.models import PlannedSession

    resolved_user = _resolve_read_user(user)

    if date is not None:
        try:
            from datetime import date as _date
            plan_date = _date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    else:
        plan_date = datetime.now(BANGKOK_TZ).date()

    with Session(engine) as s:
        rows = (
            s.query(PlannedSession)
            .filter(
                PlannedSession.user_id == resolved_user.id,
                PlannedSession.planned_date == plan_date,
            )
            .all()
        )

    planned = len(rows) > 0
    return {
        "plan_date": plan_date.isoformat(),
        "planned": planned,
        "sessions": [_session_to_dict(r) for r in rows],
    }


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
            # Enqueue (don't execute) so scheduled + on-demand jobs flow through
            # the one pull-queue path; the poll loop below claims and runs them.
            count = _enqueue_batch_sync(None, ["strava", "stryd"], full=False, enqueued_by="schedule")
            logger.info("scheduled sync enqueued: %d job(s)", count)
        except Exception as exc:
            logger.error("scheduled sync failed to enqueue: %s", exc, exc_info=True)

        if banister_enabled and (time.monotonic() - last_banister_refit) >= _BANISTER_REFIT_INTERVAL_SECONDS:
            last_banister_refit = time.monotonic()
            try:
                job_queue.enqueue("banister_refit", {}, enqueued_by="schedule", dedupe_key="banister_refit")
            except Exception as exc:
                logger.error("scheduled banister refit failed to enqueue: %s", exc, exc_info=True)


@app.on_event("startup")
def _start_scheduler() -> None:
    threading.Thread(target=_scheduler_loop, daemon=True, name="worker-scheduler").start()
    # Second daemon: the pull-queue poll loop (claims + runs enqueued jobs).
    threading.Thread(target=_queue_poll_loop, daemon=True, name="worker-queue-poll").start()
