"""Per-provider sync status for revamp training toolbar (P1-2)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import (
    StravaActivity,
    StravaToken,
    StrydActivity,
    StrydCredentials,
    SyncJob,
    WorkerJobRun,
)


# Rows left in pending/running after a crash (UAT has June 2026 Stryd
# zombies) must not paint the toolbar as "Syncing…" forever. Incremental
# pulls finish in seconds; 15 minutes is well past a live job.
RUNNING_MAX_AGE = timedelta(minutes=15)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def job_is_live(started_at: Optional[datetime], created_at: Optional[datetime], *, now: Optional[datetime] = None) -> bool:
    """True when a pending/running SyncJob is young enough to still be executing."""
    now = now or _utc_now()
    ts = _as_utc(started_at) or _as_utc(created_at)
    if ts is None:
        return False
    return (now - ts) < RUNNING_MAX_AGE


def _provider_running(session: Session, user_id: uuid.UUID, source: str) -> bool:
    row = session.execute(
        select(SyncJob)
        .where(SyncJob.user_id == user_id)
        .where(SyncJob.source == source)
        .where(SyncJob.status.in_(("pending", "running")))
        .order_by(SyncJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return False
    return job_is_live(row.started_at, row.created_at)


def _last_completed(session: Session, user_id: uuid.UUID, source: str) -> Optional[SyncJob]:
    return session.execute(
        select(SyncJob)
        .where(SyncJob.user_id == user_id)
        .where(SyncJob.source == source)
        .where(SyncJob.status == "completed")
        .order_by(SyncJob.completed_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _last_failed(session: Session, user_id: uuid.UUID, source: str) -> Optional[SyncJob]:
    return session.execute(
        select(SyncJob)
        .where(SyncJob.user_id == user_id)
        .where(SyncJob.source == source)
        .where(SyncJob.status == "failed")
        .order_by(SyncJob.completed_at.desc(), SyncJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _pending_count(session: Session, user_id: uuid.UUID, source: str) -> int:
    return int(
        session.execute(
            select(func.count(SyncJob.id))
            .where(SyncJob.user_id == user_id)
            .where(SyncJob.source == source)
            .where(SyncJob.status == "pending")
        ).scalar()
        or 0
    )


_TOOLBAR_SYNC_JOB_TYPES = frozenset({"strava_sync", "stryd_sync"})
_NON_SYNC_JOB_TYPES = frozenset({
    "backfill",
    "precompute",
    "banister_refit",
    "daily_coach",
    "weekly_coach",
    "garmin_sync",
})


def _parse_snapshot_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return _as_utc(raw)
    try:
        return _as_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def snapshot_is_live_sync(job_snapshot: Optional[dict], *, now: Optional[datetime] = None) -> bool:
    """True when a status payload is an in-flight Strava/Stryd pull, not a stale backfill."""
    if not job_snapshot:
        return False
    st = (job_snapshot.get("status") or "").lower()
    if st not in ("running", "pending"):
        return False
    job_type = (job_snapshot.get("job_type") or "").lower()
    if job_type in _NON_SYNC_JOB_TYPES:
        return False
    if job_type and job_type not in _TOOLBAR_SYNC_JOB_TYPES and not job_type.endswith("_sync"):
        return False
    now = now or _utc_now()
    ts = (
        _parse_snapshot_ts(job_snapshot.get("started_at"))
        or _parse_snapshot_ts(job_snapshot.get("enqueued_at"))
        or _parse_snapshot_ts(job_snapshot.get("created_at"))
    )
    if ts is not None and not job_is_live(ts, ts, now=now):
        return False
    return True


_REAUTH_HINTS = (
    "unauthorized",
    "401",
    "credentials",
    "login failed",
    "reauth",
    "password",
    "reconnect",
)
_TEMP_UNAVAILABLE = "temporarily unavailable"


def _snapshot_source(job_snapshot: Optional[dict]) -> Optional[str]:
    """Which provider an in-memory / worker snapshot belongs to, if any."""
    if not job_snapshot:
        return None
    job_type = (job_snapshot.get("job_type") or "").lower()
    if job_type in _NON_SYNC_JOB_TYPES:
        return None
    if job_type in ("strava_sync", "strava"):
        return "strava"
    if job_type in ("stryd_sync", "stryd"):
        return "stryd"
    phase = (job_snapshot.get("phase") or "").lower()
    if phase == "pulling_strava":
        return "strava"
    if phase == "pulling_stryd":
        return "stryd"
    provider = (job_snapshot.get("provider") or "").lower()
    if provider in ("strava", "stryd"):
        return provider
    return None


def _snapshot_running(job_snapshot: Optional[dict], source: str) -> bool:
    """True when the in-memory / worker snapshot is actively pulling this source."""
    if not job_snapshot:
        return False
    st = (job_snapshot.get("status") or "").lower()
    if st not in ("running", "pending"):
        return False
    return _snapshot_source(job_snapshot) == source


def _snapshot_success_at(job_snapshot: Optional[dict], source: str) -> Optional[datetime]:
    """finished_at from a successful in-memory / worker snapshot for this source."""
    if _snapshot_source(job_snapshot) != source:
        return None
    st = (job_snapshot.get("status") or "").lower()
    if st not in ("success", "completed", "ok"):
        return None
    return _parse_snapshot_ts((job_snapshot or {}).get("finished_at"))


def _later(*dts: Optional[datetime]) -> Optional[datetime]:
    present = [d for d in (_as_utc(x) for x in dts) if d is not None]
    return max(present) if present else None


def _last_worker_success_at(
    session: Session, user_id: uuid.UUID, source: str
) -> Optional[datetime]:
    try:
        val = session.execute(
            select(WorkerJobRun.finished_at)
            .where(WorkerJobRun.user_id == user_id)
            .where(WorkerJobRun.job_type == f"{source}_sync")
            .where(WorkerJobRun.status == "success")
            .where(WorkerJobRun.finished_at.isnot(None))
            .order_by(WorkerJobRun.finished_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    except Exception:
        return None
    return _as_utc(val) if isinstance(val, datetime) else None


def _last_activity_synced_at(
    session: Session, user_id: uuid.UUID, source: str
) -> Optional[datetime]:
    model = StravaActivity if source == "strava" else StrydActivity
    try:
        val = session.execute(
            select(func.max(model.synced_at)).where(model.user_id == user_id)
        ).scalar()
    except Exception:
        return None
    return _as_utc(val) if isinstance(val, datetime) else None


def record_provider_sync_outcome(
    user_id: uuid.UUID,
    source: str,
    *,
    ok: bool,
    error: Optional[str] = None,
    items_synced: int = 0,
    started_at: Optional[datetime] = None,
    job_type: str = "incremental",
) -> None:
    """Write a completed/failed SyncJob so the toolbar last-synced clock persists.

    The in-process Strava pull (``run_strava_sync``) previously only updated the
    in-memory job registry. The toolbar reads last_success_at from this table,
    so a successful Sync now still showed "last synced unknown".
    """
    from backend.db import engine

    now = _utc_now()
    uid = uuid.UUID(str(user_id))
    with Session(engine) as session:
        session.add(
            SyncJob(
                user_id=uid,
                source=source,
                job_type=job_type,
                status="completed" if ok else "failed",
                started_at=_as_utc(started_at) or now,
                completed_at=now,
                activities_fetched=int(items_synced or 0),
                error_message=None if ok else (error or "Sync failed"),
            )
        )
        session.commit()


def _needs_reauth(source: str, last_error: Optional[str]) -> bool:
    if source != "stryd" or not last_error:
        return False
    blob = last_error.lower()
    return any(hint in blob for hint in _REAUTH_HINTS)


def _one_provider(
    session: Session,
    user_id: uuid.UUID,
    source: str,
    *,
    connected: bool,
    job_snapshot: Optional[dict] = None,
) -> dict[str, Any]:
    running = _snapshot_running(job_snapshot, source) or _provider_running(session, user_id, source)
    last_ok = _last_completed(session, user_id, source)
    last_fail = _last_failed(session, user_id, source)
    last_success_dt = _later(
        last_ok.completed_at if last_ok is not None else None,
        _snapshot_success_at(job_snapshot, source),
        _last_worker_success_at(session, user_id, source),
        _last_activity_synced_at(session, user_id, source),
    )
    last_error = None
    fail_at = None
    if last_fail is not None:
        fail_at = _as_utc(last_fail.completed_at) or _as_utc(last_fail.created_at)
    if fail_at is not None and (last_success_dt is None or fail_at >= last_success_dt):
        last_error = last_fail.error_message or "Sync failed"
    last_success_at = last_success_dt.isoformat() if last_success_dt is not None else None

    return {
        "connected": connected,
        "last_success_at": last_success_at,
        "pending_count": _pending_count(session, user_id, source),
        "last_error": last_error,
        "running": running,
        "needs_reauth": _needs_reauth(source, last_error),
    }


def build_providers(
    session: Session,
    user_id: uuid.UUID,
    *,
    job_snapshot: Optional[dict] = None,
) -> dict[str, Any]:
    """Strava + Stryd provider rows for ``GET /api/sync/status``."""
    uid = uuid.UUID(str(user_id))
    strava_connected = (
        session.query(StravaToken).filter(StravaToken.user_id == uid).first() is not None
    )
    stryd_cred = session.query(StrydCredentials).filter(StrydCredentials.user_id == uid).first()
    stryd_connected = stryd_cred is not None
    stryd_needs_reauth = stryd_cred is not None and getattr(stryd_cred, "auth_failed_at", None) is not None
    strava = _one_provider(
        session,
        uid,
        "strava",
        connected=strava_connected,
        job_snapshot=job_snapshot,
    )
    stryd = _one_provider(
        session,
        uid,
        "stryd",
        connected=stryd_connected,
        job_snapshot=job_snapshot,
    )
    if stryd_needs_reauth:
        stryd["needs_reauth"] = True
    return {"strava": strava, "stryd": stryd}


def dot_state(provider: dict[str, Any], *, now: Optional[datetime] = None) -> str:
    """green | amber | red for UI tests."""
    now = now or _utc_now()
    if not provider.get("connected"):
        return "red"
    if provider.get("needs_reauth"):
        return "amber"
    err = provider.get("last_error") or ""
    if err:
        if _TEMP_UNAVAILABLE in str(err).lower():
            return "amber"
        return "red"
    ts = provider.get("last_success_at")
    if not ts:
        return "amber"
    try:
        last = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return "amber"
    age = now - last
    if age >= timedelta(hours=48):
        return "amber"
    return "green"


def provider_ui_state(provider: dict[str, Any], *, now: Optional[datetime] = None) -> str:
    """syncing | failed | stale | ok — Log toolbar pills. Nav uses nav_ui_state."""
    if provider.get("running"):
        return "syncing"
    if provider.get("needs_reauth"):
        return "failed"
    err = str(provider.get("last_error") or "")
    if err and _TEMP_UNAVAILABLE not in err.lower():
        return "failed"
    if not provider.get("connected"):
        return "failed"
    colour = dot_state(provider, now=now)
    if colour == "red":
        return "failed"
    if colour == "amber":
        return "stale"
    return "ok"


_BKK = ZoneInfo("Asia/Bangkok")
_PROVIDER_NAMES = {"strava": "Strava", "stryd": "Stryd"}


def format_sync_clock(iso: Optional[str], *, now: Optional[datetime] = None) -> str:
    """06:58 same Bangkok day; Yesterday 21:14; 3 Nov otherwise."""
    if not iso:
        return ""
    try:
        last = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    last = _as_utc(last)
    if last is None:
        return ""
    last_bkk = last.astimezone(_BKK)
    now_bkk = (now or _utc_now()).astimezone(_BKK)
    clock = last_bkk.strftime("%H:%M")
    last_d = last_bkk.date()
    today = now_bkk.date()
    if last_d == today:
        return clock
    if last_d == today - timedelta(days=1):
        return f"Yesterday {clock}"
    return f"{last_bkk.day} {last_bkk.strftime('%b')}"


def nav_ui_state(provider: dict[str, Any], *, now: Optional[datetime] = None) -> str:
    """ok | syncing | attention | failed — ring colour. Maps dot_state amber to attention."""
    if provider.get("running"):
        return "syncing"
    colour = dot_state(provider, now=now)
    if colour == "red":
        return "failed"
    if colour == "amber":
        return "attention"
    return "ok"


def nav_ui_action(provider: dict[str, Any], state: str) -> Optional[str]:
    if state == "syncing":
        return None
    if not provider.get("connected"):
        return "reconnect"
    if provider.get("needs_reauth"):
        return "reauth"
    if state == "failed":
        return "retry"
    return None


def nav_ui_label(provider: dict[str, Any], state: str, *, now: Optional[datetime] = None) -> str:
    if state == "syncing":
        return "Syncing…"
    action = nav_ui_action(provider, state)
    if action == "reauth":
        return "Sign in again"
    if action == "reconnect":
        return "Reconnect"
    if action == "retry":
        return "Retry"
    clock = format_sync_clock(provider.get("last_success_at"), now=now)
    return clock or "Never"


def annotate_provider(provider: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    out = dict(provider)
    state = nav_ui_state(out, now=now)
    out["ui_state"] = state
    out["ui_action"] = nav_ui_action(out, state)
    out["ui_label"] = nav_ui_label(out, state, now=now)
    return out


def overall_state(
    providers: dict[str, Any],
    *,
    job_status: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    """Worst of the two providers. A live job paints syncing ahead of failed/attention."""
    st = (job_status or "").lower()
    states = [nav_ui_state(providers.get(k) or {}, now=now) for k in ("strava", "stryd")]
    if st in ("running", "pending") or "syncing" in states:
        return "syncing"
    if "failed" in states:
        return "failed"
    if "attention" in states:
        return "attention"
    return "ok"


def overall_label(
    providers: dict[str, Any],
    overall: str,
    *,
    now: Optional[datetime] = None,
) -> str:
    if overall == "syncing":
        return "Settings · syncing"
    if overall == "ok":
        latest = None
        for p in providers.values():
            ts = (p or {}).get("last_success_at")
            if ts and (latest is None or str(ts) > str(latest)):
                latest = ts
        clock = format_sync_clock(latest, now=now)
        return f"Settings · all synced {clock}".rstrip() if clock else "Settings · all synced"
    for key in ("strava", "stryd"):
        p = providers.get(key) or {}
        name = _PROVIDER_NAMES[key]
        if overall == "attention" and p.get("ui_state") == "attention":
            if p.get("needs_reauth") or p.get("ui_action") == "reauth":
                return f"Settings · {name} needs your password"
            return f"Settings · {name} needs attention"
        if overall == "failed" and p.get("ui_state") == "failed":
            if not p.get("connected"):
                return f"Settings · {name} not connected"
            return f"Settings · {name} sync failed"
    return "Settings"


def decorate_sync_status(payload: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Add ui_state / ui_label / ui_action per provider plus top-level overall."""
    now = now or _utc_now()
    raw = payload.get("providers") or {}
    providers = {
        key: annotate_provider(raw.get(key) or {}, now=now) for key in ("strava", "stryd")
    }
    payload["providers"] = providers
    payload["overall"] = overall_state(providers, job_status=payload.get("status"), now=now)
    payload["overall_label"] = overall_label(providers, payload["overall"], now=now)
    return payload